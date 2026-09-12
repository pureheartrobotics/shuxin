-- 016: 舒心号、通讯录、通话信令、防骚扰
-- 用户引用列须为 TEXT，与 users.user_id 对齐

ALTER TABLE users ADD COLUMN IF NOT EXISTS shuxin_handle VARCHAR(32);
CREATE UNIQUE INDEX IF NOT EXISTS users_shuxin_handle_idx
    ON users (shuxin_handle) WHERE shuxin_handle IS NOT NULL AND shuxin_handle <> '';

CREATE TABLE IF NOT EXISTS user_contacts (
    contact_id BIGSERIAL PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    nickname VARCHAR(64) NOT NULL,
    target_handle VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_user_id, nickname)
);

CREATE TABLE IF NOT EXISTS user_blocklist (
    block_id BIGSERIAL PRIMARY KEY,
    blocker_user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    blocked_handle VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (blocker_user_id, blocked_handle)
);

CREATE TABLE IF NOT EXISTS user_dnd_settings (
    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    dnd_start TIME,
    dnd_end TIME,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS voice_calls (
    call_id VARCHAR(64) PRIMARY KEY,
    caller_user_id TEXT NOT NULL REFERENCES users(user_id),
    caller_device_id VARCHAR(64) NOT NULL,
    callee_user_id TEXT NOT NULL REFERENCES users(user_id),
    callee_handle VARCHAR(32) NOT NULL,
    answered_device_id VARCHAR(64),
    state VARCHAR(16) NOT NULL DEFAULT 'ringing',
    room_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    connected_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS voice_calls_callee_state_idx
    ON voice_calls (callee_user_id, state);
