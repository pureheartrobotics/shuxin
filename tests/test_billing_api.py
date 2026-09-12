from __future__ import annotations

from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from shuxin.voice.server import create_app


class FakeRepo:
    def __init__(self) -> None:
        self.get_monthly_expenditure_summary = AsyncMock(return_value={
            "total_cost": 10.5,
            "breakdown": {
                "llm": {"cost": 6.0, "percentage": 57.14},
                "stt": {"cost": 2.5, "percentage": 23.81},
                "tts": {"cost": 2.0, "percentage": 19.05}
            },
            "total_turns": 100,
            "average_turn_cost": 0.105
        })
        self.list_expenditures = AsyncMock(return_value={
            "items": [
                {
                    "id": "exp1",
                    "user_id": "user1",
                    "type": "stt",
                    "model": "tencent-realtime",
                    "usage_amount": 12.5,
                    "cost_yuan": 0.0025,
                    "created_at": "2026-06-26T11:20:00+08:00"
                }
            ],
            "next_cursor": ""
        })
        self.delete_expenditure = AsyncMock(return_value=True)
        self.delete_monthly_expenditures = AsyncMock(return_value=5)
        self.get_all_pricing = AsyncMock(return_value={
            "stt": {"tencent-realtime": 0.0002},
            "tts": {"volcengine-clone": 0.00002},
            "llm": {"deepseek-chat": 0.000002}
        })
        self.update_pricing = AsyncMock()


def test_billing_summary_route(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "test_token")
    app = create_app()

    # 未登录请求应返回 403
    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        response = client.get("/admin/api/billing/summary?month=2026-06")
        assert response.status_code == 403

    # 登录后请求应返回 200
    with TestClient(app) as client:
        fake_repo = FakeRepo()
        app.state.repo = fake_repo
        response = client.get(
            "/admin/api/billing/summary?month=2026-06",
            headers={"X-Admin-Token": "test_token"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["total_cost"] == 10.5
        fake_repo.get_monthly_expenditure_summary.assert_called_once_with("2026-06")


def test_billing_records_route(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "test_token")
    app = create_app()

    with TestClient(app) as client:
        fake_repo = FakeRepo()
        app.state.repo = fake_repo
        response = client.get(
            "/admin/api/billing/records?month=2026-06&user_id=user1&limit=20",
            headers={"X-Admin-Token": "test_token"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]["items"]) == 1
        assert data["data"]["items"][0]["id"] == "exp1"
        fake_repo.list_expenditures.assert_called_once_with(
            month_str="2026-06", user_id="user1", limit=20, cursor=""
        )


def test_delete_billing_record_route(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "test_token")
    app = create_app()

    with TestClient(app) as client:
        fake_repo = FakeRepo()
        app.state.repo = fake_repo
        response = client.delete(
            "/admin/api/billing/records/exp1",
            headers={"X-Admin-Token": "test_token"}
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        fake_repo.delete_expenditure.assert_called_once_with("exp1")


def test_clear_monthly_billing_route(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "test_token")
    app = create_app()

    with TestClient(app) as client:
        fake_repo = FakeRepo()
        app.state.repo = fake_repo
        response = client.delete(
            "/admin/api/billing/records/months/2026-06",
            headers={"X-Admin-Token": "test_token"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["deleted_count"] == 5
        fake_repo.delete_monthly_expenditures.assert_called_once_with("2026-06")


def test_billing_pricing_routes(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "test_token")
    app = create_app()

    # Test GET pricing
    with TestClient(app) as client:
        fake_repo = FakeRepo()
        app.state.repo = fake_repo
        response = client.get(
            "/admin/api/billing/pricing",
            headers={"X-Admin-Token": "test_token"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["stt"]["tencent-realtime"] == 0.0002

    # Test PATCH pricing
    with TestClient(app) as client:
        fake_repo = FakeRepo()
        app.state.repo = fake_repo
        response = client.patch(
            "/admin/api/billing/pricing",
            json={"stt": {"tencent-realtime": 0.00025}},
            headers={"X-Admin-Token": "test_token"}
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        fake_repo.update_pricing.assert_called_once_with("stt", {"tencent-realtime": 0.00025})


def test_device_bind_quota_exhausted() -> None:
    app = create_app()
    with TestClient(app) as client:
        fake_repo = FakeRepo()
        fake_repo.get_user_quota_by_session = AsyncMock(return_value={"exhausted": True})
        fake_repo.bind_device = AsyncMock(return_value={"binding_id": "bind_999", "already_bound": False})
        app.state.repo = fake_repo
        
        response = client.post(
            "/api/devices/bind",
            json={
                "session_token": "test_sess",
                "claim_code": "code123",
                "device_code": "dev123"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["binding_id"] == "bind_999"
