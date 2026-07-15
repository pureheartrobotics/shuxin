"""Track active voice WebSocket sessions for bind-time intro push and factory verify."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_active_sessions: dict[str, Any] = {}
_intro_locks: dict[str, asyncio.Lock] = {}

# factory_verify 并发控制：同一设备同时只允许一个验收请求
# key = device_id, value = asyncio.Event（ack 到达时 set()）
_pending_verify: dict[str, asyncio.Event] = {}


def register(device_id: str, session: Any) -> None:
    selected = str(device_id or "").strip()
    if not selected:
        return
    _active_sessions[selected] = session


def unregister(device_id: str, session: Any) -> None:
    selected = str(device_id or "").strip()
    if not selected:
        return
    if _active_sessions.get(selected) is session:
        _active_sessions.pop(selected, None)


def get_active_session(device_id: str) -> Any | None:
    selected = str(device_id or "").strip()
    if not selected:
        return None
    return _active_sessions.get(selected)


def list_sessions_for_user(user_id: str) -> list[Any]:
    """Return currently registered WS sessions for a user_id (online discovery)."""
    selected = str(user_id or "").strip()
    if not selected:
        return []
    sessions: list[Any] = []
    for session in _active_sessions.values():
        if str(getattr(session, "user_id", "") or "").strip() == selected:
            sessions.append(session)
    return sessions


def intro_lock(device_id: str) -> asyncio.Lock:
    selected = str(device_id or "").strip()
    if selected not in _intro_locks:
        _intro_locks[selected] = asyncio.Lock()
    return _intro_locks[selected]


def factory_verify_start(device_id: str) -> asyncio.Event | None:
    """开始一次工厂验收。返回 Event 对象供调用方 await；若已有进行中的验收返回 None。"""
    selected = str(device_id or "").strip()
    if not selected:
        return None
    if selected in _pending_verify:
        return None
    event = asyncio.Event()
    _pending_verify[selected] = event
    return event


def factory_verify_ack(device_id: str) -> bool:
    """设备回传 ack，触发等待中的 Event。返回 True 表示成功配对。"""
    selected = str(device_id or "").strip()
    event = _pending_verify.get(selected)
    if event is None:
        return False
    event.set()
    return True


def factory_verify_cleanup(device_id: str) -> None:
    """验收完成或超时后清理，释放并发锁。"""
    selected = str(device_id or "").strip()
    _pending_verify.pop(selected, None)


def reset_for_tests() -> None:
    _active_sessions.clear()
    _intro_locks.clear()
    _pending_verify.clear()


async def maybe_push_intro_after_bind(result: dict[str, Any]) -> None:
    """If device WS is online right after first bind, play pending intro immediately."""
    mbti = result.get("mbti") or {}
    if not mbti.get("is_first_reveal"):
        return
    device_id = str(result.get("device_code") or result.get("device_id") or "")
    session = get_active_session(device_id)
    if session is None:
        return
    try:
        await session.play_pending_device_intro(bind_success_prefix=True)
    except Exception as exc:
        logger.warning("bind intro push failed for %s: %s", device_id, exc)
