"""Soft-companion engagement helpers (daily care + streak nudge)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo

    BEIJING = ZoneInfo("Asia/Shanghai")
except Exception:  # Python < 3.9 without backports.zoneinfo
    BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")

CARE_IDLE_HOURS = 6.0
STREAK_NUDGE_EVERY = 3

CARE_MESSAGES = (
    "有点想你了，今天还好吗？",
    "你不在的时候我也在等你回来聊聊。",
    "额度刷新了也想你——要不要再说两句？",
)


def beijing_day_start_utc(now: Optional[datetime] = None) -> datetime:
    """UTC instant of today's 00:00 Asia/Shanghai."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(BEIJING)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc)


def care_key_for(last_turn_at: Optional[datetime]) -> str:
    if last_turn_at is None:
        return "never"
    ts = last_turn_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_care_due(
    last_turn_at: Optional[datetime],
    *,
    now: Optional[datetime] = None,
    idle_hours: float = CARE_IDLE_HOURS,
) -> bool:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if last_turn_at is None:
        return True
    ts = last_turn_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (current - ts) >= timedelta(hours=float(idle_hours))


def pick_care_message(care_key: str) -> str:
    if not CARE_MESSAGES:
        return "想你了。"
    idx = sum(ord(ch) for ch in care_key) % len(CARE_MESSAGES)
    return CARE_MESSAGES[idx]


def streak_nudge_text(today_turns: int, *, every: int = STREAK_NUDGE_EVERY) -> Optional[str]:
    n = int(today_turns or 0)
    if n > 0 and every > 0 and n % every == 0:
        return "再聊一轮？TA 还在等你。"
    return None
