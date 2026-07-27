from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from shuxin.voice.persistence.mall_local_repo import MallLocalRepository
from shuxin.voice.persistence.time_display import format_beijing_iso
from shuxin.voice.persistence.memory_summary import should_merge_summary
from shuxin.voice.persistence.storage import UserVoiceStorage
from shuxin.voice.persistence.users import DEFAULT_USER_ID, FACTORY_PROBE_USER_ID, UserConfigProvider, UserSettings
from shuxin.voice.persistence.base_repo import _openid_from_wx_code


class VoiceLocalRepository:
    """没有 DATABASE_URL 时的 demo fallback，沿用 YAML 和本地文件存储。"""

    def __init__(
        self,
        *,
        device_provider: DeviceConfigProvider,
        user_provider: UserConfigProvider,
        shuxin_home: Path,
        out_dir: Path,
    ) -> None:
        self.device_provider = device_provider
        self.user_provider = user_provider
        self.shuxin_home = shuxin_home
        self.out_dir = out_dir
        self.wechat_sessions: dict[str, dict[str, str]] = {}
        self.mall = MallLocalRepository(parent=self)

    async def create_wechat_session(self, *, wx_code: str) -> dict[str, Any]:
        user_id = await _openid_from_wx_code(wx_code)
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        expires_str = format_beijing_iso(expires_at)
        self.wechat_sessions[token] = {
            "user_id": user_id,
            "expires_at": expires_str,
        }
        result = {
            "session_token": token,
            "expires_at": expires_str,
            "user_id": user_id,
        }
        await self.ensure_user_dmx_llm(user_id)
        return result

    async def ensure_user_dmx_llm(self, user_id: str) -> None:
        return None

    async def get_user_quota_by_user_id(self, user_id: str) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "configured": False,
            "exhausted": False,
            "remain_yuan": None,
            "used_yuan": None,
            "message": "",
        }

    async def get_user_quota_by_session(self, session_token: str) -> dict[str, Any]:
        selected = str(session_token or "").strip()
        session = self.wechat_sessions.get(selected)
        if not session:
            raise PermissionError("session_token is invalid or expired")
        return await self.get_user_quota_by_user_id(session["user_id"])

    async def get_user_profile_by_session(self, session_token: str) -> dict[str, Any]:
        selected = str(session_token or "").strip()
        session = self.wechat_sessions.get(selected)
        if not session:
            raise PermissionError("session_token is invalid or expired")
        user_id = str(session["user_id"])
        quota = await self.get_user_quota_by_user_id(user_id)
        quota_payload = {key: value for key, value in quota.items() if key != "user_id"}
        meta = dict(getattr(self, "user_metadata", {}).get(user_id) or {})
        return {
            "user_id": user_id,
            "nickname": str(meta.get("nickname") or ""),
            "avatar_url": str(meta.get("avatar_url") or ""),
            "avatar_key": str(meta.get("avatar_key") or ""),
            "roles": {"factory_qa": False},
            "quota": quota_payload,
        }

    async def update_user_profile_by_session(
        self,
        session_token: str,
        *,
        nickname=None,
        avatar_key=None,
    ) -> dict[str, Any]:
        profile = await self.get_user_profile_by_session(session_token)
        user_id = profile["user_id"]
        if not hasattr(self, "user_metadata"):
            self.user_metadata = {}
        meta = dict(self.user_metadata.get(user_id) or {})
        if nickname is not None:
            name = str(nickname or "").strip()
            if name and len(name) > 32:
                raise ValueError("nickname must be 1..32 characters")
            if name:
                meta["nickname"] = name
            else:
                meta.pop("nickname", None)
        if avatar_key is not None:
            from shuxin.voice.cdn.purposes import resolve_key
            from shuxin.voice.cdn.qiniu import public_url_with_version

            key = str(avatar_key or "").strip().lstrip("/")
            expected = resolve_key("ugc_avatar", user_id=user_id)
            if key and key != expected:
                raise ValueError("avatar_key does not belong to this user")
            if key:
                meta["avatar_key"] = key
                meta["avatar_updated_at"] = "v1"
                meta["avatar_url"] = public_url_with_version(key, "v1")
            else:
                meta.pop("avatar_key", None)
                meta.pop("avatar_url", None)
                meta.pop("avatar_updated_at", None)
        self.user_metadata[user_id] = meta
        return await self.get_user_profile_by_session(session_token)

    async def clear_user_avatar_by_session(self, session_token: str) -> dict[str, Any]:
        profile = await self.get_user_profile_by_session(session_token)
        user_id = profile["user_id"]
        if hasattr(self, "user_metadata") and user_id in self.user_metadata:
            self.user_metadata[user_id].pop("avatar_key", None)
            self.user_metadata[user_id].pop("avatar_url", None)
            self.user_metadata[user_id].pop("avatar_updated_at", None)
        out = await self.get_user_profile_by_session(session_token)
        out["cdn_delete"] = {"ok": True, "status": 612}
        return out

    async def assert_user_quota_available(self, user_id: str) -> None:
        return None

    async def get_device_quota(self, device_id: str, *, admin_detail: bool = False) -> dict[str, Any]:
        return {
            "device_id": device_id,
            "configured": False,
            "exhausted": False,
            "remain_yuan": 999.0,
            "total_minutes_left": 999.0,
            "subscription_minutes_left": 999.0,
            "fuel_minutes_left": 0.0,
            "daily_allowance_left": 0.0,
            "subscription_expires_at": None,
            "unlimited_quota": True,
            "message": "",
        }

    async def deduct_device_minutes_quota(self, device_id: str, cost_minutes: float) -> None:
        return None

    async def assert_device_quota_available(self, device_id: str) -> None:
        return None

    async def top_up_user_dmx_quota(
        self,
        user_id: str,
        *,
        add_yuan: float,
        note: str = "",
    ) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for admin writes")

    async def create_payment_order(self, *, session_token: str, plan_id: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for payment")

    async def attach_prepay_id(self, *, out_trade_no: str, prepay_id: str) -> None:
        raise RuntimeError("DATABASE_URL is required for payment")

    async def list_payment_orders_by_session(
        self,
        session_token: str,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for payment")

    async def fulfill_payment_order(
        self,
        *,
        out_trade_no: str,
        wx_transaction_id: str,
        notify_payload: dict[str, Any],
    ) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for payment")

    async def get_user_settings(self, user_id: str | None) -> UserSettings:
        """YAML path: return settings without token gate (parity with Postgres)."""
        return self.user_provider.get(user_id)

    async def authenticate_user(self, user_id: str | None, token: str | None) -> UserSettings:
        return self.user_provider.authenticate(user_id, token)

    async def authenticate_device(
        self,
        device_code: str | None,
        device_secret: str | None,
    ) -> UserSettings:
        expected = os.environ.get("SHUXIN_DEVICE_SHARED_SECRET", "")
        if expected and device_secret != expected:
            raise PermissionError("invalid device secret")
        return self.user_provider.authenticate(DEFAULT_USER_ID, "")

    async def authenticate_device_for_factory(
        self,
        device_code: str | None,
        device_secret: str | None,
    ) -> UserSettings:
        expected = os.environ.get("SHUXIN_DEVICE_SHARED_SECRET", "")
        if expected and device_secret != expected:
            raise PermissionError("invalid device secret")
        return UserSettings(
            user_id=FACTORY_PROBE_USER_ID,
            token="",
            llm_config={},
            agent_id="",
        )

    async def get_device(self, device_id: str | None) -> DeviceConfig:
        return self.device_provider.get(device_id)

    async def touch_device_status(
        self,
        *,
        device_id: str,
        online: bool,
        session_id: str = "",
        error: str = "",
    ) -> None:
        return None

    async def ensure_session(
        self,
        *,
        session_id: str,
        user_id: str,
        device_id: str,
        client_id: str,
    ) -> None:
        return None

    async def record_turn(
        self,
        *,
        user_settings: UserSettings,
        device_id: str,
        client_id: str,
        session_id: str,
        turn_id: str,
        user_text: str,
        reply_text: str,
        input_audio: Path | None,
        reply_audio: Path | None,
        timings: dict[str, int],
        warning: str = "",
    ) -> None:
        storage = UserVoiceStorage(self.shuxin_home, self.out_dir, user_settings.user_id)
        await storage.record_turn(
            user_settings=user_settings,
            device_id=device_id,
            client_id=client_id,
            session_id=session_id,
            turn_id=turn_id,
            user_text=user_text,
            reply_text=reply_text,
            input_audio=input_audio,
            reply_audio=reply_audio,
            timings=timings,
            warning=warning,
        )

    async def status(self, user_settings: UserSettings) -> dict[str, Any]:
        return await UserVoiceStorage(
            self.shuxin_home,
            self.out_dir,
            user_settings.user_id,
        ).status(user_settings)

    async def export_summary(self, user_settings: UserSettings) -> dict[str, Any]:
        return UserVoiceStorage(
            self.shuxin_home,
            self.out_dir,
            user_settings.user_id,
        ).export_summary()

    async def compress_if_needed(self, user_settings: UserSettings) -> dict[str, Any]:
        return await UserVoiceStorage(
            self.shuxin_home,
            self.out_dir,
            user_settings.user_id,
        ).compress_if_needed(user_settings)

    async def purge_expired_audio_attachments(self, *, retention_hours: int) -> dict[str, int]:
        purged = 0
        bytes_freed = 0
        users_root = self.out_dir / "users"
        if not users_root.exists():
            return {"purged": 0, "bytes_freed": 0}
        for user_dir in users_root.iterdir():
            if not user_dir.is_dir():
                continue
            try:
                storage = UserVoiceStorage(self.shuxin_home, self.out_dir, user_dir.name)
            except ValueError:
                continue
            result = await storage.purge_expired_audio_attachments(
                retention_hours=retention_hours
            )
            purged += int(result.get("purged", 0))
            bytes_freed += int(result.get("bytes_freed", 0))
        return {"purged": purged, "bytes_freed": bytes_freed}

    async def purge_expired_factory_verify_logs(self, *, retention_days: int) -> dict[str, int]:
        return {"purged": 0}

    async def maybe_merge_rolling_summary(
        self,
        user_settings: UserSettings,
        device: DeviceConfig | None,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        storage = UserVoiceStorage(
            self.shuxin_home,
            self.out_dir,
            user_settings.user_id,
        )
        summary = storage.export_summary()
        if not should_merge_summary(summary, force=force):
            return {"merged": False, "reason": "not_due"}
        return await storage.maybe_merge_rolling_summary(device, force=force)

    async def provision_device(self, device_code: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for factory provisioning")

    async def provision_devices_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for factory provisioning")

    async def next_device_sequence(self, device_prefix: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for factory provisioning")

    async def bind_device(
        self,
        *,
        wx_code: str,
        session_token: str = "",
        claim_code: str = "",
        device_code: str = "",
    ) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mini-program binding")

    async def unbind_device(self, *, user_id: str, device_code: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for device unbinding")

    async def list_my_devices(self, *, wx_code: str, session_token: str = "") -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mini-program device list")

    async def unbind_device_by_wx_code(
        self,
        *,
        wx_code: str,
        device_code: str,
    ) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mini-program device unbinding")

    async def unbind_device_by_session(
        self,
        *,
        session_token: str,
        device_code: str,
    ) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for mini-program device unbinding")

    async def list_devices(self, *, limit: int = 50, cursor: str = "", q: str = "") -> dict[str, Any]:
        from shuxin.voice.persistence.device_secret_crypto import device_secret_encryption_configured

        default = self.device_provider.get(None)
        shared = os.environ.get("SHUXIN_DEVICE_SHARED_SECRET", "dev-device-secret")
        return {
            "items": [
                {
                    "device_id": default.device_id,
                    "device_code": default.device_id,
                    "auth_mode": "shared_secret",
                    "device_secret_configured": bool(shared),
                    "device_secret_masked": f"{shared[:4]}…{shared[-4:]}" if len(shared) > 8 else "****",
                    "device_secret_retrievable": bool(shared),
                    "device_secret_hint": "global_shared_secret",
                    "lifecycle_status": "provisioned",
                    "bound_user_id": DEFAULT_USER_ID,
                    "active_binding_id": "",
                    "claim_code": "",
                    "claim_status": "",
                    "stt_config": default.stt.__dict__,
                    "tts_config": default.tts.__dict__,
                    "llm_config": default.llm.__dict__,
                    "enabled": True,
                    "note": "yaml fallback",
                    "metadata": {},
                    "status": {"online": False, "last_seen": "", "current_session_id": "", "last_error": ""},
                }
            ],
            "next_cursor": "",
            "device_secret_encryption_configured": device_secret_encryption_configured(),
        }

    async def reveal_device_secret(self, device_id: str) -> dict[str, Any]:
        default = self.device_provider.get(device_id)
        shared = os.environ.get("SHUXIN_DEVICE_SHARED_SECRET", "dev-device-secret")
        return {
            "device_id": default.device_id,
            "device_secret": shared,
            "hint": "global_shared_secret",
        }

    async def list_voice_demo_targets(self) -> dict[str, Any]:
        default = self.device_provider.get(None)
        shared = os.environ.get("SHUXIN_DEVICE_SHARED_SECRET", "dev-device-secret")
        settings = self.user_provider.get(DEFAULT_USER_ID)
        llm = settings.llm_config or {}
        return {
            "items": [
                {
                    "user_id": settings.user_id,
                    "device_id": default.device_id,
                    "device_code": default.device_id,
                    "device_secret": shared,
                    "online": False,
                    "secret_hint": "global_shared_secret",
                    "llm_model": str(llm.get("model") or ""),
                    "llm_base_url": str(llm.get("base_url") or ""),
                    "llm_api_key_configured": bool(llm.get("api_key")),
                }
            ]
        }

    async def list_users(self, *, limit: int = 50, cursor: str = "", q: str = "") -> dict[str, Any]:
        settings = self.user_provider.get(DEFAULT_USER_ID)
        return {
            "items": [
                {
                    "user_id": settings.user_id,
                    "token_configured": bool(settings.token),
                    "audio_quota_mb": settings.audio_quota_mb,
                    "token_quota_total": 0,
                    "token_quota_used": 0,
                    "quota_note": "",
                    "llm_config": settings.llm_config or {},
                    "enabled": True,
                    "agent_id": "",
                    "metadata": {},
                    "created_at": "",
                    "updated_at": "",
                }
            ],
            "next_cursor": "",
        }

    async def list_bindings(self, *, limit: int = 50, cursor: str = "", q: str = "") -> dict[str, Any]:
        return {"items": [], "next_cursor": ""}

    async def admin_bind_device(self, *, user_id: str, device_id: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for admin binding writes")

    async def admin_unbind_device(self, *, binding_id: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for admin binding writes")

    async def upsert_device(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for admin writes")

    async def soft_delete_device(self, device_id: str) -> None:
        raise RuntimeError("DATABASE_URL is required for admin writes")

    async def rotate_device_secret(self, device_id: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for admin writes")

    async def apply_default_stt_to_all_devices(self) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for apply_default_stt_to_all_devices")

    async def apply_default_tts_to_all_devices(self) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for apply_default_tts_to_all_devices")

    async def ensure_default_agents(self) -> None:
        return None

    async def list_agents(self, *, limit: int = 50, cursor: str = "", q: str = "") -> dict[str, Any]:
        import os

        from shuxin.voice.persistence.agents import AgentRecord

        record = AgentRecord(
            agent_id="shuxin",
            display_name="初心",
            voice_type=os.environ.get("VOLCENGINE_TTS_VOICE_TYPE", ""),
            soul_path="data/agents/shuxin/SOUL.md",
        )
        return {"items": [record.to_admin_dict()], "next_cursor": ""}

    async def get_agent(self, agent_id: str) -> AgentRecord:
        import os

        from shuxin.voice.persistence.agents import AgentRecord, DEFAULT_AGENT_ID

        selected = agent_id.strip() or DEFAULT_AGENT_ID
        return AgentRecord(
            agent_id=selected,
            display_name=selected,
            voice_type=os.environ.get("VOLCENGINE_TTS_VOICE_TYPE", ""),
            soul_path="data/agents/shuxin/SOUL.md",
        )

    async def get_user_agent_id(self, user_id: str) -> str:
        from shuxin.voice.persistence.agents import DEFAULT_AGENT_ID

        return DEFAULT_AGENT_ID

    async def create_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for agent writes")

    async def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for agent writes")

    async def soft_delete_agent(self, agent_id: str) -> None:
        raise RuntimeError("DATABASE_URL is required for agent writes")

    async def patch_user(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for patch_user")

    async def update_device_label(self, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for admin writes")

    async def update_device_mbti(self, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for admin writes")

    async def mark_mbti_locked(self, device_id: str) -> dict[str, Any]:
        return {"device_id": device_id, "mbti_status": "locked"}

    async def try_reveal_and_lock(self, device_id: str, revealed_by: str) -> dict[str, Any] | None:
        return None

    async def mark_device_intro_played(self, device_id: str) -> dict[str, Any]:
        return {"device_id": device_id, "device_intro_played": True}

    async def reset_claim_code(self, device_id: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for admin writes")

    async def upsert_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for admin writes")

    async def hard_delete_user_for_test(self, user_id: str) -> None:
        raise RuntimeError("DATABASE_URL is required for admin writes")

    async def soft_delete_user(self, user_id: str) -> None:
        raise RuntimeError("DATABASE_URL is required for admin writes")

    async def record_adapter_action(
        self,
        *,
        adapter_name: str,
        action: str,
        request_json: dict[str, Any],
        result_json: dict[str, Any] | list[Any] | None = None,
        error: str = "",
    ) -> None:
        return None

    async def get_active_announcements(self) -> list[dict[str, Any]]:
        return []

    async def admin_list_announcements(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return []

    async def admin_upsert_announcement(self, **kwargs) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for announcements")

    async def admin_delete_announcement(self, announcement_id: int) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for announcements")

    async def create_feedback(self, *, user_id: str, content: str, contact: str = "") -> dict[str, Any]:
        return {"id": 1, "ok": True}

    async def admin_list_feedbacks(self, *, limit: int = 50, offset: int = 0, status: str | None = None) -> list[dict[str, Any]]:
        return []

    async def admin_update_feedback(self, feedback_id: int, **kwargs) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for feedbacks")

    async def get_pricing_by_type(self, service_type: str) -> dict[str, float]:
        return {}

    async def insert_expenditure(self, **kwargs) -> None:
        return None

    async def get_monthly_expenditure_summary(self, month_str: str) -> dict[str, Any]:
        return {
            "total_cost": 0.0,
            "breakdown": {
                "llm": {"cost": 0.0, "percentage": 0.0},
                "stt": {"cost": 0.0, "percentage": 0.0},
                "tts": {"cost": 0.0, "percentage": 0.0},
            },
            "total_turns": 0,
            "average_turn_cost": 0.0,
        }

    async def list_expenditures(self, **kwargs) -> dict[str, Any]:
        return {"items": [], "next_cursor": ""}

    async def delete_expenditure(self, expenditure_id: str) -> bool:
        return False

    async def delete_monthly_expenditures(self, month_str: str) -> int:
        return 0

    async def get_all_pricing(self) -> dict[str, Any]:
        return {"stt": {}, "tts": {}, "llm": {}}

    async def update_pricing(self, pricing_type: str, pricing_dict: dict[str, float]) -> None:
        raise RuntimeError("DATABASE_URL is required for pricing updates")

