from __future__ import annotations

from pathlib import Path


def test_payment_orders_migration_exists() -> None:
    sql = Path("src/shuxin/voice/migrations/006_orders.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS payment_orders" in sql
    assert "out_trade_no text NOT NULL UNIQUE" in sql


def test_payment_plans_migration_exists() -> None:
    sql = Path("src/shuxin/voice/migrations/007_payment_plans.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS payment_plans" in sql
    assert "platform_settings" in sql
    assert "display_credited" in sql
    assert "payment.credit_ratio" in sql


def test_payment_plans_balance_tiers_migration_exists() -> None:
    sql = Path("src/shuxin/voice/migrations/008_payment_plans_balance_tiers.sql").read_text(
        encoding="utf-8"
    )
    assert "plan_10" in sql
    assert "plan_30" in sql
    assert "plan_50" in sql
    assert "monthly" in sql
