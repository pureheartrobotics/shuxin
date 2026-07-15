from __future__ import annotations

from pathlib import Path


def test_mall_migration_exists() -> None:
    sql = Path("src/shuxin/voice/migrations/015_mall.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS mall_products" in sql
    assert "CREATE TABLE IF NOT EXISTS mall_skus" in sql
    assert "CREATE TABLE IF NOT EXISTS mall_cart_items" in sql
    assert "CREATE TABLE IF NOT EXISTS mall_addresses" in sql
    assert "CREATE TABLE IF NOT EXISTS mall_orders" in sql
    assert "CREATE TABLE IF NOT EXISTS mall_order_items" in sql


def test_mall_migration_separate_from_payment_orders() -> None:
    sql = Path("src/shuxin/voice/migrations/015_mall.sql").read_text(encoding="utf-8")
    assert "payment_orders" not in sql
