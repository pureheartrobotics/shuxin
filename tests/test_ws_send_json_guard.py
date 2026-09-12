"""WebSocket _send_json must tolerate closed sockets without raising."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from shuxin.voice.api import voice_session_registry as vsr
from shuxin.voice.api.ws_session import _VoiceWebSocketSession


def test_send_json_unregisters_on_closed_socket() -> None:
    async def run() -> None:
        vsr.reset_for_tests()
        session = object.__new__(_VoiceWebSocketSession)
        session.device_id = "dev-closed"
        session.websocket = SimpleNamespace(
            send_text=AsyncMock(side_effect=RuntimeError("Unexpected ASGI message 'websocket.send'"))
        )
        vsr.register("dev-closed", session)

        ok = await session._send_json({"type": "call/ring", "call_id": "x"})
        assert ok is False
        assert vsr.get_active_session("dev-closed") is None

    asyncio.run(run())
