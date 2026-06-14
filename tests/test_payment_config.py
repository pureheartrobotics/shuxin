from __future__ import annotations

import json

import pytest

from shuxin.voice.payment_config import (
    compute_payment_credits,
    get_payment_plan,
    load_payment_plans,
    normalize_credit_ratio,
)


def test_compute_payment_credits() -> None:
    pay, display, dmx = compute_payment_credits(100, 0.95)
    assert pay == 1.0
    assert display == 1.0
    assert dmx == 0.95


def test_normalize_credit_ratio() -> None:
    assert normalize_credit_ratio(0.95) == 0.95


def test_default_payment_plans() -> None:
    plans = load_payment_plans()
    assert len(plans) >= 3
    plan_10 = get_payment_plan("plan_10")
    assert plan_10.amount_fen == 1000
    assert plan_10.add_yuan == 10.0


def test_payment_plans_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "id": "test-plan",
            "name": "测试套餐",
            "amount_fen": 100,
            "add_yuan": 1,
            "duration_days": 7,
        }
    ]
    monkeypatch.setenv("SHUXIN_PAYMENT_PLANS", json.dumps(payload))
    plan = get_payment_plan("test-plan")
    assert plan.name == "测试套餐"
    assert plan.amount_fen == 100
