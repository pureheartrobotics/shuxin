"""通话信令内存存储（Postgres 方法未接入前的开发 fallback）。"""

from __future__ import annotations

import time
from typing import Any, Optional

_CALLS: dict[str, dict[str, Any]] = {}
_USER_HANDLES: dict[str, str] = {}
_HANDLE_USERS: dict[str, str] = {}
_CONTACTS: dict[tuple[str, str], str] = {}
_BINDINGS: dict[str, list[str]] = {}


_BLOCKED: set[tuple[str, str]] = set()
_DND_USERS: set[str] = set()


def _uid(user_id: Any) -> str:
    return str(user_id or "").strip()


def reset_for_tests() -> None:
    _CALLS.clear()
    _USER_HANDLES.clear()
    _HANDLE_USERS.clear()
    _CONTACTS.clear()
    _BINDINGS.clear()
    _BLOCKED.clear()
    _DND_USERS.clear()


def seed_block(callee_user_id: str, caller_handle: str) -> None:
    _BLOCKED.add((_uid(callee_user_id), str(caller_handle).strip().lower()))


def seed_dnd(user_id: str) -> None:
    _DND_USERS.add(_uid(user_id))


def seed_user_handle(user_id: str, handle: str) -> None:
    selected = str(handle).strip().lower()
    key = _uid(user_id)
    _USER_HANDLES[key] = selected
    _HANDLE_USERS[selected] = key


def seed_contact(owner_user_id: str, nickname: str, target_handle: str) -> None:
    _CONTACTS[(_uid(owner_user_id), str(nickname))] = str(target_handle).strip().lower()


def seed_user_devices(user_id: str, device_ids: list[str]) -> None:
    _BINDINGS[_uid(user_id)] = list(device_ids)


def get_user_by_shuxin_handle(handle: str) -> Optional[dict]:
    user_id = _HANDLE_USERS.get(str(handle).strip().lower())
    if user_id is None:
        return None
    return {"user_id": user_id, "shuxin_handle": handle}


def get_contact_handle(owner_user_id: str, nickname: str) -> str:
    return _CONTACTS.get((_uid(owner_user_id), str(nickname)), "")


def get_shuxin_handle(user_id: str) -> str:
    return _USER_HANDLES.get(_uid(user_id), "")


def list_active_device_ids_for_user(user_id: str) -> list[str]:
    return list(_BINDINGS.get(_uid(user_id), []))


def create_voice_call(**fields: Any) -> None:
    call_id = str(fields["call_id"])
    row = dict(fields)
    row.setdefault("state", "ringing")
    _CALLS[call_id] = row


def claim_voice_call_answer(call_id: str, device_id: str) -> Optional[dict]:
    row = _CALLS.get(call_id)
    if not row or row.get("state") != "ringing":
        return None
    if row.get("answered_device_id"):
        return None
    row["answered_device_id"] = device_id
    row["state"] = "connected"
    row["connected_at"] = time.time()
    return dict(row)


def get_voice_call(call_id: str) -> Optional[dict]:
    row = _CALLS.get(call_id)
    return dict(row) if row else None


def end_voice_call(call_id: str, reason: str = "ended") -> None:
    row = _CALLS.get(call_id)
    if not row:
        return
    row["state"] = reason
    row["ended_at"] = time.time()


async def is_caller_blocked(callee_user_id: str, caller_handle: str) -> bool:
    return (_uid(callee_user_id), str(caller_handle).strip().lower()) in _BLOCKED


async def is_user_in_dnd(user_id: str) -> bool:
    return _uid(user_id) in _DND_USERS
