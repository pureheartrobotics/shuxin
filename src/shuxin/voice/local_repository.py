from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from shuxin.voice.config import DeviceConfig, DeviceConfigProvider
from shuxin.voice.storage import UserVoiceStorage
from shuxin.voice.users import DEFAULT_USER_ID, UserConfigProvider, UserSettings


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

    async def create_wechat_session(self, *, wx_code: str) -> dict[str, Any]:
        code = str(wx_code or "").strip()
        if not code:
            raise PermissionError("wx_code is required")
        user_id = f"wx_{hashlib.sha256(code.encode('utf-8')).hexdigest()[:24]}"
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        self.wechat_sessions[token] = {
            "user_id": user_id,
            "expires_at": expires_at.isoformat(),
        }
        return {
            "session_token": token,
            "expires_at": expires_at.isoformat(),
            "user_id": user_id,
        }

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
        default = self.device_provider.get(None)
        return {
            "items": [
                {
                    "device_id": default.device_id,
                    "device_code": default.device_id,
                    "auth_mode": "yaml",
                    "device_secret_configured": False,
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
        if not os.environ.get("DATABASE_URL", "").strip():
            raise RuntimeError("apply_default_stt requires DATABASE_URL (Postgres)")
        raise RuntimeError("apply_default_stt requires Postgres repository")

    async def update_device_label(self, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for admin writes")

    async def reset_claim_code(self, device_id: str) -> dict[str, Any]:
        raise RuntimeError("DATABASE_URL is required for admin writes")

    async def upsert_user(self, payload: dict[str, Any]) -> dict[str, Any]:
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
