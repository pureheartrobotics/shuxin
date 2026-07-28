"""Shared helpers for soft companion text chat (sync + stream)."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from shuxin.core.memory import MemoryEntry
from shuxin.voice.age_consent import AGE_CONSENT_VERSION, age_consent_ok
from shuxin.voice.billing.text_billing import (
    estimate_chars_to_prompt_tokens,
    estimate_minutes_by_typing_speed,
    estimate_minutes_for_text,
    minutes_from_llm_usage,
    text_max_chars,
)
from shuxin.voice.config.config import merge_llm_device_config
from shuxin.voice.integrations.dmx_client import default_platform_llm_config
from shuxin.voice.service import VoiceService, _voice_max_history

logger = logging.getLogger("shuxin.voice.api.companions")


class TextChatPrepError(Exception):
    def __init__(self, payload: dict, status_code: int):
        super().__init__(str(payload.get("detail") or payload.get("error") or "error"))
        self.payload = payload
        self.status_code = status_code


async def _assert_age_consent(repo: Any, user_id: str) -> None:
    checker = getattr(repo, "get_user_age_consent_meta", None)
    if checker is None:
        return
    meta = await checker(user_id)
    if age_consent_ok(meta):
        return
    raise TextChatPrepError(
        {
            "error": "age_consent_required",
            "detail": "请先确认已年满 18 周岁",
            "age_consent_version": AGE_CONSENT_VERSION,
        },
        403,
    )


def _seed_agent_short_term(agent: Any, turns: List[Dict[str, Any]]) -> None:
    """把历史回合注入 short_term，不触发 Mem0 写入。"""
    memory = getattr(agent, "memory", None)
    if memory is None:
        return
    max_n = _voice_max_history()
    selected = list(turns)[-max_n:]
    now = datetime.now().isoformat()
    for turn in selected:
        user_text = str(turn.get("user_text") or "").strip()
        reply_text = str(turn.get("reply_text") or "").strip()
        if user_text:
            memory.short_term.append(
                MemoryEntry(role="user", content=user_text, timestamp=now)
            )
        if reply_text:
            memory.short_term.append(
                MemoryEntry(role="assistant", content=reply_text, timestamp=now)
            )
        if len(memory.short_term) > memory.max_short_term:
            memory.short_term = memory.short_term[-memory.max_short_term :]


async def prepare_text_chat(repo, *, session_token: str, companion_id: str, text: str) -> Dict[str, Any]:
    """Validate quota / LLM and build an initialized Agent. Raises TextChatPrepError or ValueError/PermissionError."""
    companion_id = str(companion_id or "").strip()
    text = str(text or "").strip()
    if not companion_id:
        raise ValueError("companion_id is required")
    if not text:
        raise ValueError("text is required")

    user_id = await repo.companions._user_id_from_session(session_token)
    await _assert_age_consent(repo, user_id)
    companion = await repo.companions.get_companion_for_user(
        user_id=user_id, companion_id=companion_id
    )
    billing_settings = await repo.companions.get_text_billing_settings()
    max_chars = text_max_chars(billing_settings)
    if len(text) > max_chars:
        raise ValueError("text exceeds {} characters".format(max_chars))

    soft = await repo.companions.ensure_soft_device(user_id=user_id)
    soft_id = soft["device_id"]
    estimate_token = estimate_minutes_for_text(text, settings=billing_settings)
    estimate_typing = estimate_minutes_by_typing_speed(text, settings=billing_settings)
    estimate = max(estimate_token, estimate_typing)

    try:
        await repo.assert_device_quota_available(soft_id)
    except Exception as exc:
        quota_snap: dict = {}
        try:
            quota_snap = await repo.get_device_quota(soft_id)
        except Exception:
            quota_snap = {}
        daily_left = float(quota_snap.get("daily_allowance_left") or 0)
        sub_left = float(quota_snap.get("subscription_minutes_left") or 0)
        fuel_left = float(quota_snap.get("fuel_minutes_left") or 0)
        reason = (
            "daily_allowance_exhausted"
            if daily_left <= 0 and sub_left <= 0 and fuel_left <= 0
            else "quota_exhausted"
        )
        raise TextChatPrepError(
            {
                "error": "quota_exhausted",
                "error_kind": reason,
                "detail": str(exc),
                "quota": {
                    "remain_yuan": float(quota_snap.get("remain_yuan") or 0),
                    "exhausted": True,
                    "daily_allowance_left": daily_left,
                    "subscription_minutes_left": sub_left,
                    "fuel_minutes_left": fuel_left,
                },
            },
            402,
        )

    device = await repo.get_device(soft_id)
    if hasattr(repo, "ensure_user_dmx_llm"):
        try:
            await repo.ensure_user_dmx_llm(user_id)
        except Exception as exc:
            logger.info("ensure_user_dmx_llm skipped: %s", exc)
    user_settings = await repo.get_user_settings(user_id)
    device.llm = merge_llm_device_config(device.llm, default_platform_llm_config())
    if user_settings and user_settings.llm_config:
        device.llm = merge_llm_device_config(device.llm, user_settings.llm_config)
    if not str(device.llm.api_key or "").strip():
        from shuxin.core.config import Config

        fallback = Config.load()
        if fallback.llm.api_key:
            device.llm = merge_llm_device_config(
                device.llm,
                {
                    "provider": fallback.llm.provider,
                    "model": fallback.llm.model,
                    "base_url": fallback.llm.base_url,
                    "api_key": fallback.llm.api_key,
                },
            )
    if not str(device.llm.api_key or "").strip():
        from shuxin.voice.integrations.dmx_client import dmx_admin_configured

        if dmx_admin_configured():
            raise TextChatPrepError(
                {
                    "error": "dmx_provision_failed",
                    "detail": (
                        "DMX admin could not provision a per-user API key; "
                        "verify DMX_SYSTEM_TOKEN and DMX_API_USER_ID "
                        "(run scripts/probe_dmx_admin.py in the voice container)"
                    ),
                },
                503,
            )
        raise TextChatPrepError(
            {
                "error": "llm_api_key_missing",
                "detail": (
                    "LLM api_key is not configured for this user/device; "
                    "configure DMX admin credentials or set user llm_config"
                ),
            },
            400,
        )

    shuxin_home = Path(os.environ.get("SHUXIN_HOME") or str(Path.home() / ".shuxin"))
    user_home = shuxin_home / "users" / user_id
    user_home.mkdir(parents=True, exist_ok=True)

    service = VoiceService()
    agent = service.create_agent(device, user_home=user_home, companion_id=companion_id)
    try:
        agent.identity.set_mbti(str(companion["mbti"]))
    except Exception:
        pass
    agent.initialize()

    # 注入该伙伴最近原文，保证文字跨请求短期连续
    try:
        hist = await repo.list_companion_chat_history(
            user_id=user_id,
            companion_id=companion_id,
            limit=_voice_max_history(),
        )
        _seed_agent_short_term(agent, list(hist.get("turns") or []))
    except Exception as exc:
        logger.info("seed text short_term skipped: %s", exc)

    session_id = "text-{}-{}".format(companion_id, uuid.uuid4().hex[:12])
    try:
        await repo.ensure_session(
            session_id=session_id,
            user_id=user_id,
            device_id=soft_id,
            client_id="soft-miniprogram-text",
        )
    except Exception as exc:
        logger.info("ensure_session for text chat skipped: %s", exc)

    return {
        "user_id": user_id,
        "companion": companion,
        "companion_id": companion_id,
        "text": text,
        "soft_id": soft_id,
        "billing_settings": billing_settings,
        "estimate": estimate,
        "estimate_token": estimate_token,
        "estimate_typing": estimate_typing,
        "agent": agent,
        "user_settings": user_settings,
        "session_id": session_id,
    }


async def finalize_text_chat_billing(
    repo,
    *,
    ctx: Dict[str, Any],
    reply: str,
) -> Dict[str, Any]:
    """Deduct quota, record turn, return response body fields (usage + engagement)."""
    text = ctx["text"]
    billing_settings = ctx["billing_settings"]
    soft_id = ctx["soft_id"]
    user_id = ctx["user_id"]
    companion_id = ctx["companion_id"]
    companion = ctx["companion"]
    agent = ctx["agent"]

    usage: dict = {}
    try:
        usage = dict(getattr(agent, "last_usage", None) or {})
    except Exception:
        usage = {}
    prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion_tokens = int(
        usage.get("completion_tokens") or usage.get("output_tokens") or 0
    )
    cache_tokens = int(usage.get("cache_tokens") or usage.get("cached_tokens") or 0)
    if prompt_tokens <= 0 and completion_tokens <= 0:
        prompt_tokens = estimate_chars_to_prompt_tokens(text)
        completion_tokens = estimate_chars_to_prompt_tokens(str(reply or ""))

    cost_minutes = minutes_from_llm_usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_tokens=cache_tokens,
        settings=billing_settings,
    )
    if cost_minutes > 0:
        try:
            await repo.deduct_device_minutes_quota(soft_id, cost_minutes)
        except Exception as exc:
            logger.warning("text deduct failed: %s", exc)

    await repo.companions.record_text_turn(
        user_id=user_id,
        companion_id=companion_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_tokens=cache_tokens,
        cost_minutes=cost_minutes,
    )
    try:
        await repo.companions.after_companion_turn(
            user_id=user_id, companion_id=companion_id, voice_turn=False
        )
    except Exception as exc:
        logger.info("after_companion_turn skipped: %s", exc)

    # 与语音共用 conversation_events，供历史与短期回填
    user_settings = ctx.get("user_settings")
    if user_settings is not None:
        try:
            await repo.record_turn(
                user_settings=user_settings,
                device_id=soft_id,
                client_id="soft-miniprogram-text",
                session_id=str(ctx.get("session_id") or uuid.uuid4().hex),
                turn_id=uuid.uuid4().hex,
                user_text=text,
                reply_text=str(reply or ""),
                input_audio=None,
                reply_audio=None,
                timings={},
                companion_id=companion_id,
                channel="text",
            )
        except Exception as exc:
            logger.warning("text record_turn failed: %s", exc)

    engagement: dict = {}
    try:
        engagement = await repo.companions.get_engagement_for_user(
            user_id=user_id, companion_id=companion_id
        )
    except Exception as exc:
        logger.info("engagement after chat failed: %s", exc)

    return {
        "reply": str(reply or ""),
        "companion_id": companion_id,
        "mbti": companion["mbti"],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cache_tokens": cache_tokens,
            "cost_minutes": cost_minutes,
            "estimate_minutes": ctx["estimate"],
            "estimate_minutes_typing": ctx["estimate_typing"],
            "estimate_minutes_token_gate": ctx["estimate_token"],
            "chars_per_minute": float(billing_settings.get("chars_per_minute") or 40),
        },
        "engagement": engagement,
    }


def shutdown_agent(agent: Any) -> None:
    """先强制 flush Mem0，再释放 Agent（文本请求结束与语音挂断对齐）。"""
    try:
        memory = getattr(agent, "memory", None)
        if memory is not None and hasattr(memory, "flush_deferred_mem0"):
            memory.flush_deferred_mem0(force=True)
    except Exception as exc:
        logger.warning("text Mem0 flush failed: %s", exc)
    try:
        agent.shutdown()
    except Exception:
        pass
