from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, date, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from shuxin.voice.postgres_repository import VoicePostgresRepository

class FakeConnection:
    def __init__(self, fetchrow_val=None, fetch_vals=None):
        self.fetchrow_val = fetchrow_val
        self.fetch_vals = fetch_vals or []
        self.executed = []

    async def fetchrow(self, query, *args):
        self.executed.append((query, args))
        return self.fetchrow_val

    async def fetch(self, query, *args):
        self.executed.append((query, args))
        return self.fetch_vals

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "UPDATE 1"

    async def execute_inside_transaction(self, query, *args):
        self.executed.append((query, args))
        return "UPDATE 1"

class FakeTransaction:
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class FakePool:
    def __init__(self, conn=None):
        self.conn = conn or FakeConnection()

    def acquire(self):
        class Context:
            def __init__(self, conn):
                self.conn = conn
            async def __aenter__(self):
                return self.conn
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
        return Context(self.conn)

    async def fetchrow(self, query, *args):
        return await self.conn.fetchrow(query, *args)

    async def fetch(self, query, *args):
        return await self.conn.fetch(query, *args)

    async def execute(self, query, *args):
        return await self.conn.execute(query, *args)


def test_deduct_device_minutes_quota_subscription_priority() -> None:
    # Mock transaction context
    class ConnWithTx(FakeConnection):
        def transaction(self):
            return FakeTransaction()
        async def fetchrow(self, query, *args):
            self.executed.append((query, args))
            if "device_bindings" in query:
                return {"user_id": "test_user"}
            return None
        async def fetch(self, query, *args):
            self.executed.append((query, args))
            if "devices" in query:
                return [{
                    "device_id": "test_device",
                    "subscription_plan_id": "sub_premium",
                    "subscription_minutes_limit": 100,
                    "subscription_minutes_used": 10.0,
                    "subscription_expires_at": None,
                    "fuel_minutes_balance": 5.0,
                    "daily_allowance_date": None,
                    "daily_allowance_seconds_used": 0.0,
                    "last_reset_month": "2026-06",
                    "enabled": True,
                }]
            return []
    
    conn_tx = ConnWithTx()
    repo = VoicePostgresRepository(pool=FakePool(conn_tx))

    async def run():
        # Deduct 5 minutes.
        await repo.deduct_device_minutes_quota("test_device", 5.0)

    asyncio.run(run())

    # Verify that the update query set subscription_minutes_used
    update_queries = [x for x in conn_tx.executed if "UPDATE devices" in x[0]]
    assert len(update_queries) > 0


def test_deduct_device_minutes_quota_spillover_to_fuel() -> None:
    class ConnWithTx(FakeConnection):
        def transaction(self):
            return FakeTransaction()
        async def fetchrow(self, query, *args):
            self.executed.append((query, args))
            if "device_bindings" in query:
                return {"user_id": "test_user"}
            return None
        async def fetch(self, query, *args):
            self.executed.append((query, args))
            if "devices" in query:
                return [{
                    "device_id": "test_device",
                    "subscription_plan_id": "sub_premium",
                    "subscription_minutes_limit": 10,
                    "subscription_minutes_used": 8.0,
                    "subscription_expires_at": None,
                    "fuel_minutes_balance": 5.0,
                    "daily_allowance_date": None,
                    "daily_allowance_seconds_used": 0.0,
                    "last_reset_month": "2026-06",
                    "enabled": True,
                }]
            return []

    conn_tx = ConnWithTx()
    repo = VoicePostgresRepository(pool=FakePool(conn_tx))

    async def run():
        await repo.deduct_device_minutes_quota("test_device", 5.0)

    asyncio.run(run())
    update_queries = [x for x in conn_tx.executed if "UPDATE devices" in x[0]]
    assert len(update_queries) > 0


