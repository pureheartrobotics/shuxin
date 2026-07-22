"""Investor companions / gacha / text chat APIs."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from shuxin.voice.api.routers.deps import get_repo
from shuxin.voice.billing.text_billing import (
    estimate_minutes_for_text,
    minutes_from_llm_usage,
    text_max_chars,
)
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
        estimate = estimate_minutes_for_text(text, settings=billing_settings)
        # Gate using existing quota helpers when available
        try:
            await repo.assert_device_quota_available(soft_id)
        except Exception as exc:
            return JSONResponse(
                {"error": "quota_exhausted", "detail": str(exc)},
                status_code=402,
            )

        # Run Agent with companion MBTI
        from shuxin.core.agent import Agent
        from shuxin.core.config import Config

        config = Config()
        agent = Agent(config=config)
        # Apply MBTI identity
        try:
            agent.identity.set_mbti(str(companion["mbti"]))
        except Exception:
            pass
        agent.initialize()
        reply = agent.chat(text)

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
                },
            }
        )
    except PermissionError as exc:
        return _err(exc, status=401)
    except ValueError as exc:
        return _err(exc, status=400)
    except Exception as exc:
        logger.exception("chat text failed")
        return _err(exc, status=500)
