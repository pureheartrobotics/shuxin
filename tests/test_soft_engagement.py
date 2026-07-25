"""Soft engagement loops: care, streak, quota 402."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from shuxin.voice.config.config import LLMDeviceConfig
from shuxin.voice.engagement.soft_loops import (
    care_key_for,
    is_care_due,
    pick_care_message,
    streak_nudge_text,
)
from shuxin.voice.persistence.users import UserSettings


def test_care_due_when_idle():
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    last = now - timedelta(hours=7)
    assert is_care_due(last, now=now) is True
    assert is_care_due(now - timedelta(hours=1), now=now) is False
    assert is_care_due(None, now=now) is True


def test_streak_nudge_every_three():
    assert streak_nudge_text(0) is None
    assert streak_nudge_text(2) is None
    assert streak_nudge_text(3)
    assert streak_nudge_text(6)


def test_care_message_stable_for_key():
    key = care_key_for(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert pick_care_message(key) == pick_care_message(key)


class _FakeCompanions:
    def __init__(self):
        self.engagement_calls = 0

    async def _user_id_from_session(self, session_token: str) -> str:
        return "wx_engage_user"

    async def get_companion_for_user(self, *, user_id: str, companion_id: str):
        return {"companion_id": companion_id, "mbti": "ENFP", "display_name": "小E"}

    async def get_text_billing_settings(self):
        return {"chars_per_minute": 40, "text_max_chars": 500}

    async def ensure_soft_device(self, *, user_id: str):
        return {"device_id": "soft-wx_engage_user"}

    async def record_text_turn(self, **kwargs):
        return None

    async def after_companion_turn(self, **kwargs):
        return {}

    async def get_engagement_for_user(self, *, user_id: str, companion_id=None):
        self.engagement_calls += 1
        return {
            "quota": {
                "remain_yuan": 1.2,
                "exhausted": False,
                "daily_allowance_left": 1.2,
                "subscription_minutes_left": 0,
                "fuel_minutes_left": 0,
            },
            "care": {"unread": False, "message": "", "care_key": "never"},
            "streak": {"today_turns": 3, "today_companion_turns": 3, "nudge": "再聊几轮，关系会更近一点。"},
            "relationship": {
                "stage_id": "familiar",
                "stage_label": "熟悉",
                "next_hint": "再近一点就到「伙伴」",
                "latest_milestone": None,
            },
        }


class _FakeRepo:
    def __init__(self, device: MagicMock, *, exhaust: bool = False):
        self.companions = _FakeCompanions()
        self._device = device
        self._exhaust = exhaust

    async def assert_device_quota_available(self, device_id: str):
        if self._exhaust:
            raise PermissionError("陪伴点已用尽，请充值")

    async def get_device(self, device_id: str):
        return self._device

    async def get_device_quota(self, device_id: str, *, admin_detail: bool = False):
        return {
            "remain_yuan": 0.0,
            "exhausted": True,
            "daily_allowance_left": 0.0,
            "subscription_minutes_left": 0.0,
            "fuel_minutes_left": 0.0,
        }

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


def _client_with_repo(repo):
    from shuxin.voice.server import create_app

    app = create_app()
    with TestClient(app) as client:
        client.app.state.repo = repo
        yield client


def test_chat_text_402_quota_exhausted(monkeypatch):
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "t")
    device = MagicMock()
    device.llm = LLMDeviceConfig(
        provider="openai",
        model="m",
        base_url="https://x/v1",
        api_key="k",
    )
    repo = _FakeRepo(device, exhaust=True)
    from shuxin.voice.server import create_app

    app = create_app()
    with TestClient(app) as client:
        client.app.state.repo = repo
        res = client.post(
            "/api/chat/text",
            json={
                "session_token": "sess",
                "companion_id": "c1",
                "text": "你好",
            },
        )
    assert res.status_code == 402
    body = res.json()
    assert body["error"] == "quota_exhausted"
    assert body["error_kind"] == "daily_allowance_exhausted"
    assert body["quota"]["exhausted"] is True


def test_chat_text_includes_engagement(monkeypatch):
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "t")
    device = MagicMock()
    device.llm = LLMDeviceConfig(
        provider="openai",
        model="m",
        base_url="https://x/v1",
        api_key="k",
    )
    repo = _FakeRepo(device, exhaust=False)
    fake_agent = MagicMock()
    fake_agent.identity = MagicMock()
    fake_agent.chat.return_value = "嗨"
    fake_agent.last_usage = {"prompt_tokens": 10, "completion_tokens": 5}

    with patch("shuxin.voice.service.VoiceService") as VS:
        inst = VS.return_value
        inst.create_agent.return_value = fake_agent
        from shuxin.voice.server import create_app

        app = create_app()
        with TestClient(app) as client:
            client.app.state.repo = repo
            res = client.post(
                "/api/chat/text",
                json={
                    "session_token": "sess",
                    "companion_id": "c1",
                    "text": "你好呀",
                },
            )
    assert res.status_code == 200
    body = res.json()
    assert body["engagement"]["streak"]["nudge"]
    assert body["engagement"]["relationship"]["stage_label"]
    assert repo.companions.engagement_calls == 1
