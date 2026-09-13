from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from shuxin.voice.api.ws_session import _VoiceWebSocketSession

class MockWebSocket:
    def __init__(self):
        self.sent_messages = []

    async def send_text(self, text: str) -> None:
        self.sent_messages.append(json.loads(text))

@pytest.mark.anyio
async def test_auth_gate_rejects_unauthenticated_listen() -> None:
    # 1. Setup session without user_settings (None)
    ws = MockWebSocket()
    session = _VoiceWebSocketSession(
        websocket=ws,
        service=MagicMock(),
        repo=MagicMock(),
        shuxin_home=Path("/tmp"),
        default_device_id="demo-device-001",
        out_dir=Path("/tmp"),
    )
    session.user_settings = None

    # 2. Send "listen start" text message
    listen_msg = json.dumps({"type": "listen", "state": "start"})
    await session._handle_text(listen_msg)

    # 3. Assert error was sent back
    assert len(ws.sent_messages) == 1
    err = ws.sent_messages[0]
    assert err["type"] == "error"
    assert "not authenticated" in err["message"]
    assert not session.listening  # should not start listening

@pytest.mark.anyio
async def test_auth_gate_rejects_unauthenticated_text_turn() -> None:
    # 1. Setup session without user_settings (None)
    ws = MockWebSocket()
    session = _VoiceWebSocketSession(
        websocket=ws,
        service=MagicMock(),
        repo=MagicMock(),
        shuxin_home=Path("/tmp"),
        default_device_id="demo-device-001",
        out_dir=Path("/tmp"),
    )
    session.user_settings = None

    # 2. Send "text_turn" message
    text_turn_msg = json.dumps({"type": "text_turn", "text": "hello"})
    await session._handle_text(text_turn_msg)

    # 3. Assert error was sent back
    assert len(ws.sent_messages) == 1
    err = ws.sent_messages[0]
    assert err["type"] == "error"
    assert "not authenticated" in err["message"]

@pytest.mark.anyio
async def test_auth_gate_allows_authenticated_listen() -> None:
    # 1. Setup session WITH user_settings
    ws = MockWebSocket()
    mock_repo = MagicMock()
    mock_repo.get_device = AsyncMock()
    
    session = _VoiceWebSocketSession(
        websocket=ws,
        service=MagicMock(),
        repo=mock_repo,
        shuxin_home=Path("/tmp"),
        default_device_id="demo-device-001",
        out_dir=Path("/tmp"),
    )
    session.user_settings = MagicMock() # Authenticated
    session.user_id = "user-123"
    session.device_id = "device-123"
    
    # Mock ASR start
    session._start_realtime_asr_if_needed = AsyncMock()

    # 2. Send "listen start" text message
    listen_msg = json.dumps({"type": "listen", "state": "start"})
    await session._handle_text(listen_msg)

    # 3. Assert it does NOT raise unauthenticated error
    # It sends back {"type": "listen", "state": "start"}
    assert any(m.get("type") == "listen" and m.get("state") == "start" for m in ws.sent_messages)
    assert session.listening
    session._start_realtime_asr_if_needed.assert_called_once()


@pytest.mark.anyio
async def test_mcp_chassis_motion_is_discovered_and_dispatched() -> None:
    ws = MockWebSocket()
    session = _VoiceWebSocketSession(
        websocket=ws,
        service=MagicMock(),
        repo=MagicMock(),
        shuxin_home=Path("/tmp"),
        default_device_id="demo-device-001",
        out_dir=Path("/tmp"),
    )
    session._mcp_enabled = True

    await session._handle_mcp_msg(
        {
            "payload": {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"tools": [{"name": "self.chassis.go_forward"}]},
            }
        }
    )
    await session._dispatch_chassis_motion("小车前进")

    calls = [message for message in ws.sent_messages if message.get("type") == "mcp"]
    assert calls[-1]["payload"]["method"] == "tools/call"
    assert calls[-1]["payload"]["params"]["name"] == "self.chassis.go_forward"
