"""chat_text must merge soft-device + user LLM via merge_llm_device_config."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from shuxin.voice.config.config import LLMDeviceConfig
from shuxin.voice.persistence.users import UserSettings, DEFAULT_USER_ID


class _FakeCompanions:
    async def _user_id_from_session(self, session_token: str) -> str:
        assert session_token == "sess"
        return "wx_no_token_user"

    async def get_companion_for_user(self, *, user_id: str, companion_id: str):
        return {"companion_id": companion_id, "mbti": "ENFP", "display_name": "小E"}

    async def get_text_billing_settings(self):
        return {"chars_per_minute": 40, "text_max_chars": 500}

    async def ensure_soft_device(self, *, user_id: str):
        return {"device_id": "soft-user-1"}

    async def record_text_turn(self, **kwargs):
        return None

    async def get_engagement_for_user(self, *, user_id: str, companion_id=None):
        return {
            "quota": {"remain_yuan": 9, "exhausted": False, "daily_allowance_left": 1.5},
            "care": {"unread": False, "message": "", "care_key": "never"},
            "streak": {"today_turns": 1, "today_companion_turns": 1, "nudge": ""},
        }


class _FakeRepo:
    def __init__(self, device: MagicMock):
        self.companions = _FakeCompanions()
        self._device = device
        self.ensure_dmx_called = False

    async def assert_device_quota_available(self, device_id: str):
        return None

    async def get_device(self, device_id: str):
        return self._device

    async def ensure_user_dmx_llm(self, user_id: str):
        self.ensure_dmx_called = True

    async def get_user_settings(self, user_id: str):
        # WeChat users have empty users.token; must still return llm_config
        return UserSettings(
            user_id=user_id,
            token="",
            llm_config={
                "model": "user-model",
                "api_key": "user-api-key",
                "base_url": "https://llm.example/v1",
            },
        )

    async def authenticate_user(self, user_id: str, password: str):
        raise AssertionError("chat_text must not call authenticate_user")

    async def deduct_device_minutes_quota(self, device_id: str, cost_minutes: float):
        return None


def test_chat_text_merges_user_llm_into_soft_device(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "t")
    from shuxin.voice.server import create_app

    device = MagicMock()
    device.llm = LLMDeviceConfig(
        provider="openai",
        model="device-model",
        base_url="https://device.example/v1",
        api_key="device-key",
    )

    fake_agent = MagicMock()
    fake_agent.identity = MagicMock()
    fake_agent.chat.return_value = "你好呀"
    fake_agent.last_usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cache_tokens": 0,
    }

    fake_service = MagicMock()
    fake_service.create_agent.return_value = fake_agent

    app = create_app()
    with TestClient(app) as client:
        repo = _FakeRepo(device)
        app.state.repo = repo
        with patch(
            "shuxin.voice.api.routers.companions.VoiceService",
            return_value=fake_service,
        ):
            res = client.post(
                "/api/chat/text",
                json={
                    "session_token": "sess",
                    "companion_id": "cmp-1",
                    "text": "你好",
                },
            )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reply"] == "你好呀"
    assert body["usage"]["chars_per_minute"] == 40
    assert "estimate_minutes_typing" in body["usage"]
    assert repo.ensure_dmx_called is True
    # user override wins for non-empty fields
    assert device.llm.api_key == "user-api-key"
    assert device.llm.model == "user-model"
    fake_service.create_agent.assert_called_once()
    fake_agent.identity.set_mbti.assert_called_with("ENFP")


def test_get_user_settings_allows_empty_token() -> None:
    """Regression: WeChat users have empty users.token; load must not require it."""
    settings = UserSettings(
        user_id="wx_abc",
        token="",
        llm_config={"api_key": "k"},
    )
    assert settings.user_id == "wx_abc"
    assert settings.token == ""
    assert settings.llm_config["api_key"] == "k"
    assert settings.user_id != DEFAULT_USER_ID
