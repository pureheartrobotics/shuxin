from __future__ import annotations

import asyncio
from typing import Any

from shuxin.voice.api.ws_mcp_chassis import (
    DeviceMcpBridge,
    arguments_for_tool,
    parse_chassis_command,
)


def test_parse_forward_nudge_and_chinese_seconds() -> None:
    assert parse_chassis_command("你好初心") is None
    forward = parse_chassis_command("小车前进")
    assert forward is not None and forward.action == "go_forward"
    assert forward.duration_s == 1.5
    nudge = parse_chassis_command("往前走一点")
    assert nudge is not None and nudge.duration_s == 0.8
    timed = parse_chassis_command("前进两秒")
    assert timed is not None and timed.duration_s == 2.0
    back = parse_chassis_command("往后再走一点吧")
    assert back is not None and back.action == "go_back"
    stop = parse_chassis_command("停下")
    assert stop is not None and stop.action == "stop"


def test_arguments_only_when_schema_lists_them() -> None:
    command = parse_chassis_command("前进")
    assert command is not None
    assert arguments_for_tool({"inputSchema": {"properties": {}}}, command) == {}
    args = arguments_for_tool(
        {"inputSchema": {"properties": {"duration": {"type": "number"}, "speed": {"type": "number"}}}},
        command,
    )
    assert args["duration"] == 1.5
    assert args["speed"] == 0.55


def _bridge() -> tuple[DeviceMcpBridge, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    async def send_json(message: dict[str, Any]) -> None:
        sent.append(message)

    return DeviceMcpBridge(send_json, device_id="esp32-car"), sent


def _mcp_calls(sent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m["payload"] for m in sent if m.get("type") == "mcp"]


def _tool_list_payload(names: list[str], *, request_id: int = 2) -> dict[str, Any]:
    return {
        "payload": {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": [{"name": name} for name in names]},
        }
    }


async def _run_handshake_and_forward() -> None:
    bridge, sent = _bridge()
    bridge.session_id = "sess-1"
    await bridge.start()
    methods = [p["method"] for p in _mcp_calls(sent)]
    assert methods == ["initialize"]
    await bridge.handle_device_message(
        {
            "payload": {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "esp32", "version": "1"},
                },
            }
        }
    )
    methods = [p["method"] for p in _mcp_calls(sent)]
    assert methods == ["initialize", "tools/list"]
    await bridge.handle_device_message(
        _tool_list_payload(
            [
                "self.chassis.go_forward",
                "self.chassis.go_back",
                "self.chassis.turn_left",
                "self.chassis.turn_right",
                "self.chassis.stop",
            ]
        )
    )
    ok = await bridge.dispatch_user_text("小车前进")
    assert ok is True
    call = _mcp_calls(sent)[-1]
    assert call["method"] == "tools/call"
    assert call["params"]["name"] == "self.chassis.go_forward"
    assert call["params"]["arguments"] == {}
    await bridge.reset()


async def _run_queue_until_tools_ready() -> None:
    bridge, sent = _bridge()
    await bridge.start()
    await bridge.handle_device_message(
        {
            "payload": {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"serverInfo": {"name": "esp32"}},
            }
        }
    )
    queued = await bridge.dispatch_user_text("往前走一点")
    assert queued is False
    assert not any(p.get("method") == "tools/call" for p in _mcp_calls(sent))
    await bridge.handle_device_message(_tool_list_payload(["self.chassis.go_forward", "self.chassis.stop"]))
    call = _mcp_calls(sent)[-1]
    assert call["method"] == "tools/call"
    assert call["params"]["name"] == "self.chassis.go_forward"
    await bridge.reset()


async def _run_initialize_timeout_lists_tools() -> None:
    bridge, sent = _bridge()
    bridge.init_timeout_seconds = 0.01
    await bridge.start()
    await asyncio.sleep(0.05)
    methods = [p["method"] for p in _mcp_calls(sent)]
    assert methods == ["initialize", "tools/list"]
    await bridge.reset()


async def _run_auto_stop_and_abort() -> None:
    bridge, sent = _bridge()
    original_sleep = asyncio.sleep

    async def instant_sleep(delay: float) -> None:
        if delay >= 0.5:
            return
        await original_sleep(0)

    asyncio.sleep = instant_sleep  # type: ignore[method-assign]
    try:
        bridge.enabled = True
        await bridge.handle_device_message(
            _tool_list_payload(["self.chassis.go_forward", "self.chassis.stop"], request_id=99)
        )
        await bridge.dispatch_user_text("前进")
        for _ in range(8):
            await original_sleep(0)
        names = [p["params"]["name"] for p in _mcp_calls(sent) if p.get("method") == "tools/call"]
        assert names[0] == "self.chassis.go_forward"
        assert names[-1] == "self.chassis.stop"
        await bridge.emergency_stop()
        assert _mcp_calls(sent)[-1]["params"]["name"] == "self.chassis.stop"
    finally:
        asyncio.sleep = original_sleep  # type: ignore[method-assign]
        await bridge.reset()


def test_mcp_handshake_then_forward() -> None:
    asyncio.run(_run_handshake_and_forward())


def test_mcp_queues_motion_until_tools_ready() -> None:
    asyncio.run(_run_queue_until_tools_ready())


def test_mcp_initialize_timeout_falls_back_to_tools_list() -> None:
    asyncio.run(_run_initialize_timeout_lists_tools())


def test_mcp_auto_stop_then_abort() -> None:
    asyncio.run(_run_auto_stop_and_abort())
