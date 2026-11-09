"""User-facing datetime formatting in Asia/Shanghai (UTC+8, no DST)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

BEIJING_TZ = timezone(timedelta(hours=8))


def _coerce_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def format_beijing_display(value: Any) -> str:
    """Human-readable Beijing time: 2026-06-30 11:01:16."""
    if value is None:
        return ""
    if not hasattr(value, "isoformat"):
        return str(value or "")
    dt = _coerce_aware_utc(value).astimezone(BEIJING_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_beijing_iso(value: Any) -> str:
    """Machine-parseable Beijing ISO: 2026-06-30T11:01:16+08:00."""
    if value is None:
        return ""
    if not hasattr(value, "isoformat"):
        return str(value or "")
    dt = _coerce_aware_utc(value).astimezone(BEIJING_TZ)
    return dt.isoformat(timespec="seconds")
