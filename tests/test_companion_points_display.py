from shuxin.voice.billing.companion_points import (
    QUOTA_EXHAUSTED_USER_MESSAGE,
    format_plan_description_minutes,
    minutes_to_points,
)


def test_minutes_to_points_rounding_and_floor():
    assert minutes_to_points(0) == 0
    assert minutes_to_points(12) == 120
    assert minutes_to_points(0.04) == 1  # avoid zero while positive minutes
    assert minutes_to_points(1.24) == 12


def test_plan_description_uses_companion_points():
    assert format_plan_description_minutes(120, monthly=True) == "含 1200 陪伴点/月"
    assert format_plan_description_minutes(30, monthly=False) == "含 300 陪伴点"


def test_quota_exhausted_user_message():
    assert "陪伴点" in QUOTA_EXHAUSTED_USER_MESSAGE
    assert "分钟" not in QUOTA_EXHAUSTED_USER_MESSAGE
