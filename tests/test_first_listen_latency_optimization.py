from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from shuxin.voice.agents import AgentRecord
from shuxin.voice.config import DeviceConfig, LLMDeviceConfig, ProviderConfig
from shuxin.voice.server import _VoiceWebSocketSession
from shuxin.voice.users import UserSettings
from shuxin.voice.postgres_repository import VoicePostgresRepository
from shuxin.voice.dmx_client import create_user_token

def test_device_auth_cache() -> None:
    async def run() -> None:
        # Test that authenticate_device uses memory caching and only queries the DB on the first call
        pool = MagicMock()
        repo = VoicePostgresRepository(pool)
        
        device_code = "SX-test-cache-001"
        device_secret = "secret-abc"
        
        db_row = {
            "device_id": "SX-test-cache-001",
            "auth_mode": "per_device_secret",
            "device_secret_hash": "dummy_hash",
            "user_id": "user-abc",
            "audio_quota_mb": 512,
            "llm_config": '{"api_key": "user-api-key"}',
            "agent_id": "shuxin"
        }
        
        # Mock postgres return value
        pool.fetchrow = AsyncMock(side_effect=[
            db_row, # for authenticate_device SELECT
            {"llm_config": '{"api_key": "user-api-key"}'} # for ensure_user_dmx_llm users query
        ])
        
        # Mock verify secret and get_device
        with patch("shuxin.voice.postgres_repository._verify_device_secret", return_value=True):
            with patch.object(repo, "ensure_user_dmx_llm", new=AsyncMock()):
                # 1. First call: Cache miss, queries the database
                settings_1 = await repo.authenticate_device(device_code, device_secret)
                assert settings_1.user_id == "user-abc"
                assert pool.fetchrow.call_count == 2 # 1 for auth, 1 for ensure_user_dmx_llm
                
                # 2. Second call: Cache hit, no database queries
                settings_2 = await repo.authenticate_device(device_code, device_secret)
                assert settings_2.user_id == "user-abc"
                assert pool.fetchrow.call_count == 2 # call count remains 2! Cache was hit!

    asyncio.run(run())

def test_dmx_balance_query_decoupled() -> None:
    async def run() -> None:
        # Test that get_device_quota does NOT query DMX when admin_detail is False
        pool = MagicMock()
        repo = VoicePostgresRepository(pool)
        
        db_row = {
            "device_id": "SX-device-001",
            "subscription_plan_id": 1,
            "subscription_minutes_limit": 100.0,
            "subscription_minutes_used": 10.0,
            "subscription_expires_at": None,
            "fuel_minutes_balance": 50.0,
            "last_reset_month": "2026-06",
            "daily_allowance_date": None,
            "daily_allowance_seconds_used": 0.0,
        }
        
        pool.fetchrow = AsyncMock(side_effect=[
            {"user_id": "user-abc"}, # 1st: select user_id from device_bindings
            {"daily_free_minutes": 1.5, "enabled": True}, # 2nd: select miniapp_allowance_settings
        ])
        pool.fetch = AsyncMock(return_value=[db_row]) # select devices
        
        with patch("shuxin.voice.postgres_repository.get_token_balance", new=AsyncMock()) as mock_balance:
            quota = await repo.get_device_quota("SX-device-001", admin_detail=False)
            assert quota["exhausted"] is False
            assert quota["total_minutes_left"] == 51.5 # sub_expires_at is None, so sub_remaining is 0.0, total is 50.0 + 1.5 allowance = 51.5
            assert mock_balance.call_count == 0 # Decoupled! DMX check is skipped when admin_detail=False

    asyncio.run(run())

def test_create_user_token_unlimited() -> None:
    async def run() -> None:
        # Mock responses
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = MagicMock()

        # Mock httpx client
        client_instance = AsyncMock()
        client_instance.post = AsyncMock(return_value=mock_response)
        
        # Setup context manager mock
        async_client_mock = MagicMock()
        async_client_mock.return_value.__aenter__.return_value = client_instance
        
        with patch("shuxin.voice.dmx_client.dmx_admin_configured", return_value=True):
            with patch("shuxin.voice.dmx_client._admin_headers", return_value={"Authorization": "Bearer test-admin-token"}):
                with patch("shuxin.voice.dmx_client.httpx.AsyncClient", new=async_client_mock):
                    with patch("shuxin.voice.dmx_client._fetch_token_key_by_name", new=AsyncMock(return_value="sk-unlimited-token-abc")):
                        api_key = await create_user_token(name="test-unlimited", unlimited_quota=True)
                        assert api_key == "sk-unlimited-token-abc"
                        
                        # Verify HTTP post body has unlimited_quota: True and remain_quota: 0
                        called_args, called_kwargs = client_instance.post.call_args
                        payload = called_kwargs.get("json")
                        assert payload["unlimited_quota"] is True
                        assert payload["remain_quota"] == 0

    asyncio.run(run())

