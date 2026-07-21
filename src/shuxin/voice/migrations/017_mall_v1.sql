-- Mall V1: shipping carrier + pending order expiry support (stock release via app logic)

ALTER TABLE mall_orders
    ADD COLUMN IF NOT EXISTS shipping_carrier text NOT NULL DEFAULT '';
