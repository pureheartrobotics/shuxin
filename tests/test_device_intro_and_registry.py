from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from shuxin.voice.mbti_reveal import build_device_intro_text
from shuxin.voice.server import create_app
from shuxin.voice import voice_session_registry as vsr


def test_build_device_intro_text_with_bind_prefix() -> None:
    text = build_device_intro_text("INFJ", bind_success_prefix=True)
    assert text.startswith("绑定成功。")
    assert "INFJ" in text


def test_build_device_intro_text_without_bind_prefix() -> None:
    text = build_device_intro_text("INFJ", bind_success_prefix=False)
    assert not text.startswith("绑定成功。")
    assert "INFJ" in text


def test_maybe_push_intro_after_bind_only_first_reveal() -> None:
    vsr.reset_for_tests()
    session = SimpleNamespace(
        play_pending_device_intro=AsyncMock(return_value=True),
    )
    vsr.register("SX-000201", session)

    async def run() -> None:
        await vsr.maybe_push_intro_after_bind(
            {
                "device_code": "SX-000201",
                "mbti": {"is_first_reveal": False, "mbti": "INFJ"},
            }
        )
        await vsr.maybe_push_intro_after_bind(
            {
                "device_code": "SX-000201",
                "mbti": {"is_first_reveal": True, "mbti": "INFJ"},
            }
        )

    asyncio.run(run())
    session.play_pending_device_intro.assert_awaited_once_with(bind_success_prefix=True)
    vsr.reset_for_tests()


def test_maybe_push_intro_after_bind_no_session_is_noop() -> None:
    vsr.reset_for_tests()

    async def run() -> None:
        await vsr.maybe_push_intro_after_bind(
            {
                "device_code": "SX-000202",
                "mbti": {"is_first_reveal": True, "mbti": "INFJ"},
            }
        )

    asyncio.run(run())


def test_bind_api_triggers_intro_push_when_session_online(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_WECHAT_MOCK", "1")
    app = create_app()
    session = SimpleNamespace(play_pending_device_intro=AsyncMock(return_value=True))
    vsr.reset_for_tests()
    vsr.register("SX-000203", session)

    class FakeRepo:
        async def bind_device(self, **kwargs):
            return {
                "device_code": "SX-000203",
                "mbti": {"is_first_reveal": True, "mbti": "INFJ"},
            }

    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        res = client.post(
            "/api/devices/bind",
            json={"wx_code": "mock-code", "claim_code": "CLM-A001-0001"},
        )

    assert res.status_code == 200
    session.play_pending_device_intro.assert_awaited_once_with(bind_success_prefix=True)
    vsr.reset_for_tests()
