-- Migration: 014_move_quota_to_devices.sql

ALTER TABLE devices
    ADD COLUMN IF NOT EXISTS subscription_plan_id text REFERENCES miniapp_subscription_plans(plan_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS subscription_minutes_limit integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS subscription_minutes_used numeric(12, 4) NOT NULL DEFAULT 0.0000,
    ADD COLUMN IF NOT EXISTS subscription_expires_at timestamptz,
    ADD COLUMN IF NOT EXISTS fuel_minutes_balance numeric(12, 4) NOT NULL DEFAULT 0.0000,
    ADD COLUMN IF NOT EXISTS last_reset_month varchar(7) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS daily_allowance_date date,
    ADD COLUMN IF NOT EXISTS daily_allowance_seconds_used numeric(8, 2) NOT NULL DEFAULT 0.00;

ALTER TABLE payment_orders
    ADD COLUMN IF NOT EXISTS device_id text;
