from __future__ import annotations

import asyncio
from typing import Any

import pytest

from shuxin.voice.payment_config import DEFAULT_CREDIT_RATIO, compute_payment_credits, normalize_credit_ratio
from shuxin.voice.postgres_repository import VoicePostgresRepository


class FakePool:
    def __init__(self, *, fetch_rows: list | None = None, fetchrow: Any = None, fetchval: Any = None) -> None:
        self.fetch_rows = fetch_rows or []
        self.fetchrow_value = fetchrow
        self.fetchval_value = fetchval
        self.executed: list[tuple] = []

    async def fetch(self, *_args, **_kwargs):
        return self.fetch_rows

    async def fetchrow(self, *_args, **_kwargs):
        return self.fetchrow_value

    async def fetchval(self, *_args, **_kwargs):
        return self.fetchval_value

    async def execute(self, query, *args):
        self.executed.append((query, args))


def test_compute_payment_credits_100_at_095() -> None:
    pay_yuan, display, dmx = compute_payment_credits(10000, 0.95)
    assert pay_yuan == 100.0
    assert display == 100.0
    assert dmx == 95.0


def test_normalize_credit_ratio_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        normalize_credit_ratio(0)
    with pytest.raises(ValueError):
        normalize_credit_ratio(1.5)


def test_get_credit_ratio_default_when_missing() -> None:
    repo = VoicePostgresRepository(pool=FakePool(fetchrow=None))

    async def run() -> float:
        return await repo.get_credit_ratio()

    assert asyncio.run(run()) == DEFAULT_CREDIT_RATIO


def test_get_credit_ratio_from_settings() -> None:
    repo = VoicePostgresRepository(
        pool=FakePool(fetchrow={"value": {"ratio": 0.9}}),
    )

    async def run() -> float:
        return await repo.get_credit_ratio()

    assert asyncio.run(run()) == 0.9


def test_set_credit_ratio_persists() -> None:
    pool = FakePool()
    repo = VoicePostgresRepository(pool=pool)

    async def run() -> dict:
        return await repo.set_credit_ratio(0.88)

    result = asyncio.run(run())
    assert result["credit_ratio"] == 0.88
    assert pool.executed


def test_list_payment_plans_from_db() -> None:
    rows = [
        {
            "plan_id": "plan_100",
            "name": "100 元",
            "description": "",
            "amount_fen": 10000,
            "sort_order": 10,
            "enabled": True,
        }
    ]
    repo = VoicePostgresRepository(pool=FakePool(fetch_rows=rows))

    async def run():
        return await repo.list_payment_plans(include_disabled=False)

    plans = asyncio.run(run())
    assert len(plans) == 1
    assert plans[0].id == "plan_100"
    assert plans[0].amount_fen == 10000


def test_soft_delete_payment_plan() -> None:
    row = {
        "plan_id": "plan_100",
        "name": "100 元",
        "description": "",
        "amount_fen": 10000,
        "sort_order": 10,
        "enabled": False,
    }
    repo = VoicePostgresRepository(pool=FakePool(fetchrow=row))

    async def run():
        return await repo.soft_delete_payment_plan("plan_100")

    result = asyncio.run(run())
    assert result["enabled"] is False
    assert result["plan_id"] == "plan_100"
