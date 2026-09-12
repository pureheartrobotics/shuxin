CREATE TABLE IF NOT EXISTS users (
    user_id text PRIMARY KEY,
    token text NOT NULL DEFAULT '',
    audio_quota_mb integer NOT NULL DEFAULT 512,
    token_quota_total bigint NOT NULL DEFAULT 0,
    token_quota_used bigint NOT NULL DEFAULT 0,
    quota_note text NOT NULL DEFAULT '',
    llm_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled boolean NOT NULL DEFAULT true,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS token_quota_total bigint NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS token_quota_used bigint NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS quota_note text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS llm_config jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS devices (
    device_id text PRIMARY KEY,
    auth_mode text NOT NULL DEFAULT 'shared_secret'
        CHECK (auth_mode IN ('shared_secret', 'per_device_secret')),
    device_secret_hash text,
    status text NOT NULL DEFAULT 'provisioned'
        CHECK (status IN ('provisioned', 'bound', 'disabled')),
    stt_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    tts_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    llm_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled boolean NOT NULL DEFAULT true,
    note text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

ALTER TABLE devices
    ADD COLUMN IF NOT EXISTS auth_mode text NOT NULL DEFAULT 'shared_secret',
    ADD COLUMN IF NOT EXISTS device_secret_hash text,
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'provisioned';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'devices_auth_mode_check'
    ) THEN
        ALTER TABLE devices
            ADD CONSTRAINT devices_auth_mode_check
            CHECK (auth_mode IN ('shared_secret', 'per_device_secret'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'devices_status_check'
    ) THEN
        ALTER TABLE devices
            ADD CONSTRAINT devices_status_check
            CHECK (status IN ('provisioned', 'bound', 'disabled'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS device_claim_codes (
    claim_code_id text PRIMARY KEY,
    device_id text NOT NULL REFERENCES devices(device_id),
    claim_code text NOT NULL DEFAULT '',
    claim_code_hash text NOT NULL UNIQUE,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'claimed', 'revoked')),
    claimed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE device_claim_codes
    ADD COLUMN IF NOT EXISTS claim_code text NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS device_bindings (
    binding_id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    device_id text NOT NULL REFERENCES devices(device_id),
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'unbound')),
    bound_at timestamptz NOT NULL DEFAULT now(),
    unbound_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS device_binding_events (
    event_id text PRIMARY KEY,
    user_id text REFERENCES users(user_id),
    device_id text REFERENCES devices(device_id),
    event_type text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS device_status (
    device_id text PRIMARY KEY REFERENCES devices(device_id),
    online boolean NOT NULL DEFAULT false,
    last_seen timestamptz,
    current_session_id text NOT NULL DEFAULT '',
    last_error text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wechat_sessions (
    session_token_hash text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS voice_sessions (
    session_id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    device_id text NOT NULL REFERENCES devices(device_id),
    client_id text NOT NULL DEFAULT '',
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS conversation_events (
    event_id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    device_id text NOT NULL REFERENCES devices(device_id),
    session_id text NOT NULL REFERENCES voice_sessions(session_id),
    turn_id text NOT NULL,
    event_type text NOT NULL,
    user_text text NOT NULL DEFAULT '',
    reply_text text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS audio_attachments (
    attachment_id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    device_id text NOT NULL REFERENCES devices(device_id),
    session_id text NOT NULL REFERENCES voice_sessions(session_id),
    turn_id text NOT NULL,
    kind text NOT NULL,
    path text NOT NULL,
    media_type text NOT NULL,
    size_bytes bigint NOT NULL DEFAULT 0,
    sha256 text NOT NULL DEFAULT '',
    compressed boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS shared_memory (
    user_id text PRIMARY KEY REFERENCES users(user_id),
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_facts (
    fact_id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    fact_key text NOT NULL,
    fact_value text NOT NULL,
    category text NOT NULL DEFAULT 'general',
    confidence double precision NOT NULL DEFAULT 1.0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS companion_state (
    user_id text PRIMARY KEY REFERENCES users(user_id),
    state jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS admin_audit_logs (
    audit_id text PRIMARY KEY,
    action text NOT NULL,
    target_type text NOT NULL,
    target_id text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS adapter_actions (
    action_id text PRIMARY KEY,
    adapter_name text NOT NULL,
    action text NOT NULL,
    status text NOT NULL,
    request_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    result_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    error text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS users_active_created_idx
    ON users (created_at DESC, user_id)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS devices_active_created_idx
    ON devices (created_at DESC, device_id)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS device_claim_codes_device_id_idx
    ON device_claim_codes (device_id);

CREATE INDEX IF NOT EXISTS device_claim_codes_active_hash_idx
    ON device_claim_codes (claim_code_hash)
    WHERE status = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS device_claim_codes_claim_code_idx
    ON device_claim_codes (claim_code)
    WHERE claim_code <> '';

CREATE UNIQUE INDEX IF NOT EXISTS device_bindings_one_active_device_idx
    ON device_bindings (device_id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS device_bindings_user_status_idx
    ON device_bindings (user_id, status);

CREATE INDEX IF NOT EXISTS device_binding_events_device_created_idx
    ON device_binding_events (device_id, created_at DESC);

CREATE INDEX IF NOT EXISTS device_status_last_seen_idx
    ON device_status (last_seen DESC);

CREATE INDEX IF NOT EXISTS wechat_sessions_user_expires_idx
    ON wechat_sessions (user_id, expires_at DESC);

CREATE INDEX IF NOT EXISTS voice_sessions_user_created_idx
    ON voice_sessions (user_id, started_at DESC, session_id);

CREATE INDEX IF NOT EXISTS conversation_events_user_created_idx
    ON conversation_events (user_id, created_at DESC, event_id)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS conversation_events_device_created_idx
    ON conversation_events (device_id, created_at DESC, event_id)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS audio_attachments_user_created_idx
    ON audio_attachments (user_id, created_at DESC, attachment_id)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS user_facts_active_user_key_idx
    ON user_facts (user_id, fact_key)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS admin_audit_logs_created_idx
    ON admin_audit_logs (created_at DESC, audit_id);
