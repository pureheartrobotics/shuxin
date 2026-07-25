"""Isolated text-chat billing: LLM tokens → yuan → minutes (swappable)."""

from __future__ import annotations

from typing import Any, Mapping


DEFAULT_TEXT_BILLING: dict[str, float] = {
    "text_max_chars": 500,
    "llm_input_yuan_per_m_tokens": 0.85,
    "llm_output_yuan_per_m_tokens": 1.7,
    "llm_cache_yuan_per_m_tokens": 0.02,
    "yuan_to_minutes_rate": 1.0,
    # 中文手机输入保守估计，用于预估展示；后台 investor.text_billing 可改
    "chars_per_minute": 40.0,
}


def merge_text_billing_settings(raw: Mapping[str, Any] | None) -> dict[str, float]:
    out = dict(DEFAULT_TEXT_BILLING)
    if not raw:
        return out
    for key in out:
        if key in raw and raw[key] is not None:
            try:
                out[key] = float(raw[key])
            except (TypeError, ValueError):
                continue
    return out


def estimate_chars_to_prompt_tokens(text: str) -> int:
    """Rough CJK-aware estimate for pre-gate (not billed)."""
    n = len(text or "")
    # ~1.5 chars per token for Chinese-heavy input
    return max(1, int(n / 1.5) + 1)


def yuan_from_llm_usage(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cache_tokens: int = 0,
    settings: Mapping[str, Any] | None = None,
) -> float:
    cfg = merge_text_billing_settings(settings)
    pin = float(cfg["llm_input_yuan_per_m_tokens"])
    pout = float(cfg["llm_output_yuan_per_m_tokens"])
    pcache = float(cfg["llm_cache_yuan_per_m_tokens"])
    return (
        max(0, int(prompt_tokens)) * pin / 1_000_000.0
        + max(0, int(completion_tokens)) * pout / 1_000_000.0
        + max(0, int(cache_tokens)) * pcache / 1_000_000.0
    )


def minutes_from_yuan(yuan: float, settings: Mapping[str, Any] | None = None) -> float:
    cfg = merge_text_billing_settings(settings)
    rate = float(cfg["yuan_to_minutes_rate"]) or 1.0
    return max(0.0, float(yuan) * rate)


def minutes_from_llm_usage(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cache_tokens: int = 0,
    settings: Mapping[str, Any] | None = None,
) -> float:
    return minutes_from_yuan(
        yuan_from_llm_usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_tokens=cache_tokens,
            settings=settings,
        ),
        settings=settings,
    )


def estimate_minutes_for_text(
    text: str,
    *,
    max_completion_tokens: int = 384,
    settings: Mapping[str, Any] | None = None,
) -> float:
    """Upper-bound gate before calling the LLM (token path, conservative)."""
    cfg = merge_text_billing_settings(settings)
    prompt = estimate_chars_to_prompt_tokens(text)
    return minutes_from_llm_usage(
        prompt_tokens=prompt,
        completion_tokens=int(max_completion_tokens),
        cache_tokens=0,
        settings=cfg,
    )


def estimate_minutes_by_typing_speed(
    text: str,
    *,
    settings: Mapping[str, Any] | None = None,
) -> float:
    """展示用预估：按可配中文打字速度（字/分钟）换算。"""
    cfg = merge_text_billing_settings(settings)
    cpm = float(cfg.get("chars_per_minute") or 40.0)
    if cpm <= 0:
        cpm = 40.0
    n = len(text or "")
    return max(0.0, float(n) / cpm)


def text_max_chars(settings: Mapping[str, Any] | None = None) -> int:
    return int(merge_text_billing_settings(settings)["text_max_chars"])
