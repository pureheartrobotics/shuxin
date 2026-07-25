"""User-facing companion points (display only; ledger remains minutes)."""

from __future__ import annotations

POINTS_PER_MINUTE = 10

QUOTA_EXHAUSTED_USER_MESSAGE = "陪伴点已用尽，请充值"


def minutes_to_points(minutes: float) -> int:
    m = float(minutes or 0.0)
    if m <= 0:
        return 0
    points = int(round(m * POINTS_PER_MINUTE))
    return points if points > 0 else 1


def format_plan_description_minutes(duration_minutes: int, *, monthly: bool = False) -> str:
    pts = minutes_to_points(float(duration_minutes))
    if monthly:
        return f"含 {pts} 陪伴点/月"
    return f"含 {pts} 陪伴点"