def test_device_binding_welcome_gift() -> None:
    class DynamicFakeConnection(FakeConnection):
        async def fetchrow(self, query, *args):
            self.executed.append((query, args))
            if "devices" in query:
                return {"status": "provisioned", "metadata": "{}"}
            elif "miniapp_allowance_settings" in query:
                return {
                    "gift_subscription_plan_id": "gift_plan_id",
                    "gift_duration_months": 3
                }
            elif "miniapp_subscription_plans" in query:
                return {"duration_minutes": 100}
            elif "device_bindings" in query:
                return None
            return None

    conn = DynamicFakeConnection()
    repo = VoicePostgresRepository(pool=FakePool(conn))

    async def run():
        res = await repo._bind_device_for_user(conn, user_id="test_user", device_id="device_123", event_type="bind_hello")
        assert res["already_bound"] is False

    asyncio.run(run())

    device_updates = [x for x in conn.executed if "UPDATE devices" in x[0]]
    assert len(device_updates) == 2
    
    # The second update is the gift assignment
    args = device_updates[1][1]
    assert args[0] == "device_123"
    assert args[1] == "gift_plan_id"
    assert args[2] == 100
    assert args[3] == 3


def test_create_miniapp_payment_order_uses_pay_yuan_for_add_yuan() -> None:
    insert_return = {
        "order_id": "order-mini-1",
        "out_trade_no": "sxmini",
        "plan_id": "jichuban",
        "plan_name": "基础版",
        "amount_fen": 1,
        "add_yuan": 0.01,
        "duration_days": 30,
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
        "pay_yuan": 0.01,
        "display_credited": 0.0,
        "dmx_credited": 0.0,
        "credit_ratio": 1.0,
        "device_id": "SX-000119",
    }

    class CreateOrderConn(FakeConnection):
        async def fetchrow(self, query, *args):
            self.executed.append((query, args))
            if "miniapp_subscription_plans" in query:
                return {"name": "基础版", "amount_fen": 1, "duration_minutes": 60}
            if "INSERT INTO payment_orders" in query:
                assert args[6] == 0.01  # add_yuan placeholder, not 0
                return insert_return
            if "device_bindings" in query:
                return {"device_id": "SX-000119"}
            return None

    conn = CreateOrderConn()
    repo = VoicePostgresRepository(pool=FakePool(conn))

    async def run():
        with patch.object(
            repo,
            "_user_id_from_wechat_auth",
            new=AsyncMock(return_value="wx_user"),
        ):
            return await repo.create_payment_order(
                session_token="sess",
                plan_id="jichuban",
                device_id="SX-000119",
            )

    result = asyncio.run(run())
    assert result["plan"]["amount_fen"] == 1
    assert result["plan"]["amount_yuan"] == 0.01


class MiniappFulfillConn:
    def __init__(self) -> None:
        self.executed: list[tuple] = []

    async def fetchrow(self, query: str, *args):
        if "FROM payment_orders" in query:
            return {
                "order_id": "order-mini-1",
                "user_id": "wx_user",
                "plan_id": "jichuban",
                "plan_name": "基础版",
                "amount_fen": 1,
                "add_yuan": 0.01,
                "duration_days": 30,
                "status": "pending",
                "wx_transaction_id": None,
                "pay_yuan": 0.01,
                "display_credited": 0.0,
                "dmx_credited": 0.0,
                "credit_ratio": 1.0,
                "device_id": "SX-000119",
            }
        if "miniapp_subscription_plans" in query:
            return {"duration_minutes": 60}
        return None

    async def execute(self, query: str, *args):
        self.executed.append((query, args))

    @asynccontextmanager
    async def transaction(self):
        yield


class MiniappFulfillAcquire:
    def __init__(self, conn: MiniappFulfillConn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_args):
        return False


class MiniappFulfillPool:
    def __init__(self, conn: MiniappFulfillConn) -> None:
        self.conn = conn

    def acquire(self):
        return MiniappFulfillAcquire(self.conn)

    async def execute(self, query, *args):
        await self.conn.execute(query, *args)


