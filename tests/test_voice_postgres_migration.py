from pathlib import Path


def test_voice_postgres_migration_defines_authoritative_tables() -> None:
    sql = Path("src/shuxin/voice/migrations/001_voice_postgres.sql").read_text(
        encoding="utf-8"
    )

    for table in [
        "users",
        "devices",
        "device_claim_codes",
        "device_bindings",
        "device_binding_events",
        "device_status",
        "wechat_sessions",
        "voice_sessions",
        "conversation_events",
        "audio_attachments",
        "shared_memory",
        "user_facts",
        "companion_state",
        "admin_audit_logs",
        "adapter_actions",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    assert "deleted_at timestamptz" in sql
    assert "WHERE deleted_at IS NULL" in sql
    assert "audio_attachments_user_created_idx" in sql
    assert "auth_mode text NOT NULL DEFAULT 'shared_secret'" in sql
    assert "device_secret_hash text" in sql
    assert "claim_code text NOT NULL DEFAULT ''" in sql
    assert "claim_code_hash text NOT NULL UNIQUE" in sql
    assert "device_claim_codes_claim_code_idx" in sql
    assert "token_quota_total bigint NOT NULL DEFAULT 0" in sql
    assert "token_quota_used bigint NOT NULL DEFAULT 0" in sql
    assert "quota_note text NOT NULL DEFAULT ''" in sql
    assert "llm_config jsonb NOT NULL DEFAULT '{}'::jsonb" in sql
    assert "session_token_hash text PRIMARY KEY" in sql
    assert "expires_at timestamptz NOT NULL" in sql
    assert "wechat_sessions_user_expires_idx" in sql


def test_voice_postgres_migration_uses_cursor_friendly_indexes() -> None:
    sql = Path("src/shuxin/voice/migrations/001_voice_postgres.sql").read_text(
        encoding="utf-8"
    )

    assert "ON users (created_at DESC, user_id)" in sql
    assert "ON devices (created_at DESC, device_id)" in sql
    assert "ON conversation_events (user_id, created_at DESC, event_id)" in sql


def test_voice_postgres_migration_enforces_binding_rules() -> None:
    sql = Path("src/shuxin/voice/migrations/001_voice_postgres.sql").read_text(
        encoding="utf-8"
    )

    assert "device_bindings_one_active_device_idx" in sql
    assert "WHERE status = 'active'" in sql
    assert "device_bindings_user_status_idx" in sql
    assert "device_claim_codes_active_hash_idx" in sql
    assert "SHUXIN_DEVICE_SHARED_SECRET" not in sql
