from __future__ import annotations

import asyncio
from datetime import datetime, date, timezone
from typing import Any
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

    async def execute(self, query, *args):
        return await self.conn.execute(query, *args)


def test_deduct_device_minutes_quota_subscription_priority() -> None:
    conn = FakeConnection(
        fetchrow_val={
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
        }
    )
    # Mock transaction context
    class ConnWithTx(FakeConnection):
        def transaction(self):
            return FakeTransaction()
    
    conn_tx = ConnWithTx(fetchrow_val=conn.fetchrow_val)
    repo = VoicePostgresRepository(pool=FakePool(conn_tx))

    async def run():
        # Deduct 5 minutes.
        await repo.deduct_device_minutes_quota("test_device", 5.0)

    asyncio.run(run())

    # Verify that the update query set subscription_minutes_used
    update_queries = [x for x in conn_tx.executed if "UPDATE devices" in x[0]]
    assert len(update_queries) > 0


def test_deduct_device_minutes_quota_spillover_to_fuel() -> None:
    conn = FakeConnection(
        fetchrow_val={
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
        }
    )
    class ConnWithTx(FakeConnection):
        def transaction(self):
            return FakeTransaction()

    conn_tx = ConnWithTx(fetchrow_val=conn.fetchrow_val)
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
