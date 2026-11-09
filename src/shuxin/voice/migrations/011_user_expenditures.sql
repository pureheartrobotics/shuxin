CREATE TABLE IF NOT EXISTS user_expenditures (
    expenditure_id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    type text NOT NULL CHECK (type IN ('stt', 'tts', 'llm')),
    model text NOT NULL DEFAULT '',
    usage_amount double precision NOT NULL DEFAULT 0,
    cost_yuan numeric(12, 6) NOT NULL DEFAULT 0.000000,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_expenditures_user_date
    ON user_expenditures (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_expenditures_date
    ON user_expenditures (created_at DESC);

-- 初始化默认计费价格配置，单价单位为“元/最小计费单位”
-- STT为每秒单价，TTS为每字单价，LLM为每token单价
INSERT INTO platform_settings (key, value)
VALUES
    ('pricing.stt', '{"tencent-realtime": 0.000200, "default": 0.000200}'::jsonb),
    ('pricing.tts', '{"volcengine-clone": 0.000020, "default": 0.000020}'::jsonb),
    ('pricing.llm', '{"deepseek-chat": 0.000002, "default": 0.000002}'::jsonb)
ON CONFLICT (key) DO NOTHING;
