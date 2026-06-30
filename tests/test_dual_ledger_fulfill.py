from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from shuxin.voice.payment_config import DISPLAY_BALANCE_METADATA_KEY
from shuxin.voice.postgres_repository import VoicePostgresRepository


class RepoFakePool:
    def __init__(self, *, fetchrow: Any = None) -> None:
        self.fetchrow_value = fetchrow
        self.executed: list[tuple] = []

    async def fetchrow(self, *_args, **_kwargs):
        return self.fetchrow_value

    async def execute(self, query, *args):
        self.executed.append((query, args))


class FakeConn:
    def __init__(self, order_row: dict, user_row: dict) -> None:
        self.order_row = order_row
        self.user_row = user_row
        self.executed: list[tuple] = []

    async def fetchrow(self, query: str, *args):
        if "FROM payment_orders" in query:
            return self.order_row
        if "FROM users" in query:
            return self.user_row
        return None

    async def execute(self, query: str, *args):
        self.executed.append((query, args))

    @asynccontextmanager
    async def transaction(self):
        yield


class FakeAcquire:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_args):
        return False


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn
        self.executed: list[tuple] = []

    def acquire(self):
        return FakeAcquire(self.conn)

    async def execute(self, query, *args):
        self.executed.append((query, args))


def _paid_order_row(*, amount_fen: int = 10000) -> dict[str, Any]:
    return {
        "order_id": "order-1",
        "user_id": "wx_user",
        "plan_id": "plan_100",
        "plan_name": "100 元",
        "amount_fen": amount_fen,
        "add_yuan": 100.0,
        "duration_days": 0,
        "status": "pending",
        "wx_transaction_id": None,
        "pay_yuan": 100.0,
        "display_credited": 100.0,
        "dmx_credited": 95.0,
        "credit_ratio": 0.95,
        "device_id": None,
    }


def test_fulfill_payment_order_credits_display_and_dmx() -> None:
    user_row = {
        "llm_config": {"api_key": "sk-test"},
        "quota_note": "",
        "metadata": {DISPLAY_BALANCE_METADATA_KEY: 10.0},
    }
    conn = FakeConn(_paid_order_row(), user_row)
    repo = VoicePostgresRepository(pool=FakePool(conn))
    notify = {"amount": {"total": 10000}}

    async def run():
        with patch(
            "shuxin.voice.postgres_repository.top_up_token_by_api_key",
            new=AsyncMock(return_value={"ok": True}),
        ) as top_up:
            result = await repo.fulfill_payment_order(
                out_trade_no="sx123",
                wx_transaction_id="wx-tx-1",
                notify_payload=notify,
            )
        return result, top_up

    result, top_up = asyncio.run(run())
    assert result["status"] == "paid"
    top_up.assert_awaited_once()
    assert top_up.await_args.kwargs["add_yuan"] == 95.0
    metadata_updates = [
        args for query, args in conn.executed if "metadata = $2" in query
    ]
    assert metadata_updates
    import json

    metadata = json.loads(metadata_updates[0][1])
    assert metadata[DISPLAY_BALANCE_METADATA_KEY] == 110.0


def test_new_user_display_balance_matches_dmx_gift() -> None:
    pool = RepoFakePool(
        fetchrow={"llm_config": {}, "metadata": {}},
    )
    repo = VoicePostgresRepository(pool=pool)

    async def run():
        with patch("shuxin.voice.postgres_repository.dmx_admin_configured", return_value=True), patch(
            "shuxin.voice.postgres_repository.create_user_token",
            new=AsyncMock(return_value="sk-new"),
        ), patch(
            "shuxin.voice.postgres_repository.merge_platform_llm_defaults",
            side_effect=lambda cfg: cfg,
        ):
            await repo.ensure_user_dmx_llm("wx_new")

    asyncio.run(run())
    assert pool.executed
    import json

    _, llm_json, metadata_json = pool.executed[0][1]
    metadata = json.loads(metadata_json)
    assert metadata[DISPLAY_BALANCE_METADATA_KEY] == 10.0


class QuotaFakePool:
    def __init__(self, *, fetchrow: Any = None) -> None:
        self.fetchrow_value = fetchrow
        self.executed: list[tuple] = []

    async def fetchrow(self, *_args, **_kwargs):
        return self.fetchrow_value

    async def execute(self, query, *args):
        self.executed.append((query, args))

    def acquire(self):
        return _QuotaFakeAcquire(self)


class _QuotaFakeAcquire:
    def __init__(self, pool: QuotaFakePool) -> None:
        self.pool = pool

    async def __aenter__(self):
        return self.pool

    async def __aexit__(self, *_args):
        return False


def test_lazy_backfill_display_from_dmx() -> None:
    pool = QuotaFakePool(
        fetchrow={
            "llm_config": {"api_key": "sk-test"},
            "metadata": {},
        },
    )
    repo = VoicePostgresRepository(pool=pool)

    async def run():
        with patch(
            "shuxin.voice.postgres_repository.get_token_balance",
            new=AsyncMock(return_value={"remain_yuan": 50.0, "used_yuan": 0, "exhausted": False}),
        ), patch.object(repo, "get_credit_ratio", new=AsyncMock(return_value=0.95)):
            return await repo.get_user_quota_by_user_id("wx_old", admin_detail=True)

    result = asyncio.run(run())
    assert result["display_balance_yuan"] == 50.0
    assert result["remain_yuan"] == 50.0
    assert pool.executed


def test_admin_top_up_dual_ledger() -> None:
    pool = QuotaFakePool(
        fetchrow={
            "llm_config": {"api_key": "sk-test"},
            "quota_note": "",
            "metadata": {DISPLAY_BALANCE_METADATA_KEY: 10.0},
        },
    )
    repo = VoicePostgresRepository(pool=pool)

    async def run():
        with patch.object(repo, "get_credit_ratio", new=AsyncMock(return_value=0.95)), patch(
            "shuxin.voice.postgres_repository.top_up_token_by_api_key",
            new=AsyncMock(return_value={"ok": True}),
        ) as top_up, patch.object(
            repo,
            "get_user_quota_by_user_id",
            new=AsyncMock(
                return_value={
                    "configured": True,
                    "remain_yuan": 20.0,
                    "display_balance_yuan": 20.0,
                    "dmx_remain_yuan": 19.5,
                }
            ),
        ), patch.object(repo, "audit", new=AsyncMock()):
            result = await repo.top_up_user_dmx_quota("wx_user", add_yuan=10.0)
            return result, top_up

    result, top_up = asyncio.run(run())
    assert result["add_yuan"] == 10.0
    top_up.assert_awaited_once()
    assert top_up.await_args.kwargs["add_yuan"] == 9.5
    import json

    metadata_updates = [args for query, args in pool.executed if "metadata = $2" in query]
    assert metadata_updates
    metadata = json.loads(metadata_updates[0][1])
    assert metadata[DISPLAY_BALANCE_METADATA_KEY] == 20.0
