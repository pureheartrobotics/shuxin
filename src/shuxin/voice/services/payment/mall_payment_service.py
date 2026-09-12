from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from shuxin.voice.services.payment.wechat_pay_gateway import get_wechat_pay_gateway


class MallPaymentService:
    """实体商品商城支付。"""

    def __init__(self, repo: Any) -> None:
        self.repo = repo
        self.gateway = get_wechat_pay_gateway()

    async def create_order(
        self,
        *,
        session_token: str,
        address_id: str,
    ) -> JSONResponse:
        if not session_token:
            raise ValueError("session_token is required")
        if not address_id:
            raise ValueError("address_id is required")
        if self.gateway.mock_mode():
            return JSONResponse(
                {"error": "WeChat Pay is disabled while SHUXIN_WECHAT_MOCK=1"},
                status_code=503,
            )
        if not self.gateway.configured():
            return JSONResponse({"error": "WeChat Pay is not configured"}, status_code=503)

        created = await self.repo.mall.create_order_from_cart(
            session_token=session_token,
            address_id=address_id,
        )
        order = dict(created.get("order") or {})
        amount_fen = int(order.get("total_fen") or 0)
        if amount_fen <= 0:
            raise ValueError("invalid order amount")
        prepay = self.gateway.create_jsapi(
            description="初心商城订单",
            out_trade_no=str(order["out_trade_no"]),
            amount_fen=amount_fen,
            payer_openid=str(created["user_id"]),
        )
        await self.repo.mall.attach_mall_prepay_id(
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

    async def fulfill_notify(self, headers: dict[str, str], body: bytes) -> JSONResponse:
        payload = self.gateway.parse_notify(headers, body)
        out_trade_no = str(payload.get("out_trade_no") or "")
        if not out_trade_no:
            return JSONResponse({"code": "FAIL", "message": "missing out_trade_no"}, status_code=400)
        if not out_trade_no.startswith("mx"):
            return JSONResponse({"code": "FAIL", "message": "not a mall order"}, status_code=400)
        await self.repo.mall.fulfill_mall_order(
            out_trade_no=out_trade_no,
            wx_transaction_id=str(payload.get("transaction_id") or ""),
            notify_payload=payload,
        )
        return JSONResponse({"code": "SUCCESS", "message": "成功"})
