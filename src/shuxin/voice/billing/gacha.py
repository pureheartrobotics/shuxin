"""Gacha weighted sampling (pure, testable)."""

from __future__ import annotations

import random
from typing import Any, Mapping, Sequence

from shuxin.core.identity import VALID_MBTI_TYPES


DEFAULT_GACHA: dict[str, Any] = {
    "paid_draw_price_yuan": 9.9,
    "free_draws_per_user": 3,
    "weights": {},
}


def merge_gacha_settings(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULT_GACHA)
    if not raw:
        return out
    if "paid_draw_price_yuan" in raw and raw["paid_draw_price_yuan"] is not None:
        try:
            out["paid_draw_price_yuan"] = float(raw["paid_draw_price_yuan"])
        except (TypeError, ValueError):
            pass
    if "free_draws_per_user" in raw and raw["free_draws_per_user"] is not None:
        try:
            out["free_draws_per_user"] = int(raw["free_draws_per_user"])
        except (TypeError, ValueError):
            pass
    weights = raw.get("weights")
    if isinstance(weights, dict):
        cleaned: dict[str, float] = {}
        for k, v in weights.items():
            key = str(k).strip().upper()
            if key not in VALID_MBTI_TYPES:
                continue
            try:
                w = float(v)
            except (TypeError, ValueError):
                continue
            if w > 0:
                cleaned[key] = w
        out["weights"] = cleaned
    return out


def build_weight_table(settings: Mapping[str, Any] | None = None) -> dict[str, float]:
    """Explicit weights for listed types; remaining types share equal residual mass."""
    cfg = merge_gacha_settings(settings)
    explicit: dict[str, float] = dict(cfg.get("weights") or {})
    types = sorted(VALID_MBTI_TYPES)
    if not types:
        return {"ENFP": 1.0}
    if not explicit:
        return {t: 1.0 for t in types}
    listed_sum = sum(explicit.values())
    unlisted = [t for t in types if t not in explicit]
    table = dict(explicit)
    if unlisted:
        # Give unlisted the same total mass as listed average * count, or 1 each
        avg = (listed_sum / len(explicit)) if explicit else 1.0
        for t in unlisted:
            table[t] = avg
    return table


def weighted_pick_mbti(
    settings: Mapping[str, Any] | None = None,
    *,
    rng: random.Random | None = None,
) -> str:
    table = build_weight_table(settings)
    items: Sequence[tuple[str, float]] = list(table.items())
    population = [k for k, _ in items]
    weights = [w for _, w in items]
    picker = rng or random
    return picker.choices(population, weights=weights, k=1)[0]
