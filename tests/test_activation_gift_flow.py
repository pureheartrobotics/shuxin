"""End-to-end tests: activation gift + bind while user quota exhausted."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from shuxin.voice.persistence.base_repo import _hash_secret
from shuxin.voice.persistence.postgres_repository import VoicePostgresRepository
from shuxin.voice.server import create_app

GIFT_PLAN_ID = "jichuban"
GIFT_MINUTES = 120
GIFT_MONTHS = 3
DAILY_FREE_MINUTES = 3.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _default_device(device_id: str, *, status: str = "provisioned") -> dict[str, Any]:
    return {
        "device_id": device_id,
        "status": status,
        "enabled": True,
        "deleted_at": None,
        "metadata": {},
        "subscription_plan_id": None,
        "subscription_minutes_limit": 0.0,
        "subscription_minutes_used": 0.0,
        "subscription_expires_at": None,
        "fuel_minutes_balance": 0.0,
        "last_reset_month": _now().strftime("%Y-%m"),
        "daily_allowance_date": None,
        "daily_allowance_seconds_used": 0.0,
    }


class ActivationGiftState:
    """Minimal in-memory store for gift + quota integration tests."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.devices: dict[str, dict[str, Any]] = {}
        self.bindings: list[dict[str, Any]] = []
        self.sessions: dict[str, str] = {}  # token_hash -> user_id

    def add_user(self, user_id: str) -> None:
        self.users[user_id] = {
            "user_id": user_id,
            "enabled": True,
            "deleted_at": None,
            "metadata": {},
            "llm_config": {},
        }

    def add_device(self, device_id: str, *, status: str = "provisioned") -> None:
        self.devices[device_id] = _default_device(device_id, status=status)

    def register_session(self, user_id: str, session_token: str) -> None:
        self.sessions[_hash_secret(session_token)] = user_id

    def zero_user_pool(self, user_id: str) -> None:
        today = _now().date()
        for binding in self.bindings:
            if binding["user_id"] != user_id or binding["status"] != "active":
                continue
            device = self.devices[binding["device_id"]]
            device["subscription_minutes_limit"] = 0.0
            device["subscription_minutes_used"] = 0.0
            device["subscription_expires_at"] = None
            device["fuel_minutes_balance"] = 0.0
            device["daily_allowance_date"] = today
            device["daily_allowance_seconds_used"] = 99999.0

    def _active_bindings(self, *, user_id: str | None = None, device_id: str | None = None) -> list[dict[str, Any]]:
        rows = [b for b in self.bindings if b["status"] == "active"]
        if user_id is not None:
            rows = [b for b in rows if b["user_id"] == user_id]
        if device_id is not None:
            rows = [b for b in rows if b["device_id"] == device_id]
        return rows

    def _device_quota_row(self, device_id: str) -> dict[str, Any]:
        device = self.devices[device_id]
        return {
            "device_id": device_id,
            "subscription_plan_id": device["subscription_plan_id"],
            "subscription_minutes_limit": device["subscription_minutes_limit"],
            "subscription_minutes_used": device["subscription_minutes_used"],
            "subscription_expires_at": device["subscription_expires_at"],
            "fuel_minutes_balance": device["fuel_minutes_balance"],
            "last_reset_month": device["last_reset_month"],
            "daily_allowance_date": device["daily_allowance_date"],
            "daily_allowance_seconds_used": device["daily_allowance_seconds_used"],
        }


class FakeTransaction:
    async def __aenter__(self) -> FakeTransaction:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


