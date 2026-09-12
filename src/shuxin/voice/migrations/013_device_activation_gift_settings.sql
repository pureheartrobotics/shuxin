-- 系统低保表扩展，添加设备首次激活赠送配置
ALTER TABLE miniapp_allowance_settings
    ADD COLUMN IF NOT EXISTS gift_subscription_plan_id text REFERENCES miniapp_subscription_plans(plan_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS gift_duration_months integer NOT NULL DEFAULT 0;
