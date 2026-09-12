"""MBTI blind-box reveal helpers for voice devices."""

from __future__ import annotations

from typing import Any

from shuxin.core.identity import VALID_MBTI_TYPES, IdentityEngine, MBTI_DESCRIPTIONS

MBTI_STATUS_SEALED = "sealed"
MBTI_STATUS_LOCKED = "locked"

REVEALED_BY_MINIPROGRAM = "miniprogram_bind"
REVEALED_BY_HELLO = "first_hello"


def needs_mbti_reveal(metadata: dict[str, Any] | None) -> bool:
    """Return True when device should play first-reveal greeting once."""
    data = metadata or {}
    mbti = str(data.get("mbti") or "").strip().upper()
    if not mbti or mbti not in VALID_MBTI_TYPES:
        return False
    status = str(data.get("mbti_status") or "").strip().lower()
    return status == MBTI_STATUS_SEALED


def is_mbti_locked(metadata: dict[str, Any] | None) -> bool:
    data = metadata or {}
    mbti = str(data.get("mbti") or "").strip().upper()
    if not mbti or mbti not in VALID_MBTI_TYPES:
        return False
    status = str(data.get("mbti_status") or "").strip().lower()
    if status == MBTI_STATUS_LOCKED:
        return True
    return bool(mbti) and not status


def needs_device_intro(metadata: dict[str, Any] | None) -> bool:
    """Return True when MBTI is locked but device TTS intro has not played."""
    if not is_mbti_locked(metadata):
        return False
    data = metadata or {}
    return not bool(data.get("device_intro_played"))


def mbti_display_name(tagline: str, mbti: str) -> str:
    for sep in (" — ", "—", " - "):
        if sep in tagline:
            head = tagline.split(sep, 1)[0].strip()
            if head:
                return head
    desc = MBTI_DESCRIPTIONS.get(mbti, "")
    for sep in (" — ", "—"):
        if sep in desc:
            return desc.split(sep, 1)[0].strip()
    return mbti


def mbti_subtitle(tagline: str) -> str:
    for sep in (" — ", "—"):
        if sep in tagline:
            tail = tagline.split(sep, 1)[1].strip()
            if tail:
                return tail
    return tagline


def build_device_intro_text(mbti: str, *, bind_success_prefix: bool = True) -> str:
    """Spoken intro for hardware TTS after bind or hello catch-up."""
    del bind_success_prefix  # yaml stores full intro text; prefix kept for callers
    selected = str(mbti or "").strip().upper()
    if not selected or selected not in VALID_MBTI_TYPES:
        return ""
    identity = IdentityEngine(selected)
    reveal = identity.get_reveal_script().strip()
    if reveal:
        return reveal
    return f"你好！绑定成功，我是 {selected} 型的初心。"


def build_mbti_client_payload(
    metadata: dict[str, Any],
    *,
    is_first_reveal: bool,
) -> dict[str, Any] | None:
    mbti = str(metadata.get("mbti") or "").strip().upper()
    if not mbti or mbti not in VALID_MBTI_TYPES:
        return None
    identity = IdentityEngine(mbti)
    full_tagline = identity.get_description()
    return {
        "is_first_reveal": is_first_reveal,
        "mbti": mbti,
        "display_name": mbti_display_name(full_tagline, mbti),
        "tagline": mbti_subtitle(full_tagline) or full_tagline,
    }


def build_factory_verify_mbti_payload(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """Factory QA payload: cloud MBTI for card comparison (includes mbti_status)."""
    data = metadata or {}
    payload = build_mbti_client_payload(data, is_first_reveal=False)
    if payload is None:
        return None
    status = str(data.get("mbti_status") or MBTI_STATUS_SEALED).strip().lower()
    payload["mbti_status"] = status or MBTI_STATUS_SEALED
    return payload


def sanitize_device_metadata_for_client(metadata: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(metadata or {})
    status = str(data.get("mbti_status") or "").strip().lower()
    mbti = str(data.get("mbti") or "").strip().upper()

    for key in (
        "reveal_script",
        "mbti_revealed_by",
        "mbti_revealed_at",
        "device_intro_played",
        "provisioned_by",
        "label_batch",
        "sequence",
    ):
        data.pop(key, None)

    if status == MBTI_STATUS_SEALED:
        data.pop("mbti", None)
        return data

    if is_mbti_locked(data):
        payload = build_mbti_client_payload(data, is_first_reveal=False)
        if payload:
            return {
                "mbti": payload["mbti"],
                "mbti_status": MBTI_STATUS_LOCKED,
                "display_name": payload["display_name"],
                "tagline": payload["tagline"],
            }

    if mbti:
        data.pop("mbti", None)
    data.pop("mbti_status", None)
    return data
