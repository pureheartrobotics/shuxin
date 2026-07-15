from __future__ import annotations

from typing import Any

from shuxin.voice.integrations.wechat_pay import (
    create_jsapi_payment,
    parse_payment_notify,
    wechat_pay_configured,
    wechat_pay_mock_mode,
)


class WeChatPayGateway:
    """微信支付 SDK 门面。"""

    def mock_mode(self) -> bool:
        return wechat_pay_mock_mode()

    def configured(self) -> bool:
        return wechat_pay_configured()

    def create_jsapi(
        self,
        *,
        description: str,
        out_trade_no: str,
        amount_fen: int,
        payer_openid: str,
    ) -> dict[str, Any]:
        return create_jsapi_payment(
            description=description,
            out_trade_no=out_trade_no,
            amount_fen=amount_fen,
            payer_openid=payer_openid,
        )

    def parse_notify(self, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        return parse_payment_notify(headers, body)


_gateway: WeChatPayGateway | None = None


def get_wechat_pay_gateway() -> WeChatPayGateway:
    global _gateway
    if _gateway is None:
        _gateway = WeChatPayGateway()
    return _gateway
