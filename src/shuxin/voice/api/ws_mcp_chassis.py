"""ESP32 MCP chassis: Xiaozhi-compatible handshake and voice-to-motor dispatch."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("shuxin.voice.mcp_chassis")

SendJson = Callable[[dict[str, Any]], Awaitable[Any]]

MCP_PROTOCOL_VERSION = "2024-11-05"
INIT_TIMEOUT_SECONDS = 2.0
DEFAULT_MOVE_SECONDS = 1.5
NUDGE_SECONDS = 0.8
MAX_MOVE_SECONDS = 4.0
DEFAULT_SPEED = 0.55
FAST_SPEED = 0.85
SLOW_SPEED = 0.35

CHASSIS_TOOL_ALIASES: dict[str, tuple[str, ...]] = {
    "go_forward": ("self.chassis.go_forward", "self.chassis.forward"),
    "go_back": ("self.chassis.go_back", "self.chassis.go_backward", "self.chassis.backward"),
    "turn_left": ("self.chassis.turn_left", "self.chassis.left"),
    "turn_right": ("self.chassis.turn_right", "self.chassis.right"),
    "stop": ("self.chassis.stop",),
}

_STOP_RE = re.compile(
    r"(停下|停车|停止|站住|别动|不要动|不要走|别往前|取消|^停$|^停[，,。！! ])"
)
_BACK_RE = re.compile(r"(后退|往后|向后|倒车|退后)")
_LEFT_RE = re.compile(r"(左转|向左转|往左转|向左|往左)")
_RIGHT_RE = re.compile(r"(右转|向右转|往右转|向右|往右)")
_FORWARD_RE = re.compile(r"(前进|往前走|向前走|向前|过来|走近|走过来|开过来)")
_NUDGE_RE = re.compile(r"(一点点|一点|一下|稍微)")
_FAST_RE = re.compile(r"(快|赶紧)")
_SLOW_RE = re.compile(r"(慢|缓缓)")
_SECONDS_RE = re.compile(r"([一二三四五六七八九十两\d]+)\s*秒")
_CN_NUM = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass(frozen=True)
class ChassisCommand:
    action: str
    duration_s: float
    speed: float
    source_text: str


def _parse_seconds(token: str) -> float:
    token = token.strip()
    if token.isdigit():
        return float(token)
    return float(_CN_NUM.get(token, 0) or 0)


def parse_chassis_command(text: str) -> Optional[ChassisCommand]:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return None
    if _STOP_RE.search(compact):
        return ChassisCommand("stop", 0.0, 0.0, text)
    if _BACK_RE.search(compact):
        action = "go_back"
    elif _LEFT_RE.search(compact):
        action = "turn_left"
    elif _RIGHT_RE.search(compact):
        action = "turn_right"
    elif _FORWARD_RE.search(compact):
        action = "go_forward"
    else:
        return None
    duration = NUDGE_SECONDS if _NUDGE_RE.search(compact) else DEFAULT_MOVE_SECONDS
    match = _SECONDS_RE.search(compact)
    if match:
        parsed = _parse_seconds(match.group(1))
        if parsed > 0:
            duration = min(parsed, MAX_MOVE_SECONDS)
    speed = DEFAULT_SPEED
    if _FAST_RE.search(compact):
        speed = FAST_SPEED
    elif _SLOW_RE.search(compact):
        speed = SLOW_SPEED
    return ChassisCommand(action, duration, speed, text)


def arguments_for_tool(tool: dict[str, Any] | None, command: ChassisCommand) -> dict[str, Any]:
    """Pass duration/speed only when the device advertised those properties."""
    if not tool or command.action == "stop":
        return {}
    schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    args: dict[str, Any] = {}
    for key, value in (
        ("duration", command.duration_s),
        ("seconds", command.duration_s),
        ("timeout", command.duration_s),
        ("speed", command.speed),
    ):
        if key in properties:
            args[key] = value
    return args


def resolve_tool_name(action: str, tool_names: set[str]) -> Optional[str]:
    for name in CHASSIS_TOOL_ALIASES.get(action, ()):
        if name in tool_names:
            return name
    return None


class DeviceMcpBridge:
    """Backend-side MCP client talking to an ESP32 Xiaozhi-style tool server."""

    init_timeout_seconds = INIT_TIMEOUT_SECONDS

    def __init__(self, send_json: SendJson, *, device_id: str = "") -> None:
        self._send_json = send_json
        self.device_id = device_id
        self.session_id = ""
        self.enabled = False
        self.tools: dict[str, dict[str, Any]] = {}
        self.ready = asyncio.Event()
        self._request_id = 0
        self._pending_by_id: dict[int, str] = {}
        self._pending_motion: Optional[str] = None
        self._stop_task: Optional[asyncio.Task[None]] = None
        self._init_timeout_task: Optional[asyncio.Task[None]] = None
        self._initialize_done = False
        self._turn_key: tuple[str, float] | None = None

    @property
    def tool_names(self) -> set[str]:
        return set(self.tools)

    def begin_turn(self) -> None:
        self._turn_key = None

    async def reset(self) -> None:
        self.enabled = False
        self.tools.clear()
        self.ready.clear()
        self._request_id = 0
        self._pending_by_id.clear()
        self._pending_motion = None
        self._initialize_done = False
        self._turn_key = None
        await self._cancel_task(self._stop_task)
        self._stop_task = None
        await self._cancel_task(self._init_timeout_task)
        self._init_timeout_task = None

    async def start(self) -> None:
        self.enabled = True
        await self._send_request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "shuxin-voice", "version": "esp32"},
            },
        )
        await self._cancel_task(self._init_timeout_task)
        self._init_timeout_task = asyncio.create_task(self._initialize_timeout())

    async def handle_device_message(self, data: dict[str, Any]) -> None:
        if not self.enabled:
            return
        payload = data.get("payload")
        if not isinstance(payload, dict):
            logger.warning("invalid MCP payload from device=%s", self.device_id)
            return
        error = payload.get("error")
        if isinstance(error, dict):
            logger.warning("device MCP error device=%s error=%s", self.device_id, error)
            return
        method = payload.get("method")
        if isinstance(method, str) and payload.get("id") is None:
            logger.info("device MCP notification device=%s method=%s", self.device_id, method)
            return
        result = payload.get("result")
        if not isinstance(result, dict):
            return
        request_id = payload.get("id")
        pending_method = self._pending_by_id.pop(request_id, None) if isinstance(request_id, int) else None
        if pending_method == "initialize" or (
            not self._initialize_done and "serverInfo" in result
        ):
            await self._on_initialized()
            return
        if pending_method == "tools/list" or isinstance(result.get("tools"), list):
            await self._on_tools_list(result)

    async def dispatch_user_text(self, text: str, *, schedule_stop: bool = True) -> bool:
        if not self.enabled:
            return False
        command = parse_chassis_command(text)
        if command is None:
            return False
        if not self.tools:
            self._pending_motion = text
            logger.info("chassis motion queued device=%s text=%s", self.device_id, text)
            return False
        return await self._execute_command(command, schedule_stop=schedule_stop)

    async def emergency_stop(self) -> None:
        if not self.enabled:
            return
        self._pending_motion = None
        await self._cancel_task(self._stop_task)
        self._stop_task = None
        if resolve_tool_name("stop", self.tool_names):
            await self._execute_command(
                ChassisCommand("stop", 0.0, 0.0, "abort"),
                schedule_stop=False,
            )

    async def _on_initialized(self) -> None:
        self._initialize_done = True
        await self._cancel_task(self._init_timeout_task)
        self._init_timeout_task = None
        logger.info("device MCP initialized device=%s", self.device_id)
        await self._send_request("tools/list", {"cursor": "", "withUserTools": False})

    async def _initialize_timeout(self) -> None:
        try:
            await asyncio.sleep(self.init_timeout_seconds)
        except asyncio.CancelledError:
            raise
        if self._initialize_done or not self.enabled:
            return
        logger.warning(
            "device MCP initialize timed out device=%s; listing tools anyway",
            self.device_id,
        )
        await self._send_request("tools/list", {"cursor": "", "withUserTools": False})

    async def _on_tools_list(self, result: dict[str, Any]) -> None:
        tools = result.get("tools")
        if not isinstance(tools, list):
            return
        for tool in tools:
            if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                self.tools[str(tool["name"])] = tool
        logger.info(
            "device MCP tools discovered device=%s tools=%s",
            self.device_id,
            sorted(self.tools),
        )
        next_cursor = result.get("nextCursor")
        if isinstance(next_cursor, str) and next_cursor:
            await self._send_request(
                "tools/list",
                {"cursor": next_cursor, "withUserTools": False},
            )
            return
        self.ready.set()
        pending = self._pending_motion
        self._pending_motion = None
        if pending:
            await self.dispatch_user_text(pending)

    async def _execute_command(self, command: ChassisCommand, *, schedule_stop: bool) -> bool:
        tool_name = resolve_tool_name(command.action, self.tool_names)
        if not tool_name:
            logger.warning(
                "chassis tool unavailable device=%s action=%s tools=%s",
                self.device_id,
                command.action,
                sorted(self.tool_names),
            )
            return False
        turn_key = (command.action, round(command.duration_s, 2))
        if command.action != "stop" and self._turn_key == turn_key:
            return False
        current = asyncio.current_task()
        if self._stop_task is not None and self._stop_task is not current:
            await self._cancel_task(self._stop_task)
            self._stop_task = None
        arguments = arguments_for_tool(self.tools.get(tool_name), command)
        await self._send_request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )
        self._turn_key = turn_key
        logger.info(
            "chassis MCP call device=%s tool=%s duration=%.2f text=%s",
            self.device_id,
            tool_name,
            command.duration_s,
            command.source_text,
        )
        if command.action != "stop" and schedule_stop:
            self._stop_task = asyncio.create_task(self._stop_after(command.duration_s))
        return True

    async def _stop_after(self, duration: float) -> None:
        try:
            await asyncio.sleep(duration)
            await self.dispatch_user_text("停止", schedule_stop=False)
        except asyncio.CancelledError:
            raise

    async def _send_request(self, method: str, params: dict[str, Any]) -> None:
        self._request_id += 1
        request_id = self._request_id
        self._pending_by_id[request_id] = method
        message: dict[str, Any] = {
            "type": "mcp",
            "payload": {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
        }
        if self.session_id:
            message["session_id"] = self.session_id
        await self._send_json(message)

    @staticmethod
    async def _cancel_task(task: Optional[asyncio.Task[None]]) -> None:
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return
