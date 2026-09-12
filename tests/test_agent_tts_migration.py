"""Migration SQL files for volcengine TTS and agents schema."""

from __future__ import annotations

from pathlib import Path


def test_tts_volcengine_migration_sql_exists() -> None:
    path = Path("src/shuxin/voice/migrations/004_devices_tts_volcengine_default.sql")
    text = path.read_text(encoding="utf-8")
    assert "volcengine-clone" in text
    assert "UPDATE devices" in text


def test_agents_migration_sql_exists() -> None:
    path = Path("src/shuxin/voice/migrations/005_agents.sql")
    text = path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS agents" in text
    assert "users.agent_id" in text or "agent_id" in text
    assert "'shuxin'" in text
