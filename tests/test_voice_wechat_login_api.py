from __future__ import annotations

from fastapi.testclient import TestClient

from shuxin.voice.server import create_app


def test_wechat_login_returns_app_session_without_session_key(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_WECHAT_MOCK", "1")
    app = create_app()

    with TestClient(app) as client:
        response = client.post("/api/wechat/login", json={"wx_code": "login-code-001"})

    assert response.status_code == 200
    data = response.json()
    assert data["session_token"]
    assert data["expires_at"]
    assert data["user_id"].startswith("wx_")
    assert "session_key" not in data


def test_device_routes_accept_session_token_while_keeping_wx_code(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_WECHAT_MOCK", "1")
    app = create_app()

    class FakeRepo:
        def __init__(self) -> None:
            self.calls = []

        async def bind_device(self, **kwargs):
            self.calls.append(("bind", kwargs))
            return {"ok": True}

        async def list_my_devices(self, **kwargs):
            self.calls.append(("my", kwargs))
            return {"items": []}

        async def unbind_device_by_wx_code(self, **kwargs):
            self.calls.append(("unbind_wx", kwargs))
            return {"ok": True}

        async def unbind_device_by_session(self, **kwargs):
            self.calls.append(("unbind_session", kwargs))
            return {"ok": True}

    with TestClient(app) as client:
        fake = FakeRepo()
        app.state.repo = fake
        bind = client.post(
            "/api/devices/bind",
            json={"session_token": "app-session", "claim_code": "CLM-A001-000003"},
        )
        mine = client.post("/api/devices/my", json={"session_token": "app-session"})
        unbind = client.post(
            "/api/devices/unbind",
            json={"session_token": "app-session", "device_code": "SX-000003"},
        )
        legacy = client.post(
            "/api/devices/my",
            json={"wx_code": "legacy-code"},
        )

    assert bind.status_code == 200
    assert mine.status_code == 200
    assert unbind.status_code == 200
    assert legacy.status_code == 200
    assert fake.calls == [
        ("bind", {"wx_code": "", "session_token": "app-session", "claim_code": "CLM-A001-000003", "device_code": ""}),
        ("my", {"wx_code": "", "session_token": "app-session"}),
        ("unbind_session", {"session_token": "app-session", "device_code": "SX-000003"}),
        ("my", {"wx_code": "legacy-code", "session_token": ""}),
    ]
