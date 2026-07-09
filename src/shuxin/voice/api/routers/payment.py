from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from shuxin.voice.api.routers.deps import get_repo

logger = logging.getLogger("shuxin.voice.api.routers.payment")

router = APIRouter(tags=["Payment"])


@router.get("/api/payment/plans")
async def payment_plans(repo=Depends(get_repo)):
    try:
        plans = await repo.list_miniapp_payment_plans()
        return JSONResponse({"items": plans})
    except Exception as exc:
        logger.warning("Failed to list miniapp payment plans, falling back: %s", exc)
        from shuxin.voice.config.payment_config import list_payment_plan_dicts
        return JSONResponse({"items": list_payment_plan_dicts()})


@router.post("/api/payment/create-order")
async def payment_create_order(request: Request, repo=Depends(get_repo)):
    from shuxin.voice.integrations.wechat_pay import create_jsapi_payment, wechat_pay_configured, wechat_pay_mock_mode

    payload = await request.json()
    session_token = str(payload.get("session_token") or "")
    plan_id = str(payload.get("plan_id") or "")
    if not session_token:
        raise ValueError("session_token is required")
    if not plan_id:
        raise ValueError("plan_id is required")
    if wechat_pay_mock_mode():
        return JSONResponse(
            {"error": "WeChat Pay is disabled while SHUXIN_WECHAT_MOCK=1"},
            status_code=503,
        )
    if not wechat_pay_configured():
        return JSONResponse({"error": "WeChat Pay is not configured"}, status_code=503)

    device_id = str(payload.get("device_id") or "").strip() or None
    order = await repo.create_payment_order(session_token=session_token, plan_id=plan_id, device_id=device_id)
    plan_payload = dict(order.get("plan") or {})
    amount_fen = int(plan_payload.get("amount_fen") or 0)
    plan_name = str(plan_payload.get("name") or plan_id)
    if amount_fen <= 0:
        raise ValueError(f"invalid plan amount for: {plan_id}")
    prepay = create_jsapi_payment(
        description=f"初心{plan_name}",
        out_trade_no=str(order["out_trade_no"]),
        amount_fen=amount_fen,
        payer_openid=str(order["user_id"]),
    )
    await repo.attach_prepay_id(
        out_trade_no=str(order["out_trade_no"]),
        prepay_id=str(prepay["prepay_id"]),
    )
    pay_params = dict(prepay.get("pay_params") or {})
    return JSONResponse(
        {
            "order": order,
            "prepay_id": prepay["prepay_id"],
            "pay_params": pay_params,
        }
    )


@router.post("/api/payment/orders")
async def payment_orders(request: Request, repo=Depends(get_repo)):
    payload = await request.json()
    session_token = str(payload.get("session_token") or "")
    if not session_token:
        raise ValueError("session_token is required")
    limit = int(payload.get("limit") or 20)
    return JSONResponse(
        await repo.list_payment_orders_by_session(session_token, limit=limit)
    )


@router.post("/api/payment/notify")
async def payment_notify(request: Request, repo=Depends(get_repo)):
    from shuxin.voice.integrations.wechat_pay import parse_payment_notify

    body = await request.body()
    headers = {key: value for key, value in request.headers.items()}
    try:
        payload = parse_payment_notify(headers, body)
        out_trade_no = str(payload.get("out_trade_no") or "")
        wx_transaction_id = str(payload.get("transaction_id") or "")
        if not out_trade_no:
            return JSONResponse({"code": "FAIL", "message": "missing out_trade_no"}, status_code=400)
        await repo.fulfill_payment_order(
            out_trade_no=out_trade_no,
            wx_transaction_id=wx_transaction_id,
            notify_payload=payload,
        )
        return JSONResponse({"code": "SUCCESS", "message": "成功"})
    except Exception as exc:
        logger.exception("payment notify failed")
        return JSONResponse({"code": "FAIL", "message": str(exc)}, status_code=400)
