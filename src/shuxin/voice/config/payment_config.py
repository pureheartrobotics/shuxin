from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_CREDIT_RATIO = 0.95
DISPLAY_BALANCE_METADATA_KEY = "display_balance_yuan"
PAYMENT_CREDIT_RATIO_SETTING_KEY = "payment.credit_ratio"


@dataclass(frozen=True)
class PaymentPlan:
    id: str
    name: str
    amount_fen: int
    add_yuan: float = 0.0
    duration_days: int = 0
    description: str = ""
    enabled: bool = True
    sort_order: int = 0

    def to_public_dict(self, *, credit_ratio: float | None = None) -> dict[str, object]:
        pay_yuan = round(self.amount_fen / 100, 2)
        return {
            "id": self.id,
            "plan_id": self.id,
            "name": self.name,
            "description": self.description,
            "amount_fen": self.amount_fen,
            "amount_yuan": pay_yuan,
            "add_yuan": pay_yuan,
            "duration_days": 0,
        }

    def to_admin_dict(self) -> dict[str, object]:
        data = self.to_public_dict()
        data["enabled"] = self.enabled
        data["sort_order"] = self.sort_order
        return data


def normalize_credit_ratio(raw: float) -> float:
    ratio = float(raw)
    if ratio <= 0 or ratio > 1:
        raise ValueError("credit_ratio must be between 0 and 1")
    return round(ratio, 4)


def compute_payment_credits(amount_fen: int, credit_ratio: float) -> tuple[float, float, float]:
    pay_yuan = round(int(amount_fen) / 100, 2)
    ratio = normalize_credit_ratio(credit_ratio)
    display_credit = pay_yuan
    dmx_credit = round(pay_yuan * ratio, 4)
    return pay_yuan, display_credit, dmx_credit


DEFAULT_PAYMENT_PLANS: tuple[PaymentPlan, ...] = (
    PaymentPlan(
        id="plan_10",
        name="10 元",
        description="充值 10 元",
        amount_fen=1000,
        add_yuan=10.0,
    ),
    PaymentPlan(
        id="plan_30",
        name="30 元",
        description="充值 30 元",
        amount_fen=3000,
        add_yuan=30.0,
    ),
    PaymentPlan(
        id="plan_50",
        name="50 元",
        description="充值 50 元",
        amount_fen=5000,
        add_yuan=50.0,
    ),
)


def _parse_plan(raw: dict[str, object]) -> PaymentPlan:
    plan_id = str(raw.get("id") or raw.get("plan_id") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not plan_id or not name:
        raise ValueError("payment plan requires id and name")
    amount_fen = int(raw.get("amount_fen") or 0)
    if amount_fen <= 0:
        raise ValueError(f"payment plan {plan_id} must have positive amount_fen")
    add_yuan = float(raw.get("add_yuan") or round(amount_fen / 100, 2))
    duration_days = int(raw.get("duration_days") or 0)
    description = str(raw.get("description") or "").strip()
    enabled = bool(raw.get("enabled", True))
    sort_order = int(raw.get("sort_order") or 0)
    return PaymentPlan(
        id=plan_id,
        name=name,
        amount_fen=amount_fen,
        add_yuan=add_yuan,
        duration_days=max(duration_days, 0),
        description=description,
        enabled=enabled,
        sort_order=sort_order,
    )


def plan_from_row(row: Any) -> PaymentPlan:
    pay_yuan = round(int(row["amount_fen"]) / 100, 2)
    return PaymentPlan(
        id=str(row["plan_id"]),
        name=str(row["name"]),
        amount_fen=int(row["amount_fen"]),
        add_yuan=pay_yuan,
        duration_days=0,
        description=str(row["description"] or ""),
        enabled=bool(row["enabled"]),
        sort_order=int(row["sort_order"] or 0),
    )


def load_payment_plans() -> list[PaymentPlan]:
    env_json = os.environ.get("SHUXIN_PAYMENT_PLANS", "").strip()
    if env_json:
        payload = json.loads(env_json)
        if not isinstance(payload, list):
            raise ValueError("SHUXIN_PAYMENT_PLANS must be a JSON array")
        return [_parse_plan(item) for item in payload if isinstance(item, dict)]

    config_path = Path(
        os.environ.get("SHUXIN_PAYMENT_PLANS_FILE", "/app/data/payment_plans.json")
    )
    if config_path.is_file():
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"{config_path} must contain a JSON array")
        return [_parse_plan(item) for item in payload if isinstance(item, dict)]

    return list(DEFAULT_PAYMENT_PLANS)


def get_payment_plan(plan_id: str) -> PaymentPlan:
    selected = str(plan_id or "").strip()
    for plan in load_payment_plans():
        if plan.id == selected:
            return plan
    raise ValueError(f"unknown payment plan: {selected}")


def list_payment_plan_dicts() -> list[dict[str, object]]:
    return [plan.to_public_dict() for plan in load_payment_plans()]


def payment_plans_snapshot() -> list[dict[str, object]]:
    return [asdict(plan) for plan in load_payment_plans()]