def test_create_wechat_session_guards_deleted_user() -> None:
    async def run() -> None:
        pool = MagicMock()
        repo = VoicePostgresRepository(pool)
        
        # Mock connection context manager
        conn = AsyncMock()
        
        # When conn.fetchrow is called to check user status, return enabled=False
        conn.fetchrow = AsyncMock(return_value={"enabled": False, "deleted_at": None})
        
        # Mock acquire context manager on pool
        pool.acquire = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = conn
        
        with patch("shuxin.voice.postgres_repository._openid_from_wx_code", new=AsyncMock(return_value="openid-test")):
            with pytest.raises(PermissionError) as exc_info:
                await repo.create_wechat_session(wx_code="some-wx-code")
            assert str(exc_info.value) == "User account is disabled or deleted"
            
        # Re-mock to return soft-deleted user (deleted_at is not None)
        conn.fetchrow = AsyncMock(return_value={"enabled": True, "deleted_at": "some-timestamp"})
        with patch("shuxin.voice.postgres_repository._openid_from_wx_code", new=AsyncMock(return_value="openid-test")):
            with pytest.raises(PermissionError) as exc_info:
                await repo.create_wechat_session(wx_code="some-wx-code")
            assert str(exc_info.value) == "User account is disabled or deleted"

    asyncio.run(run())

def test_admin_bind_device_first_activation_gifts_plan() -> None:
    async def run() -> None:
        pool = MagicMock()
        repo = VoicePostgresRepository(pool)
        
        # Mock connection context manager
        conn = AsyncMock()
        
        # Setup transaction mock
        tx_mock = MagicMock()
        tx_mock.__aenter__ = AsyncMock()
        tx_mock.__aexit__ = AsyncMock()
        conn.transaction = MagicMock(return_value=tx_mock)
        
        # When conn.fetchrow is called inside admin_bind_device
        conn.fetchrow = AsyncMock(side_effect=[
            None, # 1st: SELECT binding_id FROM device_bindings
            {"status": "provisioned"}, # 2nd: SELECT status FROM devices
            {"gift_subscription_plan_id": "jichuban", "gift_duration_months": 3}, # 3rd: SELECT gift rules
            {"duration_minutes": 300}, # 4th: SELECT plan duration
        ])
        
        # Mock fetchval for device/user exist checks
        conn.fetchval = AsyncMock(return_value=True)
        
        # Mock acquire context manager on pool
        pool.acquire = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = conn
        
        # We need to mock record_binding_event and audit
        with patch.object(repo, "_record_binding_event", new=AsyncMock()):
            with patch.object(repo, "audit", new=AsyncMock()):
                res = await repo.admin_bind_device(user_id="wx_test_123", device_id="SX-000999")
                assert res["device_id"] == "SX-000999"
                assert res["user_id"] == "wx_test_123"
                
                # Verify that conn.execute was called to update devices with jichuban and 300 minutes
                # It should be the third execute call
                called_executes = conn.execute.call_args_list
                assert len(called_executes) >= 3
                
                # Check the third execute call (the update query)
                update_args = called_executes[2][0]
                assert "UPDATE devices" in update_args[0]
                assert update_args[1] == "SX-000999" # device_id
                assert update_args[2] == "jichuban" # gift_plan_id
                assert update_args[3] == 300 # duration_minutes
                assert update_args[4] == 3 # gift_months

    asyncio.run(run())

