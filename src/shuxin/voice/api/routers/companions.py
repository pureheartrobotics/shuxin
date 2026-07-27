"""Investor companions / gacha / text chat APIs."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from shuxin.voice.api.routers.deps import get_repo
from shuxin.voice.api.routers.text_chat import (
    TextChatPrepError,
    finalize_text_chat_billing,
    prepare_text_chat,
    shutdown_agent,
)
from shuxin.voice.services.payment.wechat_pay_gateway import get_wechat_pay_gateway

logger = logging.getLogger("shuxin.voice.api.companions")

router = APIRouter(tags=["Companions"])


def _err(exc: Exception, *, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=status)


def _ndjson_line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


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
        ctx = await prepare_text_chat(
            repo,
            session_token=str(payload.get("session_token") or ""),
            companion_id=str(payload.get("companion_id") or ""),
            text=str(payload.get("text") or ""),
        )
        agent = ctx["agent"]
        try:
            reply = agent.chat(ctx["text"])
            body = await finalize_text_chat_billing(repo, ctx=ctx, reply=str(reply or ""))
            return JSONResponse(body)
        finally:
            shutdown_agent(agent)
    except TextChatPrepError as exc:
        return JSONResponse(exc.payload, status_code=exc.status_code)
    except PermissionError as exc:
        return _err(exc, status=401)
    except ValueError as exc:
        return _err(exc, status=400)
    except Exception as exc:
        logger.exception("chat text failed")
        return _err(exc, status=500)


@router.post("/api/chat/text/stream")
async def chat_text_stream(request: Request, repo=Depends(get_repo)):
    """NDJSON stream: delta lines then one done (or error) line. Same billing as /api/chat/text."""
    try:
        payload = await request.json()
        ctx = await prepare_text_chat(
            repo,
            session_token=str(payload.get("session_token") or ""),
            companion_id=str(payload.get("companion_id") or ""),
            text=str(payload.get("text") or ""),
        )
    except TextChatPrepError as exc:
        return JSONResponse(exc.payload, status_code=exc.status_code)
    except PermissionError as exc:
        return _err(exc, status=401)
    except ValueError as exc:
        return _err(exc, status=400)
    except Exception as exc:
        logger.exception("chat text stream prep failed")
        return _err(exc, status=500)

    agent = ctx["agent"]
    text = ctx["text"]
    loop = asyncio.get_event_loop()
    stream_iter = agent.chat_stream(text)
    sentinel = object()

    async def event_gen():
        full = ""
        try:
            while True:
                chunk = await loop.run_in_executor(
                    None, lambda it=stream_iter, s=sentinel: next(it, s)
                )
                if chunk is sentinel:
                    break
                piece = str(chunk or "")
                if not piece:
                    continue
                full += piece
                yield _ndjson_line({"type": "delta", "text": piece})
            body = await finalize_text_chat_billing(repo, ctx=ctx, reply=full)
            yield _ndjson_line({"type": "done", **body})
        except Exception as exc:
            logger.exception("chat text stream failed")
            yield _ndjson_line(
                {"type": "error", "error": "stream_failed", "detail": str(exc)}
            )
        finally:
            shutdown_agent(agent)

    return StreamingResponse(
        event_gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
