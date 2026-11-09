CREATE TABLE IF NOT EXISTS mall_products (
    product_id text PRIMARY KEY,
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    cover_url text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'on_sale'
        CHECK (status IN ('on_sale', 'off_sale')),
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mall_skus (
    sku_id text PRIMARY KEY,
    product_id text NOT NULL REFERENCES mall_products(product_id),
    name text NOT NULL DEFAULT '',
    price_fen integer NOT NULL CHECK (price_fen > 0),
    stock integer NOT NULL DEFAULT 0 CHECK (stock >= 0),
    attrs jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS mall_skus_product_idx ON mall_skus (product_id);

CREATE TABLE IF NOT EXISTS mall_cart_items (
    cart_item_id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    sku_id text NOT NULL REFERENCES mall_skus(sku_id),
    quantity integer NOT NULL DEFAULT 1 CHECK (quantity > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, sku_id)
);

CREATE INDEX IF NOT EXISTS mall_cart_items_user_idx ON mall_cart_items (user_id);

CREATE TABLE IF NOT EXISTS mall_addresses (
    address_id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    receiver_name text NOT NULL,
    receiver_phone text NOT NULL,
    province text NOT NULL DEFAULT '',
    city text NOT NULL DEFAULT '',
    district text NOT NULL DEFAULT '',
    detail text NOT NULL DEFAULT '',
    is_default boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS mall_addresses_user_idx ON mall_addresses (user_id);

CREATE TABLE IF NOT EXISTS mall_orders (
    order_id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(user_id),
    out_trade_no text NOT NULL UNIQUE,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'paid', 'shipped', 'completed', 'cancelled')),
    total_fen integer NOT NULL CHECK (total_fen > 0),
    address_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    wx_transaction_id text NOT NULL DEFAULT '',
    wx_prepay_id text NOT NULL DEFAULT '',
    notify_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    shipping_no text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    paid_at timestamptz,
    shipped_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS mall_orders_user_created_idx
    ON mall_orders (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS mall_orders_status_idx
    ON mall_orders (status, created_at DESC);

CREATE TABLE IF NOT EXISTS mall_order_items (
    order_item_id text PRIMARY KEY,
    order_id text NOT NULL REFERENCES mall_orders(order_id) ON DELETE CASCADE,
    product_id text NOT NULL,
    sku_id text NOT NULL,
    product_name text NOT NULL,
    sku_name text NOT NULL DEFAULT '',
    price_fen integer NOT NULL,
    quantity integer NOT NULL CHECK (quantity > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS mall_order_items_order_idx ON mall_order_items (order_id);