class StatefulGiftConnection:
    def __init__(self, state: ActivationGiftState) -> None:
        self.state = state
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.executed.append((query, args))
        q = " ".join(query.split())
        if "FROM users" in q and "SELECT 1" in q:
            user_id = args[0]
            user = self.state.users.get(user_id)
            return 1 if user and user["enabled"] and user["deleted_at"] is None else None
        if "FROM devices" in q and "SELECT 1" in q:
            device_id = args[0]
            device = self.state.devices.get(device_id)
            if device and device["enabled"] and device["deleted_at"] is None and device["status"] != "disabled":
                return 1
            return None
        if "FROM wechat_sessions" in q:
            token_hash = args[0]
            user_id = self.state.sessions.get(token_hash)
            return user_id
        return None

    async def fetchrow(self, query: str, *args: Any) -> Any:
        self.executed.append((query, args))
        q = " ".join(query.split())
        state = self.state

        if "FROM wechat_sessions" in q:
            token_hash = args[0]
            user_id = state.sessions.get(token_hash)
            if not user_id:
                return None
            return {"user_id": user_id}

        if "miniapp_allowance_settings" in q:
            return {
                "gift_subscription_plan_id": GIFT_PLAN_ID,
                "gift_duration_months": GIFT_MONTHS,
                "daily_free_minutes": DAILY_FREE_MINUTES,
                "enabled": True,
            }

        if "miniapp_subscription_plans" in q and "duration_minutes" in q:
            return {"duration_minutes": GIFT_MINUTES}

        if "FROM device_bindings" in q and "binding_id = $1" in q:
            binding_id = args[0]
            for binding in state.bindings:
                if binding["binding_id"] == binding_id and binding["status"] == "active":
                    return {"user_id": binding["user_id"], "device_id": binding["device_id"]}
            return None

        if "FROM device_bindings" in q and "SELECT 1" in q and "LIMIT 1" in q:
            device_id = args[0]
            history = [b for b in state.bindings if b["device_id"] == device_id]
            return {"?": 1} if history else None

        if "FROM device_bindings" in q and "status = 'active'" in q and "device_id = $1" in q:
            device_id = args[0]
            active = state._active_bindings(device_id=device_id)
            if not active:
                return None
            row = active[0]
            return {"binding_id": row["binding_id"], "user_id": row["user_id"]}

        if "JOIN device_bindings b" in q and "ORDER BY b.bound_at DESC" in q:
            user_id = args[0]
            active = state._active_bindings(user_id=user_id)
            if not active:
                return None
            latest = sorted(active, key=lambda b: b["bound_at"], reverse=True)[0]
            return {"device_id": latest["device_id"]}

        if "FROM device_bindings" in q and "ORDER BY bound_at DESC LIMIT 1" in q:
            device_id = args[0]
            active = state._active_bindings(device_id=device_id)
            if not active:
                return None
            return {"user_id": active[0]["user_id"]}

        if "FROM devices" in q and "SELECT metadata" in q:
            device_id = args[0]
            device = state.devices.get(device_id)
            if not device:
                return None
            return {"metadata": device["metadata"]}

        if "FROM devices" in q and "SELECT status, metadata" in q:
            device_id = args[0]
            device = state.devices.get(device_id)
            if not device:
                return None
            return {"status": device["status"], "metadata": device["metadata"]}

        if "FROM devices" in q and "subscription_plan_id" in q:
            device_id = args[0]
            device = state.devices.get(device_id)
            if not device:
                return None
            return state._device_quota_row(device_id)

        if "FROM users" in q and "metadata" in q:
            user_id = args[0]
            user = state.users.get(user_id)
            if not user:
                return None
            return {"metadata": user["metadata"]}

        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.executed.append((query, args))
        q = " ".join(query.split())
        if "JOIN device_bindings b" in q and "WHERE b.user_id = $1" in q:
            user_id = args[0]
            rows = []
            for binding in self.state._active_bindings(user_id=user_id):
                rows.append(self.state._device_quota_row(binding["device_id"]))
            return rows
        return []

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        q = " ".join(query.split())
        state = self.state

        if "INSERT INTO device_bindings" in q:
            binding_id, user_id, device_id = args[0], args[1], args[2]
            state.bindings.append(
                {
                    "binding_id": binding_id,
                    "user_id": user_id,
                    "device_id": device_id,
                    "status": "active",
                    "bound_at": _now(),
                }
            )
            return "INSERT 0 1"

        if "UPDATE device_bindings" in q and "status = 'unbound'" in q:
            user_id, device_id = args[0], args[1]
            updated = 0
            for binding in state.bindings:
                if (
                    binding["user_id"] == user_id
                    and binding["device_id"] == device_id
                    and binding["status"] == "active"
                ):
                    binding["status"] = "unbound"
                    updated = 1
            return f"UPDATE {updated}"

        if "UPDATE devices" in q and "status = 'provisioned'" in q:
            device_id = args[0]
            if not state._active_bindings(device_id=device_id):
                state.devices[device_id]["status"] = "provisioned"
            return "UPDATE 1"

        if "UPDATE devices" in q and "SET status = 'bound'" in q:
            device_id = args[0]
            state.devices[device_id]["status"] = "bound"
            return "UPDATE 1"

        if "UPDATE devices" in q and "subscription_plan_id = $2" in q:
            device_id = args[0]
            gift_plan_id = args[1]
            duration_minutes = float(args[2])
            gift_months = int(args[3])
            meta_raw = args[4]
            if isinstance(meta_raw, str):
                meta = json.loads(meta_raw)
            else:
                meta = dict(meta_raw)
            device = state.devices[device_id]
            device["subscription_plan_id"] = gift_plan_id
            device["subscription_minutes_limit"] = duration_minutes
            device["subscription_minutes_used"] = 0.0
            device["subscription_expires_at"] = _now() + timedelta(days=30 * gift_months)
            device["metadata"] = meta
            return "UPDATE 1"

        if "INSERT INTO users" in q:
            user_id = args[0]
            if user_id not in state.users:
                state.add_user(user_id)
            else:
                state.users[user_id]["deleted_at"] = None
                state.users[user_id]["enabled"] = True
            return "INSERT 0 1"

        if "UPDATE devices" in q and "subscription_minutes_used = 0" in q and "last_reset_month" in q:
            device_id = args[0]
            month = args[1]
            device = state.devices[device_id]
            device["subscription_minutes_used"] = 0.0
            device["last_reset_month"] = month
            return "UPDATE 1"

        return "UPDATE 0"


