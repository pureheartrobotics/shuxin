from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from shuxin.voice.api.routers.deps import get_repo, require_admin
from shuxin.voice.services.payment.quota_payment_service import QuotaPaymentService

logger = logging.getLogger("shuxin.voice.api.routers.payment.quota")

router = APIRouter(tags=["Payment"])


def _quota_service(repo=Depends(get_repo)) -> QuotaPaymentService:
    return QuotaPaymentService(repo)


@router.get("/api/payment/plans")
async def payment_plans(service: QuotaPaymentService = Depends(_quota_service)):
    return JSONResponse(await service.list_plans())


@router.post("/api/payment/create-order")
async def payment_create_order(request: Request, service: QuotaPaymentService = Depends(_quota_service)):
    payload = await request.json()
    return await service.create_order(
        session_token=str(payload.get("session_token") or ""),
        plan_id=str(payload.get("plan_id") or ""),
        device_id=str(payload.get("device_id") or "").strip() or None,
    )


@router.post("/api/payment/orders")
async def payment_orders(request: Request, service: QuotaPaymentService = Depends(_quota_service)):
    payload = await request.json()
    return JSONResponse(
        await service.list_orders(
            session_token=str(payload.get("session_token") or ""),
            limit=int(payload.get("limit") or 20),
        )
    )


@router.post("/api/payment/notify")
async def payment_notify(request: Request, repo=Depends(get_repo)):
    from shuxin.voice.services.payment.mall_payment_service import MallPaymentService

    body = await request.body()
    headers = {key: value for key, value in request.headers.items()}
    try:
        gateway_payload = QuotaPaymentService(repo).gateway.parse_notify(headers, body)
        out_trade_no = str(gateway_payload.get("out_trade_no") or "")
        if out_trade_no.startswith("mx"):
            return await MallPaymentService(repo).fulfill_notify(headers, body)
        return await QuotaPaymentService(repo).fulfill_notify(headers, body)
    except Exception as exc:
        logger.exception("payment notify failed")
        return JSONResponse({"code": "FAIL", "message": str(exc)}, status_code=400)