def test_multi_device_quota_aggregation() -> None:
    async def run() -> None:
        pool = MagicMock()
        repo = VoicePostgresRepository(pool)
        
        # Mock pool query methods directly
        pool.fetchrow = AsyncMock(side_effect=[
            {"user_id": "test_user_123"}, # bound check
            {"daily_free_minutes": 5.0, "enabled": True} # global settings
        ])
        
        from datetime import datetime, timezone, timedelta
        future_date = datetime.now(timezone.utc) + timedelta(days=30)
        
        device_a = {
            "device_id": "SX-001",
            "subscription_plan_id": "jichuban",
            "subscription_minutes_limit": 120.0,
            "subscription_minutes_used": 20.0,
            "subscription_expires_at": future_date,
            "fuel_minutes_balance": 50.0,
            "last_reset_month": datetime.now(timezone.utc).strftime("%Y-%m"),
            "daily_allowance_date": datetime.now(timezone.utc).date(),
            "daily_allowance_seconds_used": 60.0 # 1 minute used
        }
        device_b = {
            "device_id": "SX-002",
            "subscription_plan_id": "simple",
            "subscription_minutes_limit": 300.0,
            "subscription_minutes_used": 50.0,
            "subscription_expires_at": future_date,
            "fuel_minutes_balance": 100.0,
            "last_reset_month": datetime.now(timezone.utc).strftime("%Y-%m"),
            "daily_allowance_date": datetime.now(timezone.utc).date(),
            "daily_allowance_seconds_used": 120.0 # 2 minutes used
        }
        pool.fetch = AsyncMock(return_value=[device_a, device_b])
        
        res = await repo.get_device_quota("SX-001")
        
        # Calculations:
        # sub_rem_a = 120 - 20 = 100
        # sub_rem_b = 300 - 50 = 250
        # Total sub remaining = 350
        # Total fuel remaining = 50 + 100 = 150
        # Allowance remaining a = 5 - 1 = 4
        # Allowance remaining b = 5 - 2 = 3
        # Total allowance remaining = 7
        # Total minutes left = 350 + 150 + 7 = 507
        assert res["subscription_minutes_left"] == 350.0
        assert res["fuel_minutes_left"] == 150.0
        assert res["daily_allowance_left"] == 7.0
        assert res["total_minutes_left"] == 507.0

    asyncio.run(run())

def test_multi_device_quota_deduction() -> None:
    async def run() -> None:
        pool = MagicMock()
        repo = VoicePostgresRepository(pool)
        
        # Mock connection context manager
        conn = AsyncMock()
        pool.acquire = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = conn
        
        # Setup transaction mock
        tx_mock = MagicMock()
        tx_mock.__aenter__ = AsyncMock()
        tx_mock.__aexit__ = AsyncMock()
        conn.transaction = MagicMock(return_value=tx_mock)
        
        # For deduct_device_minutes_quota:
        # 1st call: fetchrow to find user_id for the device -> return {"user_id": "test_user_123"}
        # 2nd call: fetch to get all active bound devices -> return [device A, device B]
        from datetime import datetime, timezone, timedelta
        future_date = datetime.now(timezone.utc) + timedelta(days=30)
        
        device_a = {
            "device_id": "SX-001",
            "subscription_plan_id": "jichuban",
            "subscription_minutes_limit": 120.0,
            "subscription_minutes_used": 20.0,
            "subscription_expires_at": future_date,
            "fuel_minutes_balance": 50.0,
            "last_reset_month": datetime.now(timezone.utc).strftime("%Y-%m"),
            "daily_allowance_date": datetime.now(timezone.utc).date(),
            "daily_allowance_seconds_used": 0.0
        }
        device_b = {
            "device_id": "SX-002",
            "subscription_plan_id": "simple",
            "subscription_minutes_limit": 300.0,
            "subscription_minutes_used": 50.0,
            "subscription_expires_at": future_date,
            "fuel_minutes_balance": 100.0,
            "last_reset_month": datetime.now(timezone.utc).strftime("%Y-%m"),
            "daily_allowance_date": datetime.now(timezone.utc).date(),
            "daily_allowance_seconds_used": 0.0
        }
        
        conn.fetchrow = AsyncMock(return_value={"user_id": "test_user_123"})
        conn.fetch = AsyncMock(return_value=[device_a, device_b])
        
        # Deduct 150 minutes
        # First priority: subscription.
        # device_a sub_rem = 100 -> deducts 100 from device_a (used becomes 120)
        # device_b sub_rem = 250 -> deducts remaining 50 from device_b (used becomes 100)
        await repo.deduct_device_minutes_quota("SX-001", 150.0)
        
        # Verify execute updates
        called_executes = conn.execute.call_args_list
        assert len(called_executes) >= 2
        
        # Find updates for device A and B
        updates = {}
        for call in called_executes:
            query = call[0][0]
            if "UPDATE devices" in query:
                dev_id = call[0][1]
                sub_used = call[0][2]
                updates[dev_id] = sub_used
                
        assert updates["SX-001"] == 120.0
        assert updates["SX-002"] == 100.0

    asyncio.run(run())