class StatefulGiftPool:
    def __init__(self, conn: StatefulGiftConnection) -> None:
        self.conn = conn

    def acquire(self) -> Any:
        @asynccontextmanager
        async def _ctx():
            yield self.conn

        return _ctx()

    async def fetchrow(self, query: str, *args: Any) -> Any:
        return await self.conn.fetchrow(query, *args)

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return await self.conn.fetch(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        return await self.conn.execute(query, *args)


def _build_repo(state: ActivationGiftState) -> VoicePostgresRepository:
    conn = StatefulGiftConnection(state)
    pool = StatefulGiftPool(conn)
    return VoicePostgresRepository(pool)


def _patch_repo_side_effects(repo: VoicePostgresRepository) -> None:
    repo.devices._record_binding_event = AsyncMock()
    repo.users.audit = AsyncMock()
    repo.audit = AsyncMock()
    repo.ensure_user_dmx_llm = AsyncMock()
    repo.devices._attach_mbti_reveal_on_bind = AsyncMock(return_value=None)
    repo.devices._clear_auth_cache = lambda _device_id: None


def test_exhausted_user_bind_new_device_restores_quota() -> None:
    state = ActivationGiftState()
    user_id = "wx_old_user"
    device_a = "SX-FLOW-A"
    device_b = "SX-FLOW-B"
    state.add_user(user_id)
    state.add_device(device_a)
    state.add_device(device_b)
    state.register_session(user_id, "session-flow-token")

    repo = _build_repo(state)
    _patch_repo_side_effects(repo)

    async def run() -> None:
        await repo.admin_bind_device(user_id=user_id, device_id=device_a)
        quota_after_first = await repo.get_user_quota_by_user_id(user_id)
        assert quota_after_first["exhausted"] is False
        assert quota_after_first["subscription_minutes_left"] == pytest.approx(GIFT_MINUTES)

        state.zero_user_pool(user_id)
        quota_exhausted = await repo.get_user_quota_by_user_id(user_id)
        assert quota_exhausted["exhausted"] is True
        assert quota_exhausted["total_minutes_left"] == 0.0

        bind_result = await repo.bind_device(
            session_token="session-flow-token",
            device_code=device_b,
        )
        assert bind_result["already_bound"] is False

        quota_after_bind = await repo.get_user_quota_by_user_id(user_id)
        assert quota_after_bind["exhausted"] is False
        assert quota_after_bind["subscription_minutes_left"] >= GIFT_MINUTES
        assert quota_after_bind["total_minutes_left"] >= GIFT_MINUTES

        device_meta = state.devices[device_b]["metadata"]
        assert device_meta.get("activation_gift_applied") is True
        assert state.devices[device_b]["subscription_minutes_limit"] == GIFT_MINUTES

    asyncio.run(run())


def test_bind_api_allows_exhausted_quota_with_stateful_repo() -> None:
    state = ActivationGiftState()
    user_id = "wx_api_user"
    device_id = "SX-FLOW-C"
    session_token = "session-api-token"
    state.add_user(user_id)
    state.add_device(device_id)
    state.register_session(user_id, session_token)

    repo = _build_repo(state)
    _patch_repo_side_effects(repo)
    state.zero_user_pool(user_id)

    app = create_app()
    with TestClient(app) as client:
        app.state.repo = repo
        response = client.post(
            "/api/devices/bind",
            json={"session_token": session_token, "device_code": device_id},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["device_code"] == device_id
    assert body["already_bound"] is False
    assert state.devices[device_id]["metadata"].get("activation_gift_applied") is True


def test_rebind_same_device_does_not_reapply_gift_quota() -> None:
    state = ActivationGiftState()
    user_id = "wx_rebind_user"
    device_id = "SX-FLOW-D"
    state.add_user(user_id)
    state.add_device(device_id)

    repo = _build_repo(state)
    _patch_repo_side_effects(repo)

    async def run() -> None:
        await repo.admin_bind_device(user_id=user_id, device_id=device_id)
        limit_after_gift = state.devices[device_id]["subscription_minutes_limit"]
        assert limit_after_gift == GIFT_MINUTES

        state.zero_user_pool(user_id)
        binding_id = state._active_bindings(device_id=device_id)[0]["binding_id"]
        await repo.admin_unbind_device(binding_id=binding_id)
        assert state.devices[device_id]["status"] == "provisioned"

        await repo.admin_bind_device(user_id=user_id, device_id=device_id)
        assert state.devices[device_id]["subscription_minutes_limit"] == 0.0
        assert state.devices[device_id]["metadata"].get("activation_gift_applied") is True

    asyncio.run(run())
