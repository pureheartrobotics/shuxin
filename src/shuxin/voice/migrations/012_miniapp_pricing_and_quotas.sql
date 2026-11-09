-- 订阅套餐表
CREATE TABLE IF NOT EXISTS miniapp_subscription_plans (
    plan_id           text PRIMARY KEY,
    name              text NOT NULL,
    amount_fen        integer NOT NULL CHECK (amount_fen >= 0),
    duration_minutes  integer NOT NULL CHECK (duration_minutes > 0),
    description       text NOT NULL DEFAULT '',
    sort_order        integer NOT NULL DEFAULT 0,
    enabled           boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sub_plans_sort ON miniapp_subscription_plans (enabled, sort_order ASC, plan_id ASC);

-- 弹性加油包表
CREATE TABLE IF NOT EXISTS miniapp_fuel_packages (
    package_id        text PRIMARY KEY,
    name              text NOT NULL,
    amount_fen        integer NOT NULL CHECK (amount_fen >= 0),
    duration_minutes  integer NOT NULL CHECK (duration_minutes > 0),
    description       text NOT NULL DEFAULT '',
    sort_order        integer NOT NULL DEFAULT 0,
    enabled           boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fuel_packs_sort ON miniapp_fuel_packages (enabled, sort_order ASC, package_id ASC);

-- 系统低保设定表 (单行强制约束)
CREATE TABLE IF NOT EXISTS miniapp_allowance_settings (
    id                 integer PRIMARY KEY CHECK (id = 1),
    daily_free_minutes numeric(6, 2) NOT NULL DEFAULT 1.50,
    enabled            boolean NOT NULL DEFAULT true,
    updated_at         timestamptz NOT NULL DEFAULT now()
);

-- 插入初始化默认低保数据
INSERT INTO miniapp_allowance_settings (id, daily_free_minutes, enabled)
VALUES (1, 1.50, true)
ON CONFLICT (id) DO NOTHING;

-- 用户表列扩展
ALTER TABLE users 
    ADD COLUMN IF NOT EXISTS subscription_plan_id text REFERENCES miniapp_subscription_plans(plan_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS subscription_minutes_limit integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS subscription_minutes_used numeric(12, 4) NOT NULL DEFAULT 0.0000,
    ADD COLUMN IF NOT EXISTS subscription_expires_at timestamptz,
    ADD COLUMN IF NOT EXISTS fuel_minutes_balance numeric(12, 4) NOT NULL DEFAULT 0.0000,
    ADD COLUMN IF NOT EXISTS last_reset_month varchar(7) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS daily_allowance_date date,
    ADD COLUMN IF NOT EXISTS daily_allowance_seconds_used numeric(8, 2) NOT NULL DEFAULT 0.00;
