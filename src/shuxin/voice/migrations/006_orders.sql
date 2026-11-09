CREATE TABLE IF NOT EXISTS payment_orders (
    order_id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    out_trade_no text NOT NULL UNIQUE,
    plan_id text NOT NULL,
    plan_name text NOT NULL DEFAULT '',
    amount_fen integer NOT NULL CHECK (amount_fen > 0),
    add_yuan numeric(12, 2) NOT NULL CHECK (add_yuan > 0),
    duration_days integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'pending',
    wx_transaction_id text NOT NULL DEFAULT '',
    wx_prepay_id text NOT NULL DEFAULT '',
    notify_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    paid_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS payment_orders_user_created_idx
    ON payment_orders (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS payment_orders_status_created_idx
    ON payment_orders (status, created_at DESC);
