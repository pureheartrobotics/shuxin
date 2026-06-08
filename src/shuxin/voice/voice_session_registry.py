"""Track active voice WebSocket sessions for bind-time intro push."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_active_sessions: dict[str, Any] = {}
_intro_locks: dict[str, asyncio.Lock] = {}


def register(device_id: str, session: Any) -> None:
    selected = str(device_id or "").strip()
    if not selected:
        return
    _active_sessions[selected] = session


def unregister(device_id: str, session: Any) -> None:
    selected = str(device_id or "").strip()
    if not selected:
        return
    if _active_sessions.get(selected) is session:
        _active_sessions.pop(selected, None)


def get_active_session(device_id: str) -> Any | None:
    selected = str(device_id or "").strip()
    if not selected:
        return None
    return _active_sessions.get(selected)


def intro_lock(device_id: str) -> asyncio.Lock:
    selected = str(device_id or "").strip()
    if selected not in _intro_locks:
        _intro_locks[selected] = asyncio.Lock()
    return _intro_locks[selected]


def reset_for_tests() -> None:
    _active_sessions.clear()
    _intro_locks.clear()


async def maybe_push_intro_after_bind(result: dict[str, Any]) -> None:
    """If device WS is online right after first bind, play pending intro immediately."""
    mbti = result.get("mbti") or {}
    if not mbti.get("is_first_reveal"):
        return
    device_id = str(result.get("device_code") or result.get("device_id") or "")
    session = get_active_session(device_id)
    if session is None:
        return
    try:
        await session.play_pending_device_intro(bind_success_prefix=True)
    except Exception as exc:
        logger.warning("bind intro push failed for %s: %s", device_id, exc)