def test_fulfill_miniapp_payment_order_preserves_add_yuan() -> None:
    conn = MiniappFulfillConn()
    repo = VoicePostgresRepository(pool=MiniappFulfillPool(conn))
    notify = {"amount": {"total": 1}}

    async def run():
        with patch(
            "shuxin.voice.postgres_repository.top_up_token_by_api_key",
            new=AsyncMock(return_value={"ok": True}),
        ) as top_up:
            result = await repo.fulfill_payment_order(
                out_trade_no="sxmini",
                wx_transaction_id="wx-tx-mini",
                notify_payload=notify,
            )
        return result, top_up

    result, top_up = asyncio.run(run())
    assert result["status"] == "paid"
    assert result["add_yuan"] == 0.01
    top_up.assert_not_awaited()
    order_updates = [args for query, args in conn.executed if "UPDATE payment_orders" in query]
    assert order_updates
    assert order_updates[0][7] == 0.01

    # Assert last_reset_month is written to devices
    device_updates = [args for query, args in conn.executed if "UPDATE devices" in query]
    assert device_updates
    # args: device_id, plan_id, duration_minutes, current_month_str
    assert device_updates[0][3] == datetime.now(timezone.utc).strftime("%Y-%m")


def test_create_miniapp_payment_order_duplicate_purchase() -> None:
    from datetime import timedelta
    insert_return = {
        "order_id": "order-mini-1",
        "out_trade_no": "sxmini",
        "plan_id": "jichuban",
        "plan_name": "基础版",
        "amount_fen": 1,
        "add_yuan": 0.01,
        "duration_days": 30,
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
        "pay_yuan": 0.01,
        "display_credited": 0.0,
        "dmx_credited": 0.0,
        "credit_ratio": 1.0,
        "device_id": "SX-000119",
    }

    class DuplicateOrderConn(FakeConnection):
        async def fetchrow(self, query, *args):
            self.executed.append((query, args))
            if "miniapp_subscription_plans" in query:
                return {"name": "基础版", "amount_fen": 1, "duration_minutes": 60}
            if "INSERT INTO payment_orders" in query:
                return insert_return
            if "device_bindings" in query:
                return {"device_id": "SX-000119"}
            if "devices" in query:
                return {
                    "subscription_plan_id": "jichuban",
                    "subscription_expires_at": datetime.now(timezone.utc) + timedelta(days=10)
                }
            return None

    conn = DuplicateOrderConn()
    repo = VoicePostgresRepository(pool=FakePool(conn))

    async def run():
        with patch.object(
            repo,
            "_user_id_from_wechat_auth",
            new=AsyncMock(return_value="wx_user"),
        ):
            await repo.create_payment_order(
                session_token="sess",
                plan_id="jichuban",
                device_id="SX-000119",
            )

    with pytest.raises(PermissionError) as exc_info:
        asyncio.run(run())
    assert "无法重复购买" in str(exc_info.value)


def test_create_miniapp_payment_order_downgrade_purchase() -> None:
    from datetime import timedelta
    insert_return = {
        "order_id": "order-mini-2",
        "out_trade_no": "sxmini-2",
        "plan_id": "jichuban",
        "plan_name": "基础版",
        "amount_fen": 1,
        "add_yuan": 0.01,
        "duration_days": 30,
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
        "pay_yuan": 0.01,
        "display_credited": 0.0,
        "dmx_credited": 0.0,
        "credit_ratio": 1.0,
        "device_id": "SX-000119",
    }

    class DowngradeOrderConn(FakeConnection):
        async def fetchrow(self, query, *args):
            self.executed.append((query, args))
            if "miniapp_subscription_plans" in query:
                pid = args[0]
                if pid == "gaojiban":
                    return {"name": "高级版", "amount_fen": 2, "duration_minutes": 300}
                elif pid == "jichuban":
                    return {"name": "基础版", "amount_fen": 1, "duration_minutes": 60}
            if "INSERT INTO payment_orders" in query:
                return insert_return
            if "device_bindings" in query:
                return {"device_id": "SX-000119"}
            if "devices" in query:
                return {
                    "subscription_plan_id": "gaojiban",
                    "subscription_expires_at": datetime.now(timezone.utc) + timedelta(days=10)
                }
            return None

    conn = DowngradeOrderConn()
    repo = VoicePostgresRepository(pool=FakePool(conn))

    async def run():
        with patch.object(
            repo,
            "_user_id_from_wechat_auth",
            new=AsyncMock(return_value="wx_user"),
        ):
            await repo.create_payment_order(
                session_token="sess",
                plan_id="jichuban",
                device_id="SX-000119",
            )

    with pytest.raises(PermissionError) as exc_info:
        asyncio.run(run())
    assert "无法降级购买" in str(exc_info.value)


