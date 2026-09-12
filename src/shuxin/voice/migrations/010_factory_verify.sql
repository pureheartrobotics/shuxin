-- 工厂验收日志表
-- 每次 QA 扫码触发验收，无论 PASS/FAIL 均写一条记录
CREATE TABLE IF NOT EXISTS factory_verify_logs (
    verify_id       text PRIMARY KEY,
    claim_code      text NOT NULL DEFAULT '',
    device_id       text NOT NULL DEFAULT '',
    operator_user   text NOT NULL DEFAULT '',
    result          text NOT NULL DEFAULT 'FAIL'
        CHECK (result IN ('PASS', 'FAIL')),
    fail_reason     text NOT NULL DEFAULT '',
    verified_at     timestamptz NOT NULL DEFAULT now(),
    meta            jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- 加速按设备、按操作员查询
CREATE INDEX IF NOT EXISTS factory_verify_logs_device_idx
    ON factory_verify_logs (device_id, verified_at DESC);

CREATE INDEX IF NOT EXISTS factory_verify_logs_operator_idx
    ON factory_verify_logs (operator_user, verified_at DESC);

-- users.metadata 已有 JSONB 列，通过 metadata->>'factory_role' = 'true' 标记 QA 账号
-- 无需新增列
