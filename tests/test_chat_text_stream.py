"""Text chat NDJSON stream + continuous conversation_mode helpers."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from shuxin.voice.config.config import LLMDeviceConfig
from shuxin.voice.persistence.users import UserSettings


class _FakeCompanions:
    async def _user_id_from_session(self, session_token: str) -> str:
        return "wx_stream_user"

    async def get_companion_for_user(self, *, user_id: str, companion_id: str):
        return {"companion_id": companion_id, "mbti": "ENFP", "display_name": "小E"}

    async def get_text_billing_settings(self):
        return {"chars_per_minute": 40, "text_max_chars": 500}

    async def ensure_soft_device(self, *, user_id: str):
        return {"device_id": "soft-wx_stream_user"}

    async def record_text_turn(self, **kwargs):
        return None

    async def after_companion_turn(self, **kwargs):
        return {}

    async def get_engagement_for_user(self, *, user_id: str, companion_id=None):
        return {
            "quota": {"remain_yuan": 3, "exhausted": False, "daily_allowance_left": 1},
            "care": {"unread": False},
            "streak": {"nudge": ""},
            "relationship": {},
        }


class _FakeRepo:
    def __init__(self, device: MagicMock):
        self.companions = _FakeCompanions()
        self._device = device

    async def assert_device_quota_available(self, device_id: str):
        return None

    async def get_device(self, device_id: str):
        return self._device

    async def ensure_user_dmx_llm(self, user_id: str):
        return None

    async def get_user_settings(self, user_id: str):
        return UserSettings(
            user_id=user_id,
            token="",
            llm_config={
                "model": "user-model",
                "api_key": "user-api-key",
                "base_url": "https://llm.example/v1",
            },
        )

    async def deduct_device_minutes_quota(self, device_id: str, cost_minutes: float):
        return None


def test_chat_text_stream_ndjson(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "t")
    from shuxin.voice.server import create_app

    device = MagicMock()
    device.llm = LLMDeviceConfig(
        provider="openai",
        model="soft-model",
        base_url="https://llm.example/v1",
        api_key="soft-key",
    )
    repo = _FakeRepo(device)

    class _Agent:
        def __init__(self):
            self.identity = SimpleNamespace(set_mbti=lambda *_a, **_k: None)
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 5}

        def initialize(self):
            return None

        def shutdown(self):
            return None

        def chat_stream(self, text: str):
            yield "你"
            yield "好"

    fake_service = MagicMock()
    fake_service.create_agent.return_value = _Agent()

    app = create_app()
    with patch("shuxin.voice.api.routers.text_chat.VoiceService", return_value=fake_service):
        with TestClient(app) as client:
            client.app.state.repo = repo
            res = client.post(
                "/api/chat/text/stream",
                json={
                    "session_token": "tok",
                    "companion_id": "c1",
                    "text": "hi",
                },
            )
    assert res.status_code == 200, res.text
    lines = [ln for ln in res.text.strip().split("\n") if ln.strip()]
    assert any('"type": "delta"' in ln or '"type":"delta"' in ln for ln in lines)
    done = json.loads(lines[-1])
    assert done["type"] == "done"
    assert "你" in done["reply"] and "好" in done["reply"]


def test_continuous_mode_triggers_on_sentence_final():
    from shuxin.voice.api.ws_session import _VoiceWebSocketSession

    sess = object.__new__(_VoiceWebSocketSession)
    sess.conversation_mode = "continuous"
    sess.turn_in_progress = False
    sess.listening = True
    sess.stt_pipeline = SimpleNamespace(finish=AsyncMock(return_value="你好"))
    called = {}

    async def fake_process(text: str):
        called["text"] = text

    sess._process_turn_with_text = fake_process  # type: ignore

    asyncio.get_event_loop().run_until_complete(sess._trigger_continuous_turn("你好呀"))
    assert called.get("text") == "你好呀"
    assert sess.listening is False
    assert sess.turn_in_progress is False
