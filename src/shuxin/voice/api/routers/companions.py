"""Investor companions / gacha / text chat APIs."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from shuxin.voice.api.routers.deps import get_repo
from shuxin.voice.billing.text_billing import (
    estimate_minutes_by_typing_speed,
    estimate_minutes_for_text,
    minutes_from_llm_usage,
    text_max_chars,
)
from shuxin.voice.config.config import merge_llm_device_config
from shuxin.voice.integrations.dmx_client import default_platform_llm_config
from shuxin.voice.service import VoiceService
from shuxin.voice.services.payment.wechat_pay_gateway import get_wechat_pay_gateway

logger = logging.getLogger("shuxin.voice.api.companions")

router = APIRouter(tags=["Companions"])


def _err(exc: Exception, *, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=status)


@router.post("/api/gacha/config")
async def gacha_config(request: Request, repo=Depends(get_repo)):
    try:
        payload = await request.json()
        data = await repo.companions.get_gacha_config_for_user(
            session_token=str(payload.get("session_token") or "")
        )
        return JSONResponse(data)
    except PermissionError as exc:
        return _err(exc, status=401)
    except Exception as exc:
        logger.exception("gacha config failed")
        return _err(exc, status=500)


@router.post("/api/gacha/orders")
async def gacha_orders(request: Request, repo=Depends(get_repo)):
    try:
        payload = await request.json()
        session_token = str(payload.get("session_token") or "")
        order = await repo.companions.create_gacha_payment_order(session_token=session_token)
        if order.get("mock_paid"):
            return JSONResponse({"order": order, "pay_params": {}, "mock_paid": True})
        gateway = get_wechat_pay_gateway()
        if gateway.mock_mode() or not gateway.configured():
            # Already inserted as pending; mark paid for demo if mock
            return JSONResponse(
                {"error": "WeChat Pay is not configured; enable SHUXIN_WECHAT_MOCK=1 for demo"},
                status_code=503,
            )
        prepay = gateway.create_jsapi(
            description="初心抽卡一次",
            out_trade_no=str(order["out_trade_no"]),
            amount_fen=int(order["amount_fen"]),
            payer_openid=str(
                (await repo.companions._user_id_from_session(session_token))
            ),
        )
        await repo.attach_prepay_id(
            out_trade_no=str(order["out_trade_no"]),
            prepay_id=str(prepay["prepay_id"]),
        )
        return JSONResponse(
            {
                "order": order,
                "prepay_id": prepay["prepay_id"],
                "pay_params": dict(prepay.get("pay_params") or {}),
            }
        )
    except PermissionError as exc:
        return _err(exc, status=401)
    except Exception as exc:
        logger.exception("gacha order failed")
        return _err(exc, status=500)


@router.post("/api/gacha/draw")
async def gacha_draw(request: Request, repo=Depends(get_repo)):
    try:
        payload = await request.json()
        payment_id = str(payload.get("payment_id") or "").strip() or None
        result = await repo.companions.draw_companion(
            session_token=str(payload.get("session_token") or ""),
            payment_id=payment_id,
        )
        return JSONResponse(result)
    except PermissionError as exc:
        return _err(exc, status=401)
    except ValueError as exc:
        return _err(exc, status=400)
    except Exception as exc:
        logger.exception("gacha draw failed")
        return _err(exc, status=500)


@router.post("/api/companions")
async def companions_list(request: Request, repo=Depends(get_repo)):
    try:
        payload = await request.json()
        return JSONResponse(
            await repo.companions.list_companions(
                session_token=str(payload.get("session_token") or "")
            )
        )
    except PermissionError as exc:
        return _err(exc, status=401)
    except Exception as exc:
        logger.exception("companions list failed")
        return _err(exc, status=500)


@router.post("/api/companions/engagement")
async def companions_engagement(request: Request, repo=Depends(get_repo)):
    try:
        payload = await request.json()
        return JSONResponse(
            await repo.companions.get_engagement(
                session_token=str(payload.get("session_token") or ""),
                companion_id=str(payload.get("companion_id") or ""),
            )
        )
    except PermissionError as exc:
        return _err(exc, status=401)
    except Exception as exc:
        logger.exception("companions engagement failed")
        return _err(exc, status=500)


@router.post("/api/companions/engagement/ack-care")
async def companions_ack_care(request: Request, repo=Depends(get_repo)):
    try:
        payload = await request.json()
        return JSONResponse(
            await repo.companions.ack_engagement_care(
                session_token=str(payload.get("session_token") or ""),
                care_key=str(payload.get("care_key") or ""),
                companion_id=str(payload.get("companion_id") or ""),
            )
        )
    except PermissionError as exc:
        return _err(exc, status=401)
    except ValueError as exc:
        return _err(exc, status=400)
    except Exception as exc:
        logger.exception("companions ack care failed")
        return _err(exc, status=500)


@router.post("/api/companions/rename")
async def companions_rename(request: Request, repo=Depends(get_repo)):
    try:
        payload = await request.json()
        return JSONResponse(
            await repo.companions.rename_companion(
                session_token=str(payload.get("session_token") or ""),
                companion_id=str(payload.get("companion_id") or ""),
                display_name=str(payload.get("display_name") or ""),
            )
        )
    except PermissionError as exc:
        return _err(exc, status=401)
    except ValueError as exc:
        return _err(exc, status=400)
    except Exception as exc:
        logger.exception("companions rename failed")
        return _err(exc, status=500)


@router.post("/api/voice/soft-credentials")
async def soft_credentials(request: Request, repo=Depends(get_repo)):
    try:
        payload = await request.json()
        return JSONResponse(
            await repo.companions.issue_soft_credentials(
                session_token=str(payload.get("session_token") or "")
            )
        )
    except PermissionError as exc:
        return _err(exc, status=401)
    except Exception as exc:
        logger.exception("soft credentials failed")
        return _err(exc, status=500)


@router.post("/api/chat/text")
async def chat_text(request: Request, repo=Depends(get_repo)):
    """Text turn: LLM only, minutes via swappable text_billing."""
    try:
        payload = await request.json()
        session_token = str(payload.get("session_token") or "")
        companion_id = str(payload.get("companion_id") or "").strip()
        text = str(payload.get("text") or "").strip()
        if not companion_id:
            raise ValueError("companion_id is required")
        if not text:
            raise ValueError("text is required")

        user_id = await repo.companions._user_id_from_session(session_token)
        companion = await repo.companions.get_companion_for_user(
            user_id=user_id, companion_id=companion_id
        )
        billing_settings = await repo.companions.get_text_billing_settings()
        max_chars = text_max_chars(billing_settings)
        if len(text) > max_chars:
            raise ValueError(f"text exceeds {max_chars} characters")

        soft = await repo.companions.ensure_soft_device(user_id=user_id)
        soft_id = soft["device_id"]
        estimate_token = estimate_minutes_for_text(text, settings=billing_settings)
        estimate_typing = estimate_minutes_by_typing_speed(text, settings=billing_settings)
        estimate = max(estimate_token, estimate_typing)
        # Gate using existing quota helpers when available
        try:
            await repo.assert_device_quota_available(soft_id)
        except Exception as exc:
            quota_snap: dict[str, Any] = {}
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
            return JSONResponse(
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
                status_code=402,
            )

        device = await repo.get_device(soft_id)
        if hasattr(repo, "ensure_user_dmx_llm"):
            try:
                await repo.ensure_user_dmx_llm(user_id)
            except Exception as exc:
                logger.info("ensure_user_dmx_llm skipped: %s", exc)
        user_settings = await repo.get_user_settings(user_id)
        device.llm = merge_llm_device_config(
            device.llm,
            default_platform_llm_config(),
        )
        if user_settings and user_settings.llm_config:
            device.llm = merge_llm_device_config(device.llm, user_settings.llm_config)
        if not str(device.llm.api_key or "").strip():
            # 回退全局 Config（环境变量 / YAML），与 CLI 一致
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
                return JSONResponse(
                    {
                        "error": "dmx_provision_failed",
                        "detail": (
                            "DMX admin could not provision a per-user API key; "
                            "verify DMX_SYSTEM_TOKEN and DMX_API_USER_ID "
                            "(run scripts/probe_dmx_admin.py in the voice container)"
                        ),
                    },
                    status_code=503,
                )
            return JSONResponse(
                {
                    "error": "llm_api_key_missing",
                    "detail": (
                        "LLM api_key is not configured for this user/device; "
                        "configure DMX admin credentials or set user llm_config"
                    ),
                },
                status_code=400,
            )

        from pathlib import Path

        shuxin_home = Path(
            os.environ.get("SHUXIN_HOME")
            or str(Path.home() / ".shuxin")
        )
        user_home = shuxin_home / "users" / user_id
        user_home.mkdir(parents=True, exist_ok=True)

        service = VoiceService()
        agent = service.create_agent(
            device, user_home=user_home, companion_id=companion_id
        )
        try:
            agent.identity.set_mbti(str(companion["mbti"]))
        except Exception:
            pass
        agent.initialize()
        try:
            reply = agent.chat(text)
        finally:
            try:
                agent.shutdown()
            except Exception:
                pass

        usage = {}
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
            # Fallback estimate if provider did not return usage
            from shuxin.voice.billing.text_billing import estimate_chars_to_prompt_tokens

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
        engagement: dict[str, Any] = {}
        try:
            engagement = await repo.companions.get_engagement_for_user(
                user_id=user_id, companion_id=companion_id
            )
        except Exception as exc:
            logger.info("engagement after chat failed: %s", exc)
        return JSONResponse(
            {
                "reply": str(reply or ""),
                "companion_id": companion_id,
                "mbti": companion["mbti"],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cache_tokens": cache_tokens,
                    "cost_minutes": cost_minutes,
                    "estimate_minutes": estimate,
                    "estimate_minutes_typing": estimate_typing,
                    "estimate_minutes_token_gate": estimate_token,
                    "chars_per_minute": float(
                        billing_settings.get("chars_per_minute") or 40
                    ),
                },
                "engagement": engagement,
            }
        )
    except PermissionError as exc:
        return _err(exc, status=401)
    except ValueError as exc:
        return _err(exc, status=400)
    except Exception as exc:
        logger.exception("chat text failed")
        return _err(exc, status=500)