def test_cross_month_reset_preserves_fuel_balance_on_query() -> None:
    """跨月重置 subscription_minutes_used，但不清零 fuel_minutes_balance。"""
    class CrossMonthConn(FakeConnection):
        async def fetchrow(self, query, *args):
            self.executed.append((query, args))
            if "device_bindings" in query:
                return {"user_id": "test_user"}
            if "miniapp_allowance_settings" in query:
                return {"daily_free_minutes": 1.5, "enabled": True}
            return None

        async def fetch(self, query, *args):
            self.executed.append((query, args))
            if "devices d" in query or ("devices" in query and "device_bindings" in query):
                return [{
                    "device_id": "test_device",
                    "subscription_plan_id": "sub_basic",
                    "subscription_minutes_limit": 100.0,
                    "subscription_minutes_used": 50.0,
                    "subscription_expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
                    "fuel_minutes_balance": 30.0,
                    "last_reset_month": "2020-01",
                    "daily_allowance_date": None,
                    "daily_allowance_seconds_used": 0.0,
                }]
            return []

    conn = CrossMonthConn()
    repo = VoicePostgresRepository(pool=FakePool(conn))

    async def run():
        return await repo.get_device_quota("test_device")

    quota = asyncio.run(run())
    assert quota["fuel_minutes_left"] == 30.0
    assert quota["subscription_minutes_left"] == 100.0
    update_queries = [x for x in conn.executed if "UPDATE devices" in x[0]]
    assert len(update_queries) == 1
    sql = update_queries[0][0]
    assert "subscription_minutes_used = 0.0000" in sql
    assert "fuel_minutes_balance" not in sql


def test_cross_month_reset_preserves_fuel_balance_on_deduct() -> None:
    """deduct 路径跨月重置同样保留加油包。"""
    class CrossMonthDeductConn(FakeConnection):
        def transaction(self):
            return FakeTransaction()

        async def fetchrow(self, query, *args):
            self.executed.append((query, args))
            if "device_bindings" in query:
                return {"user_id": "test_user"}
            if "miniapp_allowance_settings" in query:
                return {"daily_free_minutes": 1.5, "enabled": True}
            return None

        async def fetch(self, query, *args):
            self.executed.append((query, args))
            if "devices" in query:
                return [{
                    "device_id": "test_device",
                    "subscription_plan_id": None,
                    "subscription_minutes_limit": 0.0,
                    "subscription_minutes_used": 0.0,
                    "subscription_expires_at": None,
                    "fuel_minutes_balance": 20.0,
                    "last_reset_month": "2020-01",
                    "daily_allowance_date": None,
                    "daily_allowance_seconds_used": 0.0,
                }]
            return []

    conn = CrossMonthDeductConn()
    repo = VoicePostgresRepository(pool=FakePool(conn))

    async def run():
        await repo.deduct_device_minutes_quota("test_device", 1.0)

    asyncio.run(run())
    reset_queries = [
        x for x in conn.executed
        if "UPDATE devices" in x[0]
        and "last_reset_month" in x[0]
        and "fuel_minutes_balance" not in x[0]
    ]
    assert len(reset_queries) == 1

