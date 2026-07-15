"""通话会话与振铃信令（切面，不承载音频）。"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Optional

from shuxin.integrations.voice_call.billing import NoopCallBillingRecorder
from shuxin.voice import brtc_token
from shuxin.voice.api import voice_session_registry as vsr
from shuxin.voice.persistence import call_memory

logger = logging.getLogger(__name__)

_billing = NoopCallBillingRecorder()


def _ring_timeout_seconds() -> int:
    raw = str(os.environ.get("SHUXIN_CALL_RING_TIMEOUT_SECONDS") or "30").strip()
    try:
        return max(5, int(raw))
    except ValueError:
        return 30


async def _safe_send_json(session: Any, payload: dict[str, Any]) -> bool:
    """向会话发信令；单路失败不冒泡，并尽量从在线表摘除失效连接。"""
    try:
        result = await session._send_json(payload)
        if result is False:
            return False
        return True
    except Exception as exc:
        device_id = str(getattr(session, "device_id", "") or "")
        logger.warning(
            "call signaling send failed device_id=%s type=%s: %s",
            device_id,
            payload.get("type"),
            exc,
        )
        if device_id:
            vsr.unregister(device_id, session)
        return False


def _numeric_user_id(seed: str) -> str:
    """百度 RTC 要求 user_id 为数字字符串；从 device_id/user_id 派生稳定值。"""
    import hashlib

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return str(int(digest[:12], 16) % 900000000000 + 100000000000)


def build_rtc_params(*, room_name: str, user_seed: str) -> dict[str, str]:
    uid = _numeric_user_id(user_seed)
    token = brtc_token.generate_rtc_token_from_env(room_name=room_name, user_id=uid)
    return {
        "app_id": brtc_token.get_rtc_app_id(),
        "server_url": brtc_token.get_rtc_server_url(),
        "room_name": room_name,
        "user_id": uid,
        "token": token,
    }


class CallService:
    def __init__(self, repo: Any) -> None:
        self.repo = repo

    def is_enabled(self) -> bool:
        return brtc_token.rtc_call_enabled() and brtc_token.rtc_credentials_configured()

    async def initiate_by_handle(
        self,
        *,
        caller_session: Any,
        target_handle: str,
        contact_name: str = "",
    ) -> dict[str, Any]:
        if not self.is_enabled():
            return {"ok": False, "message": "RTC call feature is disabled"}

        handle = str(target_handle or "").strip().lower()
        if not handle and contact_name:
            handle = await self._resolve_contact_handle(
                caller_session.user_id, contact_name
            )
        if not handle:
            return {"ok": False, "message": "未找到被叫舒心号，请检查通讯录或舒心号"}

        callee = await self._lookup_user_by_handle(handle)
        if callee is None:
            return {"ok": False, "message": f"舒心号 {handle} 不存在"}

        callee_user_id = str(callee.get("user_id") or "").strip()
        caller_user_id = str(caller_session.user_id or "").strip()
        if not callee_user_id or not caller_user_id:
            return {"ok": False, "message": "用户身份无效"}
        if callee_user_id == caller_user_id:
            return {"ok": False, "message": "不能呼叫自己"}

        if await self._is_blocked(callee_user_id, caller_user_id):
            return {"ok": False, "message": "对方已拒接你的来电"}

        if await self._is_dnd(callee_user_id):
            return {"ok": False, "message": "对方开启了免打扰"}

        callee_sessions = await self._online_sessions_for_user(callee_user_id)
        if not callee_sessions:
            return {"ok": False, "message": f"{handle} 当前没有在线设备"}

        call_id = uuid.uuid4().hex
        room_name = f"shuxin_{call_id[:16]}"
        now = time.time()
        expires_at = now + _ring_timeout_seconds()

        caller_device_id = str(caller_session.device_id or "")
        await self._persist_call(
            call_id=call_id,
            caller_user_id=caller_user_id,
            caller_device_id=caller_device_id,
            callee_user_id=callee_user_id,
            callee_handle=handle,
            room_name=room_name,
            expires_at=expires_at,
        )

        caller_rtc = build_rtc_params(room_name=room_name, user_seed=caller_device_id)
        await _safe_send_json(
            caller_session,
            {
                "type": "call/outgoing",
                "call_id": call_id,
                "callee_handle": handle,
                "rtc": caller_rtc,
            },
        )

        caller_handle = await self._handle_for_user(caller_user_id)
        rung = 0
        for session in callee_sessions:
            rtc = build_rtc_params(
                room_name=room_name,
                user_seed=str(session.device_id or ""),
            )
            if await _safe_send_json(
                session,
                {
                    "type": "call/ring",
                    "call_id": call_id,
                    "caller_device_id": caller_device_id,
                    "caller_handle": caller_handle,
                    "rtc": rtc,
                },
            ):
                rung += 1

        if rung == 0:
            await self._end_call(call_id, reason="callee_unreachable", notify=False)
            return {"ok": False, "message": f"{handle} 当前没有在线设备"}

        return {"ok": True, "message": f"正在呼叫 {contact_name or handle}", "call_id": call_id}

    async def accept(self, session: Any, call_id: str) -> dict[str, Any]:
        device_id = str(session.device_id or "")
        row = await self._claim_answer(call_id, device_id)
        if row is None:
            return {"ok": False, "message": "通话已被接听或已结束"}

        caller_device_id = str(row.get("caller_device_id") or "")
        caller_session = vsr.get_active_session(caller_device_id)
        if caller_session is None:
            await self._end_call(call_id, reason="caller_gone", notify=False)
            await _safe_send_json(
                session,
                {
                    "type": "call/end",
                    "call_id": call_id,
                    "reason": "caller_gone",
                },
            )
            return {"ok": False, "message": "主叫已离线"}

        room_name = str(row["room_name"])
        caller_rtc = build_rtc_params(room_name=room_name, user_seed=caller_device_id)
        callee_rtc = build_rtc_params(room_name=room_name, user_seed=device_id)

        _billing.on_call_connected(call_id, device_id)
        await _safe_send_json(
            caller_session,
            {
                "type": "call/connected",
                "call_id": call_id,
                "peer_device_id": device_id,
                "rtc": caller_rtc,
            },
        )
        await _safe_send_json(
            session,
            {
                "type": "call/connected",
                "call_id": call_id,
                "peer_device_id": caller_device_id,
                "rtc": callee_rtc,
            },
        )
        await self._cancel_other_ringing(call_id, answered_device_id=device_id)
        return {"ok": True}

    async def reject(self, session: Any, call_id: str) -> dict[str, Any]:
        row = await self._get_call(call_id)
        await self._end_call(call_id, reason="rejected", notify=False)
        if row:
            caller = vsr.get_active_session(str(row.get("caller_device_id") or ""))
            if caller is not None:
                await _safe_send_json(
                    caller,
                    {
                        "type": "call/end",
                        "call_id": call_id,
                        "reason": "rejected",
                    },
                )
            await self._cancel_other_ringing(
                call_id,
                answered_device_id=str(session.device_id or ""),
                reason="rejected",
            )
        return {"ok": True}

    async def end(self, session: Any, call_id: str) -> dict[str, Any]:
        row = await self._get_call(call_id)
        if row and row.get("connected_at"):
            connected = row["connected_at"]
            if hasattr(connected, "timestamp"):
                duration = time.time() - float(connected.timestamp())
            else:
                duration = time.time() - float(connected)
            _billing.on_call_ended(call_id, duration)
        await self._end_call(call_id, reason="ended", notify=True)
        return {"ok": True}

    async def _resolve_contact_handle(self, owner_user_id: str, nickname: str) -> str:
        owner = str(owner_user_id or "").strip()
        if hasattr(self.repo, "get_contact_handle"):
            return str(
                await self.repo.get_contact_handle(owner, nickname) or ""
            ).strip().lower()
        return call_memory.get_contact_handle(owner, nickname)

    async def _lookup_user_by_handle(self, handle: str) -> Optional[dict]:
        if hasattr(self.repo, "get_user_by_shuxin_handle"):
            return await self.repo.get_user_by_shuxin_handle(handle)
        return call_memory.get_user_by_shuxin_handle(handle)

    async def _handle_for_user(self, user_id: str) -> str:
        uid = str(user_id or "").strip()
        if hasattr(self.repo, "get_shuxin_handle"):
            return str(await self.repo.get_shuxin_handle(uid) or "")
        return call_memory.get_shuxin_handle(uid)

    async def _is_blocked(self, callee_user_id: str, caller_user_id: str) -> bool:
        caller_handle = await self._handle_for_user(caller_user_id)
        if not caller_handle:
            return False
        if hasattr(self.repo, "is_caller_blocked"):
            return bool(await self.repo.is_caller_blocked(callee_user_id, caller_handle))
        return await call_memory.is_caller_blocked(callee_user_id, caller_handle)

    async def _is_dnd(self, user_id: str) -> bool:
        if hasattr(self.repo, "is_user_in_dnd"):
            return bool(await self.repo.is_user_in_dnd(user_id))
        return await call_memory.is_user_in_dnd(user_id)

    async def _online_sessions_for_user(self, user_id: str) -> list[Any]:
        """Prefer live WS registry; fall back to binding lists only as a hint filter."""
        uid = str(user_id or "").strip()
        live = vsr.list_sessions_for_user(uid)
        if live:
            return live

        # Fallback: historically seeded binding tables (tests / offline tools).
        if hasattr(self.repo, "list_active_device_ids_for_user"):
            device_ids = await self.repo.list_active_device_ids_for_user(uid)
        else:
            device_ids = call_memory.list_active_device_ids_for_user(uid)
        sessions: list[Any] = []
        for device_id in device_ids:
            session = vsr.get_active_session(str(device_id))
            if session is not None:
                sessions.append(session)
        return sessions

    async def _persist_call(self, **fields: Any) -> None:
        if hasattr(self.repo, "create_voice_call"):
            await self.repo.create_voice_call(**fields)
        else:
            call_memory.create_voice_call(**fields)

    async def _claim_answer(self, call_id: str, device_id: str) -> Optional[dict]:
        if hasattr(self.repo, "claim_voice_call_answer"):
            return await self.repo.claim_voice_call_answer(call_id, device_id)
        return call_memory.claim_voice_call_answer(call_id, device_id)

    async def _get_call(self, call_id: str) -> Optional[dict]:
        if hasattr(self.repo, "get_voice_call"):
            return await self.repo.get_voice_call(call_id)
        return call_memory.get_voice_call(call_id)

    async def _cancel_other_ringing(
        self,
        call_id: str,
        answered_device_id: str,
        reason: str = "answered_elsewhere",
    ) -> None:
        row = await self._get_call(call_id)
        if not row:
            return
        callee_user_id = str(row.get("callee_user_id") or "").strip()
        for session in await self._online_sessions_for_user(callee_user_id):
            if str(session.device_id) == answered_device_id:
                continue
            await _safe_send_json(
                session,
                {
                    "type": "call/cancel",
                    "call_id": call_id,
                    "reason": reason,
                },
            )

    async def _end_call(self, call_id: str, reason: str, notify: bool = False) -> None:
        row = await self._get_call(call_id)
        if hasattr(self.repo, "end_voice_call"):
            await self.repo.end_voice_call(call_id, reason=reason)
        else:
            call_memory.end_voice_call(call_id, reason=reason)
        if not notify or not row:
            return
        payload = {"type": "call/end", "call_id": call_id, "reason": reason}
        for device_id in {row.get("caller_device_id"), row.get("answered_device_id")}:
            if not device_id:
                continue
            session = vsr.get_active_session(str(device_id))
            if session is not None:
                await _safe_send_json(session, payload)
