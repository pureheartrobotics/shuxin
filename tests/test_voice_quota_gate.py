from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from shuxin.voice.dmx_client import QUOTA_EXHAUSTED_MESSAGE
from shuxin.voice.server import _VoiceWebSocketSession


class MockWebSocket:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    async def send_text(self, text: str) -> None:
        self.sent_messages.append(json.loads(text))


def _make_session(repo: MagicMock | None = None) -> tuple[_VoiceWebSocketSession, MockWebSocket]:
    ws = MockWebSocket()
    session = _VoiceWebSocketSession(
        websocket=ws,
        service=MagicMock(),
        repo=repo or MagicMock(),
        shuxin_home=Path("/tmp"),
        default_device_id="SX-000001",
        out_dir=Path("/tmp"),
    )
    session.user_settings = MagicMock(user_id="user-1")
    session.user_id = "user-1"
    session.device_id = "SX-000001"
    return session, ws


@pytest.mark.anyio
async def test_process_turn_quota_exhausted_even_when_agent_exists() -> None:
    """Agent 已初始化时，每轮仍应拦截额度耗尽。"""
    repo = MagicMock()
    repo.assert_device_quota_available = AsyncMock(
        side_effect=PermissionError(QUOTA_EXHAUSTED_MESSAGE)
    )
    session, ws = _make_session(repo)
    session.agent = MagicMock()
    session.audio_chunks = [b"\x00\x01"]
    session._ensure_runtime = AsyncMock()
    session.stt = MagicMock()

    await session._process_turn()

    repo.assert_device_quota_available.assert_awaited_once_with("SX-000001")
    session._ensure_runtime.assert_not_awaited()
    assert len(ws.sent_messages) == 1
    err = ws.sent_messages[0]
    assert err["type"] == "error"
    assert err["error_kind"] == "quota_exhausted"
    assert QUOTA_EXHAUSTED_MESSAGE in err["message"]


@pytest.mark.anyio
async def test_process_turn_quota_ok_proceeds_to_runtime() -> None:
    repo = MagicMock()
    repo.assert_device_quota_available = AsyncMock()
    session, ws = _make_session(repo)
    session.agent = MagicMock()
    session.audio_chunks = [b"\x00\x01"]
    session._ensure_runtime = AsyncMock(side_effect=RuntimeError("stop-after-quota-check"))

    await session._process_turn()

    repo.assert_device_quota_available.assert_awaited_once_with("SX-000001")
    session._ensure_runtime.assert_awaited_once()
    assert ws.sent_messages[-1]["message"] == "stop-after-quota-check"


@pytest.mark.anyio
async def test_process_text_turn_quota_exhausted_before_chat() -> None:
    repo = MagicMock()
    repo.assert_device_quota_available = AsyncMock(
        side_effect=PermissionError(QUOTA_EXHAUSTED_MESSAGE)
    )
    session, ws = _make_session(repo)
    session.agent = MagicMock()
    session._ensure_runtime = AsyncMock()

    await session._process_text_turn("你好")

    repo.assert_device_quota_available.assert_awaited_once_with("SX-000001")
    session._ensure_runtime.assert_not_awaited()
    assert ws.sent_messages[-1]["error_kind"] == "quota_exhausted"


def test_assert_quota_for_turn_falls_back_to_user_assert() -> None:
    class RepoWithoutDeviceAssert:
        assert_user_quota_available = AsyncMock()

    repo = RepoWithoutDeviceAssert()
    session, _ = _make_session(repo)  # type: ignore[arg-type]
    session.device_id = "SX-000001"

    asyncio.run(session._assert_quota_for_turn())
    repo.assert_user_quota_available.assert_awaited_once_with("user-1")
