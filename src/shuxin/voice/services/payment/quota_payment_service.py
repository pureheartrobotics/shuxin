from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from shuxin.voice.services.payment.wechat_pay_gateway import get_wechat_pay_gateway


class QuotaPaymentService:
    """时长充值支付（保持现有 profile 弹窗流程）。"""

    def __init__(self, repo: Any) -> None:
        self.repo = repo
        self.gateway = get_wechat_pay_gateway()

    async def list_plans(self) -> dict[str, Any]:
        try:
            plans = await self.repo.list_miniapp_payment_plans()
            return {"items": plans}
        except Exception:
            from shuxin.voice.config.payment_config import list_payment_plan_dicts

            return {"items": list_payment_plan_dicts()}

    async def create_order(
        self,
        *,
        session_token: str,
        plan_id: str,
        device_id: str | None = None,
    ) -> JSONResponse:
        if not session_token:
            raise ValueError("session_token is required")
        if not plan_id:
            raise ValueError("plan_id is required")
        if self.gateway.mock_mode():
            return JSONResponse(
                {"error": "WeChat Pay is disabled while SHUXIN_WECHAT_MOCK=1"},
                status_code=503,
            )
        if not self.gateway.configured():
            return JSONResponse({"error": "WeChat Pay is not configured"}, status_code=503)

        order = await self.repo.create_payment_order(
            session_token=session_token,
            plan_id=plan_id,
            device_id=device_id,
        )
        plan_payload = dict(order.get("plan") or {})
        amount_fen = int(plan_payload.get("amount_fen") or 0)
        plan_name = str(plan_payload.get("name") or plan_id)
        if amount_fen <= 0:
            raise ValueError(f"invalid plan amount for: {plan_id}")
        prepay = self.gateway.create_jsapi(
            description=f"初心{plan_name}",
            out_trade_no=str(order["out_trade_no"]),
            amount_fen=amount_fen,
            payer_openid=str(order["user_id"]),
        )
        await self.repo.attach_prepay_id(
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

    async def list_orders(self, *, session_token: str, limit: int = 20) -> dict[str, Any]:
        if not session_token:
            raise ValueError("session_token is required")
        return await self.repo.list_payment_orders_by_session(session_token, limit=limit)

    async def fulfill_notify(self, headers: dict[str, str], body: bytes) -> JSONResponse:
        payload = self.gateway.parse_notify(headers, body)
        out_trade_no = str(payload.get("out_trade_no") or "")
        if not out_trade_no:
            return JSONResponse({"code": "FAIL", "message": "missing out_trade_no"}, status_code=400)
        if out_trade_no.startswith("mx"):
            return JSONResponse({"code": "FAIL", "message": "not a quota order"}, status_code=400)
        await self.repo.fulfill_payment_order(
            out_trade_no=out_trade_no,
            wx_transaction_id=str(payload.get("transaction_id") or ""),
            notify_payload=payload,
        )
        return JSONResponse({"code": "SUCCESS", "message": "成功"})
