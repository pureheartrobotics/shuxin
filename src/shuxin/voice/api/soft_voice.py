"""Soft-voice continuous mode helpers (unit-testable)."""

from __future__ import annotations

SOFT_VOICE_CLIENT_IDS = frozenset({"soft-miniprogram", "miniprogram"})


def is_soft_voice_client(client_id: str | None) -> bool:
    return str(client_id or "").strip() in SOFT_VOICE_CLIENT_IDS


def resolve_conversation_mode(client_id: str | None, requested: str | None) -> str:
    """Soft miniprogram always continuous so missing hello field cannot fall back to PTT."""
    if is_soft_voice_client(client_id):
        return "continuous"
    mode = str(requested or "push_to_talk").strip().lower()
    return "continuous" if mode == "continuous" else "push_to_talk"
