-- Investor miniprogram: software companions + gacha (disposable line)

CREATE TABLE IF NOT EXISTS user_companions (
    companion_id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    mbti text NOT NULL,
    display_name text NOT NULL DEFAULT '',
    source text NOT NULL DEFAULT 'free_gacha'
        CHECK (source IN ('free_gacha', 'paid_gacha')),
    payment_id text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS user_companions_user_created_idx
    ON user_companions (user_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS user_companions_payment_unique_idx
    ON user_companions (payment_id)
    WHERE payment_id <> '';

CREATE TABLE IF NOT EXISTS companion_text_turns (
    turn_id bigserial PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    companion_id text NOT NULL REFERENCES user_companions(companion_id) ON DELETE CASCADE,
    prompt_tokens integer NOT NULL DEFAULT 0,
    completion_tokens integer NOT NULL DEFAULT 0,
    cache_tokens integer NOT NULL DEFAULT 0,
    cost_minutes numeric(12, 6) NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS companion_text_turns_user_created_idx
    ON companion_text_turns (user_id, created_at DESC);

INSERT INTO platform_settings (key, value, updated_at)
VALUES (
    'investor.gacha',
    '{
        "paid_draw_price_yuan": 9.9,
        "free_draws_per_user": 3,
        "weights": {}
    }'::jsonb,
    now()
)
ON CONFLICT (key) DO NOTHING;

INSERT INTO platform_settings (key, value, updated_at)
VALUES (
    'investor.text_billing',
    '{
        "text_max_chars": 500,
        "llm_input_yuan_per_m_tokens": 0.85,
        "llm_output_yuan_per_m_tokens": 1.7,
        "llm_cache_yuan_per_m_tokens": 0.02,
        "yuan_to_minutes_rate": 1.0
    }'::jsonb,
    now()
)
ON CONFLICT (key) DO NOTHING;
