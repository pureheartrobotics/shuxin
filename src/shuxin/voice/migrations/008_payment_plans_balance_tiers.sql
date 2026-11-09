UPDATE payment_plans
SET enabled = false, updated_at = now()
WHERE plan_id IN ('monthly', 'quarterly', 'yearly');

INSERT INTO payment_plans (plan_id, name, description, amount_fen, sort_order, enabled)
VALUES
    ('plan_10', '10 元', '充值 10 元', 1000, 10, true),
    ('plan_30', '30 元', '充值 30 元', 3000, 20, true),
    ('plan_50', '50 元', '充值 50 元', 5000, 30, true)
ON CONFLICT (plan_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    amount_fen = EXCLUDED.amount_fen,
    sort_order = EXCLUDED.sort_order,
    enabled = EXCLUDED.enabled,
    updated_at = now();
