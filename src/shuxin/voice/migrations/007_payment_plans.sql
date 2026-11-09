CREATE TABLE IF NOT EXISTS payment_plans (
    plan_id text PRIMARY KEY,
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    amount_fen integer NOT NULL CHECK (amount_fen > 0),
    sort_order integer NOT NULL DEFAULT 0,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS payment_plans_enabled_sort_idx
    ON payment_plans (enabled, sort_order ASC, plan_id ASC);

CREATE TABLE IF NOT EXISTS platform_settings (
    key text PRIMARY KEY,
    value jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO platform_settings (key, value)
VALUES ('payment.credit_ratio', '{"ratio": 0.95}'::jsonb)
ON CONFLICT (key) DO NOTHING;

INSERT INTO payment_plans (plan_id, name, description, amount_fen, sort_order, enabled)
VALUES
    ('monthly', '月卡', '30 天充值档位', 2990, 10, true),
    ('quarterly', '季卡', '90 天充值档位', 7900, 20, true),
    ('yearly', '年卡', '365 天充值档位', 29900, 30, true)
ON CONFLICT (plan_id) DO NOTHING;

ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS pay_yuan numeric(12, 2);
ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS display_credited numeric(12, 2);
ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS dmx_credited numeric(12, 2);
ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS credit_ratio numeric(6, 4);
