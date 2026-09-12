from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from shuxin.voice.server import create_app


def test_payment_plans_route() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/payment/plans")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) >= 1
    assert "amount_fen" in data["items"][0]


def test_payment_create_order_requires_session(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_WECHAT_MOCK", "1")
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/payment/create-order",
            json={"session_token": "", "plan_id": "plan_10"},
        )
    assert response.status_code == 400


def test_payment_create_order_disabled_in_mock_mode(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_WECHAT_MOCK", "1")
    app = create_app()

    class FakeRepo:
        async def create_payment_order(self, **kwargs):
            return {
                "order_id": "o1",
                "user_id": "wx_test",
                "out_trade_no": "sx123",
                "plan": {},
                "status": "pending",
                "created_at": "2026-01-01T00:00:00+00:00",
            }

    app.state.repo = FakeRepo()
    with TestClient(app) as client:
        response = client.post(
            "/api/payment/create-order",
            json={"session_token": "token", "plan_id": "plan_10"},
        )
    assert response.status_code == 503
    assert "SHUXIN_WECHAT_MOCK" in response.json()["error"]


def test_payment_create_order_uses_db_plan_snapshot(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_WECHAT_MOCK", "0")
    app = create_app()

    class FakeRepo:
        async def create_payment_order(self, **kwargs):
            return {
                "order_id": "o1",
                "user_id": "wx_test",
                "out_trade_no": "sx123",
                "plan": {
                    "id": "plan_10",
                    "name": "10 元",
                    "amount_fen": 1000,
                },
                "status": "pending",
                "created_at": "2026-01-01T00:00:00+00:00",
            }

        async def attach_prepay_id(self, *, out_trade_no: str, prepay_id: str) -> None:
            return None

    with TestClient(app) as client:
        client.app.state.repo = FakeRepo()
        with patch("shuxin.voice.services.payment.wechat_pay_gateway.wechat_pay_configured", return_value=True), patch(
            "shuxin.voice.services.payment.wechat_pay_gateway.wechat_pay_mock_mode",
            return_value=False,
        ), patch(
            "shuxin.voice.services.payment.wechat_pay_gateway.create_jsapi_payment",
            return_value={
                "prepay_id": "wx_prepay",
                "pay_params": {"timeStamp": "1", "nonceStr": "n", "package": "p"},
            },
        ) as create_jsapi:
            response = client.post(
                "/api/payment/create-order",
                json={"session_token": "token", "plan_id": "plan_10"},
            )

    assert response.status_code == 200
    assert response.json()["prepay_id"] == "wx_prepay"
    create_jsapi.assert_called_once_with(
        description="初心10 元",
        out_trade_no="sx123",
        amount_fen=1000,
        payer_openid="wx_test",
    )


def test_admin_payment_plans_crud(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    app = create_app()
    stored: dict = {"ratio": 0.95, "plans": []}

    class FakeRepo:
        async def list_payment_plans(self, *, include_disabled: bool = False):
            from shuxin.voice.config.payment_config import PaymentPlan

            plans = [
                PaymentPlan(
                    id="plan_100",
                    name="100 元",
                    amount_fen=10000,
                    enabled=True,
                    sort_order=10,
                )
            ]
            return plans if include_disabled else [p for p in plans if p.enabled]

        async def create_payment_plan(self, payload: dict):
            stored["plans"].append(payload)
            return {**payload, "enabled": True}

        async def get_payment_settings(self):
            return {"credit_ratio": stored["ratio"]}

        async def set_credit_ratio(self, ratio: float):
            stored["ratio"] = ratio
            return {"credit_ratio": ratio}

        async def soft_delete_payment_plan(self, plan_id: str):
            return {"plan_id": plan_id, "enabled": False}

    headers = {"X-Admin-Token": "admin-token"}
    with TestClient(app) as client:
        client.app.state.repo = FakeRepo()
        res = client.get("/admin/api/payment/plans", headers=headers)
        assert res.status_code == 200
        assert res.json()["items"][0]["plan_id"] == "plan_100"

        res = client.patch(
            "/admin/api/platform/payment-settings",
            headers=headers,
            json={"credit_ratio": 0.9},
        )
        assert res.status_code == 200
        assert res.json()["credit_ratio"] == 0.9

        res = client.post(
            "/admin/api/payment/plans",
            headers=headers,
            json={"plan_id": "plan_30", "name": "30 元", "amount_fen": 3000},
        )
        assert res.status_code == 200

        res = client.delete("/admin/api/payment/plans/plan_100", headers=headers)
        assert res.status_code == 200
        assert res.json()["enabled"] is False
