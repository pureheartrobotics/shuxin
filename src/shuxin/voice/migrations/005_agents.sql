CREATE TABLE IF NOT EXISTS agents (
    agent_id        text PRIMARY KEY,
    display_name    text NOT NULL DEFAULT '',
    voice_type      text NOT NULL DEFAULT '',
    cluster         text NOT NULL DEFAULT 'volcano_icl',
    speed_ratio     double precision NOT NULL DEFAULT 1.0,
    encoding        text NOT NULL DEFAULT 'mp3',
    uid             text NOT NULL DEFAULT '',
    soul_path       text NOT NULL DEFAULT '',
    initial_state   jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled         boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);

INSERT INTO agents (
    agent_id, display_name, voice_type, cluster, speed_ratio, encoding, uid, soul_path, metadata
)
VALUES (
    'shuxin',
    '舒心',
    '',
    'volcano_icl',
    1.0,
    'mp3',
    'shuxin',
    'data/agents/shuxin/SOUL.md',
    '{"default_mbti":"INFJ"}'::jsonb
)
ON CONFLICT (agent_id) DO NOTHING;

ALTER TABLE users ADD COLUMN IF NOT EXISTS agent_id text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_agent_id_fkey'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_agent_id_fkey
            FOREIGN KEY (agent_id) REFERENCES agents(agent_id);
    END IF;
END $$;

UPDATE users
SET agent_id = 'shuxin'
WHERE agent_id IS NULL AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS agents_active_idx
    ON agents (agent_id)
    WHERE deleted_at IS NULL AND enabled = true;
