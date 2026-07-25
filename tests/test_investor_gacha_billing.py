"""Unit tests for investor gacha + text billing (pure logic)."""

from __future__ import annotations

import random

from shuxin.voice.billing.gacha import build_weight_table, merge_gacha_settings, weighted_pick_mbti
from shuxin.voice.billing.text_billing import (
    estimate_minutes_by_typing_speed,
    estimate_minutes_for_text,
    merge_text_billing_settings,
    minutes_from_llm_usage,
    text_max_chars,
    yuan_from_llm_usage,
)
from shuxin.voice.persistence.companion_repo import CompanionRepository


def test_text_billing_only_llm_tokens():
    yuan = yuan_from_llm_usage(
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        cache_tokens=1_000_000,
        settings={
            "llm_input_yuan_per_m_tokens": 0.85,
            "llm_output_yuan_per_m_tokens": 1.7,
            "llm_cache_yuan_per_m_tokens": 0.02,
            "yuan_to_minutes_rate": 1.0,
        },
    )
    assert abs(yuan - (0.85 + 1.7 + 0.02)) < 1e-9
    minutes = minutes_from_llm_usage(
        prompt_tokens=1_000_000,
        completion_tokens=0,
        cache_tokens=0,
        settings={"llm_input_yuan_per_m_tokens": 0.85, "yuan_to_minutes_rate": 2.0},
    )
    assert abs(minutes - 1.7) < 1e-9


def test_text_max_chars_default_500():
    assert text_max_chars({}) == 500
    assert text_max_chars({"text_max_chars": 200}) == 200


def test_estimate_minutes_scales_with_long_text():
    short = estimate_minutes_for_text("你好", max_completion_tokens=10)
    long = estimate_minutes_for_text("啊" * 500, max_completion_tokens=10)
    assert long > short


def test_gacha_weights_rare_lower_probability():
    settings = merge_gacha_settings(
        {"weights": {"INTJ": 1, "ENFP": 1000}}
    )
    rng = random.Random(42)
    picks = [weighted_pick_mbti(settings, rng=rng) for _ in range(200)]
    assert picks.count("ENFP") > picks.count("INTJ")


def test_gacha_build_weight_table_fills_unlisted():
    table = build_weight_table({"weights": {"INTJ": 5}})
    assert "INTJ" in table
    assert len(table) >= 2


def test_typing_speed_estimate_default_40():
    # 40 chars => 1 minute at default chars_per_minute=40
    assert abs(estimate_minutes_by_typing_speed("啊" * 40) - 1.0) < 1e-9
    assert abs(estimate_minutes_by_typing_speed("啊" * 80, settings={"chars_per_minute": 40}) - 2.0) < 1e-9
    assert abs(estimate_minutes_by_typing_speed("啊" * 80, settings={"chars_per_minute": 80}) - 1.0) < 1e-9


def test_merge_text_billing_keeps_chars_per_minute():
    merged = merge_text_billing_settings({"chars_per_minute": 55})
    assert merged["chars_per_minute"] == 55.0
    assert merged["text_max_chars"] == 500.0


def test_default_display_name_accepts_mbti_kwarg():
    """Regression: IdentityEngine takes ``mbti=``, not ``mbti_type=`` (draw 500)."""
    repo = CompanionRepository.__new__(CompanionRepository)
    name = CompanionRepository._default_display_name(repo, "ENFP")
    assert isinstance(name, str)
    assert name
    assert "ENFP" in name or len(name) >= 2
