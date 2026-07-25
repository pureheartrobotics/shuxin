"""WeChat login provisions DMX sub-key; chat_text surfaces dmx_provision_failed."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from shuxin.voice.config.config import LLMDeviceConfig
from shuxin.voice.persistence.users import UserSettings


def test_create_wechat_session_calls_ensure_user_dmx_llm() -> None:
    from shuxin.voice.persistence.user_repo import UserRepository

    repo = UserRepository.__new__(UserRepository)
    repo.pool = MagicMock()
    repo.pool.acquire = MagicMock()
    # async with pool.acquire() as conn
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"enabled": True, "deleted_at": None})
    conn.fetchval = AsyncMock(return_value="2026-07-23T00:00:00+00:00")

    class _Acquire:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args):
            return False

    repo.pool.acquire.return_value = _Acquire()
    repo.audit = AsyncMock()
    repo.ensure_user_dmx_llm = AsyncMock()

    async def fake_openid(code: str) -> str:
        return "wx_login_dmx_user01"

    with patch(
        "shuxin.voice.persistence.user_repo._resolve_openid_from_wx_code",
        return_value=fake_openid,
    ):
        out = asyncio.run(repo.create_wechat_session(wx_code="code-1"))
    assert out["user_id"] == "wx_login_dmx_user01"
    repo.ensure_user_dmx_llm.assert_awaited_once_with("wx_login_dmx_user01")


def test_chat_text_returns_dmx_provision_failed_when_admin_configured(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "t")
    monkeypatch.setenv("DMX_SYSTEM_TOKEN", "bad-admin")
    monkeypatch.setenv("DMX_API_USER_ID", "12345")
    from shuxin.voice.server import create_app

    device = MagicMock()
    device.llm = LLMDeviceConfig(model="m", base_url="https://x", api_key="")

    class FakeCompanions:
        async def _user_id_from_session(self, session_token: str) -> str:
            return "wx_no_key"

        async def get_companion_for_user(self, *, user_id: str, companion_id: str):
            return {"companion_id": companion_id, "mbti": "ENFP"}

        async def get_text_billing_settings(self):
            return {"chars_per_minute": 40, "text_max_chars": 500}

        async def ensure_soft_device(self, *, user_id: str):
            return {"device_id": "soft-wx_no_key"}

        async def record_text_turn(self, **kwargs):
            return None

    class FakeRepo:
        companions = FakeCompanions()

        async def assert_device_quota_available(self, device_id: str):
            return None

        async def get_device(self, device_id: str):
            return device

        async def ensure_user_dmx_llm(self, user_id: str):
            return None

        async def get_user_settings(self, user_id: str):
            return UserSettings(user_id=user_id, token="", llm_config={})

        async def deduct_device_minutes_quota(self, device_id: str, cost_minutes: float):
            return None

    app = create_app()
    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        with patch("shuxin.core.config.Config.load") as load_cfg:
            load_cfg.return_value = SimpleNamespace(
                llm=SimpleNamespace(api_key="", provider="", model="", base_url="")
            )
            res = client.post(
                "/api/chat/text",
                json={
                    "session_token": "sess",
                    "companion_id": "c1",
                    "text": "你好",
                },
            )
    assert res.status_code == 503, res.text
    assert res.json().get("error") == "dmx_provision_failed"
