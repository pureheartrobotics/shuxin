"""设备 → 服务端 call/* 信令委派。"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional, TYPE_CHECKING

from shuxin.voice.api.call_service import CallService

if TYPE_CHECKING:
    from shuxin.voice.api.ws_session import _VoiceWebSocketSession

logger = logging.getLogger(__name__)

_CALL_INTENT_RE = re.compile(
    r"(打电话|呼叫|拨号|给).{0,12}?(给)?\s*([^\s，。！？]+)"
)


async def handle_device_call_message(session: _VoiceWebSocketSession, data: dict) -> bool:
    """处理设备上行 call/* 消息。返回 True 表示已消费。"""
    message_type = str(data.get("type") or "")
    if not message_type.startswith("call/"):
        return False

    service = CallService(session.repo)
    if not service.is_enabled():
        await session._send_json(
            {"type": "error", "message": "device call feature is disabled"}
        )
        return True

    call_id = str(data.get("call_id") or "")
    action = message_type.split("/", 1)[1]

    if action == "accept":
        result = await service.accept(session, call_id)
    elif action == "reject":
        result = await service.reject(session, call_id)
    elif action == "end":
        result = await service.end(session, call_id)
    elif action == "cancel":
        result = await service.end(session, call_id)
    else:
        await session._send_json(
            {"type": "error", "message": f"unsupported call action: {action}"}
        )
        return True

    if not result.get("ok"):
        await session._send_json(
            {"type": "error", "message": str(result.get("message") or "call failed")}
        )
    return True


async def try_dispatch_call_intent(
    session: _VoiceWebSocketSession,
    user_text: str,
) -> tuple[bool, str]:
    """从用户话术触发拨号（切面：在 LLM 前快速路径）。"""
    service = CallService(session.repo)
    if not service.is_enabled():
        return False, ""

    text = str(user_text or "").strip()
    if "电话" not in text and "呼叫" not in text and "拨号" not in text:
        return False, ""

    match = _CALL_INTENT_RE.search(text)
    target = ""
    if match:
        target = str(match.group(3) or "").strip("给 ")
    if not target:
        return False, ""

    result = await service.initiate_by_handle(
        caller_session=session,
        target_handle="",
        contact_name=target,
    )
    return True, str(result.get("message") or "已处理呼叫请求")
