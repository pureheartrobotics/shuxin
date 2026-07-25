"""Soft relationship stage + milestone helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from shuxin.voice.engagement.relationship import (
    build_relationship_payload,
    evaluate_milestones,
    is_late_night_beijing,
    stage_for_bond,
    streak_nudge_for_stage,
)
from shuxin.voice.engagement.soft_loops import BEIJING


def test_stage_for_bond_thresholds():
    assert stage_for_bond(0)[0] == "first_meet"
    assert stage_for_bond(29.9)[1] == "初遇"
    assert stage_for_bond(30)[0] == "familiar"
    assert stage_for_bond(50)[1] == "伙伴"
    assert stage_for_bond(70)[0] == "bond"
    assert stage_for_bond(90)[1] == "唯一"


def test_relationship_payload_hides_score():
    payload = build_relationship_payload(bond_level=35, milestones={})
    assert payload["stage_label"] == "熟悉"
    assert "next_hint" in payload
    assert "bond_level" not in payload
    assert payload["latest_milestone"] is None


def test_milestone_idempotent_and_no_bond_side_effect():
    created = datetime(2026, 7, 1, tzinfo=timezone.utc)
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    first, newly = evaluate_milestones(
        milestones={},
        created_at=created,
        total_turns=30,
        bond_level=40,
        previous_stage_id="first_meet",
        turn_at=now,
    )
    assert "days_7" in newly
    assert "turns_30" in newly
    assert "first_stage_up" in newly
    second, newly2 = evaluate_milestones(
        milestones=first,
        created_at=created,
        total_turns=100,
        bond_level=40,
        previous_stage_id="familiar",
        turn_at=now,
    )
    assert newly2 == []
    assert second["days_7"]["unlocked"] is True


def test_late_night_window():
    late = datetime(2026, 7, 24, 16, 30, tzinfo=timezone.utc)  # 00:30 BJ
    day = datetime(2026, 7, 24, 4, 0, tzinfo=timezone.utc)  # 12:00 BJ
    assert is_late_night_beijing(late) is True
    assert is_late_night_beijing(day) is False


def test_streak_suppressed_when_exhausted():
    assert streak_nudge_for_stage(3, "familiar", quota_exhausted=True) is None
    assert streak_nudge_for_stage(3, "familiar", quota_exhausted=False)
    assert streak_nudge_for_stage(2, "familiar") is None


def test_care_ack_milestone():
    updated, newly = evaluate_milestones(milestones={}, unlock_care_ack=True)
    assert "first_care_ack" in newly
    again, newly2 = evaluate_milestones(milestones=updated, unlock_care_ack=True)
    assert newly2 == []
    assert again["first_care_ack"]["unlocked"] is True


def test_beijing_tz_available():
    assert BEIJING is not None
    _ = datetime.now(BEIJING) + timedelta(days=0)
