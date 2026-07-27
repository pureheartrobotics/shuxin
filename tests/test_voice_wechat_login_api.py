from __future__ import annotations

from fastapi.testclient import TestClient

from shuxin.voice.server import create_app


def test_wechat_login_returns_app_session_without_session_key(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_WECHAT_MOCK", "1")
    monkeypatch.delenv("SHUXIN_WECHAT_MOCK_OPENID", raising=False)
    app = create_app()

    with TestClient(app) as client:
        response = client.post("/api/wechat/login", json={"wx_code": "login-code-001"})

    assert response.status_code == 200
    data = response.json()
    assert data["session_token"]
    assert data["expires_at"]
    assert data["user_id"] == "wx_mock_dev_user"
    assert "session_key" not in data


def test_wechat_mock_openid_stable_across_codes(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_WECHAT_MOCK", "1")
    monkeypatch.delenv("SHUXIN_WECHAT_MOCK_OPENID", raising=False)
    app = create_app()

    with TestClient(app) as client:
        a = client.post("/api/wechat/login", json={"wx_code": "code-aaa"}).json()
        b = client.post("/api/wechat/login", json={"wx_code": "code-bbb"}).json()

    assert a["user_id"] == b["user_id"] == "wx_mock_dev_user"


def test_wechat_mock_openid_env_override(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_WECHAT_MOCK", "1")
    monkeypatch.setenv("SHUXIN_WECHAT_MOCK_OPENID", "wx_custom_stable")
    app = create_app()

    with TestClient(app) as client:
        data = client.post("/api/wechat/login", json={"wx_code": "any"}).json()

    assert data["user_id"] == "wx_custom_stable"


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

        async def get_user_quota_by_session(self, session_token: str):
            return {"configured": False, "exhausted": False}

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


def test_admin_next_sequence_route_requires_token_and_uses_repo(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    app = create_app()

    class FakeRepo:
        def __init__(self) -> None:
            self.prefixes = []

        async def next_device_sequence(self, device_prefix: str):
            self.prefixes.append(device_prefix)
            return {
                "device_prefix": device_prefix,
                "next_sequence": 4,
                "next_device_id": f"{device_prefix}-000004",
            }

    with TestClient(app) as client:
        fake = FakeRepo()
        app.state.repo = fake
        forbidden = client.get("/admin/api/factory/devices/next-sequence?device_prefix=SX")
        ok = client.get(
            "/admin/api/factory/devices/next-sequence?device_prefix=SX",
            headers={"X-Admin-Token": "admin-token"},
        )

    assert forbidden.status_code == 403
    assert ok.status_code == 200
    assert ok.json() == {
        "device_prefix": "SX",
        "next_sequence": 4,
        "next_device_id": "SX-000004",
    }
    assert fake.prefixes == ["SX"]


def test_user_quota_route_uses_session_token(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_WECHAT_MOCK", "1")
    app = create_app()

    class FakeRepo:
        async def get_user_quota_by_session(self, session_token: str):
            assert session_token == "app-session"
            return {
                "user_id": "wx_test",
                "configured": True,
                "remain_yuan": 8.5,
                "used_yuan": 1.5,
                "exhausted": False,
                "message": "",
            }

    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        response = client.post("/api/users/quota", json={"session_token": "app-session"})

    assert response.status_code == 200
    assert response.json()["remain_yuan"] == 8.5


def test_bind_device_allows_exhausted_quota(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_WECHAT_MOCK", "1")
    app = create_app()

    class FakeRepo:
        async def get_user_quota_by_session(self, session_token: str):
            return {"configured": True, "exhausted": True, "message": "额度已用尽，请联系客服"}

        async def bind_device(self, **kwargs):
            return {"binding_id": "test_bind_999", "already_bound": False}

    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        response = client.post(
            "/api/devices/bind",
            json={"session_token": "app-session", "claim_code": "CLM-A001-000001"},
        )

    assert response.status_code == 200
    assert response.json()["binding_id"] == "test_bind_999"


def test_admin_platform_llm_defaults_route(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("SHUXIN_LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("DMX_API_BASE_URL", "https://www.dmxapi.cn")
    app = create_app()

    with TestClient(app) as client:
        forbidden = client.get("/admin/api/platform/llm-defaults")
        ok = client.get(
            "/admin/api/platform/llm-defaults",
            headers={"X-Admin-Token": "admin-token"},
        )

    assert forbidden.status_code == 403
    assert ok.status_code == 200
    assert ok.json()["model"] == "deepseek-v4-flash"
    assert ok.json()["base_url"] == "https://www.dmxapi.cn"


def test_admin_quota_top_up_route(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    app = create_app()

    class FakeRepo:
        async def top_up_user_dmx_quota(self, user_id: str, *, add_yuan: float, note: str = ""):
            assert user_id == "wx_user_1"
            assert add_yuan == 10
            assert note == "wechat-pay-001"
            return {
                "user_id": user_id,
                "configured": True,
                "remain_yuan": 10.0,
                "exhausted": False,
                "add_yuan": 10,
            }

    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        forbidden = client.post(
            "/admin/api/users/wx_user_1/quota/top-up",
            json={"add_yuan": 10, "note": "wechat-pay-001"},
        )
        ok = client.post(
            "/admin/api/users/wx_user_1/quota/top-up",
            json={"add_yuan": 10, "note": "wechat-pay-001"},
            headers={"X-Admin-Token": "admin-token"},
        )

    assert forbidden.status_code == 403
    assert ok.status_code == 200
    assert ok.json()["remain_yuan"] == 10.0
