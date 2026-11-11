"""把底盘 / 摄像头 / 头部 MCP 注册成 Hermes toolset ``robot``。"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger("shuxin.hermes.robot")

_REGISTERED = False

DRIVE_ACTIONS = {
    "forward": "go_forward",
    "back": "go_back",
    "left": "turn_left",
    "right": "turn_right",
    "stop": "stop",
    "go_forward": "go_forward",
    "go_back": "go_back",
    "turn_left": "turn_left",
    "turn_right": "turn_right",
}


@dataclass
class RobotSessionBridge:
    """Voice WebSocket 会话暴露给 Hermes 工具的同步门面。"""

    call_mcp: Callable[[str, dict[str, Any]], str]
    wait_vision: Callable[[float], Optional[bytes]]
    caption: Callable[[bytes, str], str]
    has_tool: Callable[[str], bool]


_SESSION: ContextVar[Optional[RobotSessionBridge]] = ContextVar(
    "shuxin_robot_session", default=None
)


def bind_robot_session(bridge: Optional[RobotSessionBridge]) -> Any:
    return _SESSION.set(bridge)


def reset_robot_session(token: Any) -> None:
    _SESSION.reset(token)


def current_robot_session() -> Optional[RobotSessionBridge]:
    return _SESSION.get()


def _session_or_error() -> RobotSessionBridge | str:
    session = current_robot_session()
    if session is None:
        return "现在没有连上这台机器人，身体工具不可用。"
    return session


def _drive(args: dict[str, Any], **_kw: Any) -> str:
    session = _session_or_error()
    if isinstance(session, str):
        return session
    raw = str(args.get("action") or "forward").strip().lower()
    action = DRIVE_ACTIONS.get(raw)
    if not action:
        return "action 只能是 forward/back/left/right/stop"
    duration = float(args.get("duration") or (0.0 if action == "stop" else 1.5))
    duration = max(0.0, min(duration, 4.0))
    speed = float(args.get("speed") or 0.55)
    speed = max(0.1, min(speed, 1.0))
    return session.call_mcp(
        "chassis",
        {"action": action, "duration": duration, "speed": speed},
    )


def _look(args: dict[str, Any], **_kw: Any) -> str:
    return _see("self.camera.look", args, timeout=3.5)


def _look_around(args: dict[str, Any], **_kw: Any) -> str:
    return _see("self.camera.look_around", args, timeout=8.0)


def _see(mcp_name: str, args: dict[str, Any], *, timeout: float) -> str:
    session = _session_or_error()
    if isinstance(session, str):
        return session
    if not session.has_tool(mcp_name):
        return "这台车还没接上摄像头工具。"
    session.call_mcp(mcp_name, {})
    jpeg = session.wait_vision(timeout)
    if not jpeg:
        return "转头/看了一眼，但照片还没传上来。"
    question = str(args.get("question") or "看看前面").strip()
    return session.caption(jpeg, question)


def _photo(_args: dict[str, Any], **_kw: Any) -> str:
    session = _session_or_error()
    if isinstance(session, str):
        return session
    if not session.has_tool("self.camera.photo"):
        return "这台车还不能拍照。"
    return session.call_mcp("self.camera.photo", {})


def _album(_args: dict[str, Any], **_kw: Any) -> str:
    session = _session_or_error()
    if isinstance(session, str):
        return session
    if not session.has_tool("self.camera.album"):
        return "这台车还没有相册。"
    return session.call_mcp("self.camera.album", {})


def _head(args: dict[str, Any], **_kw: Any) -> str:
    session = _session_or_error()
    if isinstance(session, str):
        return session
    action = str(args.get("action") or "nod").strip().lower()
    if action == "nod":
        name = "self.head.nod"
        payload: dict[str, Any] = {}
    elif action == "shake":
        name = "self.head.shake"
        payload = {}
    elif action in {"center", "turn"}:
        name = "self.head.turn"
        pan = 90 if action == "center" else int(args.get("pan") or 90)
        tilt = 90 if action == "center" else int(args.get("tilt") or 90)
        payload = {"pan": max(0, min(pan, 180)), "tilt": max(0, min(tilt, 180))}
    else:
        return "action 只能是 nod/shake/center/turn"
    if not session.has_tool(name):
        return "这台车还没接头部工具。"
    return session.call_mcp(name, payload)


def register_robot_tools() -> None:
    """向 Hermes 全局 registry 注册 robot toolset（幂等）。"""
    global _REGISTERED
    if _REGISTERED:
        return
    try:
        from tools.registry import registry
    except Exception as exc:
        logger.warning("skip robot tools, Hermes registry unavailable: %s", exc)
        return

    def _reg(name: str, description: str, schema: dict[str, Any], handler: Any) -> None:
        registry.register(
            name=name,
            toolset="robot",
            schema={
                "name": name,
                "description": description,
                "parameters": schema,
            },
            handler=handler,
            description=description,
            emoji="🤖",
            override=True,
        )

    _reg(
        "robot_drive",
        "驱动机器人底盘。前进/后退/左转/右转/停车。",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["forward", "back", "left", "right", "stop"],
                    "description": "运动方向，停车用 stop",
                },
                "duration": {"type": "number", "description": "秒，默认 1.5，最大 4"},
                "speed": {"type": "number", "description": "0.35 慢 / 0.55 默认 / 0.85 快"},
            },
            "required": ["action"],
        },
        _drive,
    )
    _reg(
        "robot_look",
        "看眼前摄像头这一眼，返回画面说明。",
        {
            "type": "object",
            "properties": {"question": {"type": "string"}},
        },
        _look,
    )
    _reg(
        "robot_look_around",
        "转头环顾四周再看环境，返回画面说明。比 robot_look 慢。",
        {
            "type": "object",
            "properties": {"question": {"type": "string"}},
        },
        _look_around,
    )
    _reg(
        "robot_photo",
        "拍一张照片存进相册。",
        {"type": "object", "properties": {}},
        _photo,
    )
    _reg(
        "robot_album",
        "在屏幕上打开相册。",
        {"type": "object", "properties": {}},
        _album,
    )
    _reg(
        "robot_head",
        "头部点头、摇头，或转到指定角度。",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["nod", "shake", "center", "turn"],
                },
                "pan": {"type": "integer", "description": "左右 0-180，90 为正前"},
                "tilt": {"type": "integer", "description": "上下 0-180，90 为水平"},
            },
            "required": ["action"],
        },
        _head,
    )
    _REGISTERED = True
    logger.info("Hermes robot toolset registered")
