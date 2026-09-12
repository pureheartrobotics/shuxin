from __future__ import annotations
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from shuxin.voice.persistence.postgres_repository import VoicePostgresRepository

class FakePool:
    def __init__(self, fetchrow=None, fetchval=None, fetch=None) -> None:
        self.fetchrow_value = fetchrow
        self.fetchval_value = fetchval
        self.fetch_value = fetch or []
        self.executed_queries = []

    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def transaction(self):
        return self

    async def fetchrow(self, query, *args, **_kwargs):
        self.executed_queries.append((query, args))
        if callable(self.fetchrow_value):
            return self.fetchrow_value(query, *args)
        return self.fetchrow_value

    async def fetchval(self, query, *args, **_kwargs):
        self.executed_queries.append((query, args))
        if callable(self.fetchval_value):
            return self.fetchval_value(query, *args)
        return self.fetchval_value

    async def execute(self, query, *args, **_kwargs):
        self.executed_queries.append((query, args))
        return "UPDATE 1"

    async def fetch(self, query, *args, **_kwargs):
        self.executed_queries.append((query, args))
        return self.fetch_value


@pytest.mark.anyio
async def test_clear_auth_cache_directional_and_all() -> None:
    repo = VoicePostgresRepository(pool=None)
    repo._auth_cache = {
        "dev-1": ({"hash": "1"}, MagicMock(), 9999999999.0),
        "dev-2": ({"hash": "2"}, MagicMock(), 9999999999.0),
    }

    # Test directional pop
    repo._clear_auth_cache("dev-1")
    assert "dev-1" not in repo._auth_cache
    assert "dev-2" in repo._auth_cache

    # Test clear all
    repo._clear_auth_cache()
    assert len(repo._auth_cache) == 0


@pytest.mark.anyio
async def test_upsert_user_preserves_api_key_when_empty(monkeypatch) -> None:
    # Set up mock row from SELECT users query
    existing_row = {
        "token": "token-123",
        "audio_quota_mb": 512,
        "token_quota_total": 100,
        "token_quota_used": 10,
        "quota_note": "note",
        "llm_config": '{"provider": "openai", "model": "gpt-4", "api_key": "secret-key-123"}',
        "enabled": True,
        "metadata": '{"foo": "bar"}',
        "agent_id": "agent-001",
    }
    
    pool = FakePool(fetchrow=existing_row)
    repo = VoicePostgresRepository(pool=pool)
    
    # Mock self.audit & self.ensure_user_dmx_llm & get_agent
    async def mock_audit(*args, **kwargs): pass
    async def mock_ensure_user_dmx_llm(*args, **kwargs): pass
    async def mock_get_agent(*args, **kwargs): return MagicMock()
    
    monkeypatch.setattr(repo, "audit", mock_audit)
    monkeypatch.setattr(repo, "ensure_user_dmx_llm", mock_ensure_user_dmx_llm)
    monkeypatch.setattr(repo, "get_agent", mock_get_agent)

    # Populates _auth_cache
    repo._auth_cache = {"dev-1": (existing_row, MagicMock(), 9999.0)}
    
    # Payload with empty api_key (meaning "keep existing")
    payload = {
        "user_id": "user-001",
        "llm_config": {
            "provider": "openai",
            "model": "deepseek-chat",
            "api_key": ""
        }
    }
    
    await repo.upsert_user(payload)
    
    # Verify that the cache was cleared
    assert len(repo._auth_cache) == 0
    
    # Verify the SQL execute parameters
    execute_calls = [c for c in pool.executed_queries if "INSERT INTO users" in c[0]]
    assert len(execute_calls) == 1
    insert_sql, insert_args = execute_calls[0]
    
    # The 7th parameter (index 6) is the JSON configuration
    # (user_id, token, audio_quota_mb, token_quota_total, token_quota_used, quota_note, llm_config, ...)
    import json
    saved_llm = json.loads(insert_args[6])
    assert saved_llm["model"] == "deepseek-chat"
    # It must have preserved the api_key!
    assert saved_llm["api_key"] == "secret-key-123"
