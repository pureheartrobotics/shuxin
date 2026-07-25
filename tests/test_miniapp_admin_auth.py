from __future__ import annotations

import os

from fastapi.testclient import TestClient


def test_miniapp_admin_login_rejects_when_token_unset(monkeypatch) -> None:
    monkeypatch.delenv("SHUXIN_MINIAPP_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("SHUXIN_ADMIN_TOKEN", raising=False)
    from shuxin.voice.server import create_app

    app = create_app()
    with TestClient(app) as client:
        res = client.post("/miniapp-admin/api/login", json={"token": "any"})
    assert res.status_code == 403
    assert "not configured" in res.json().get("error", "")


def test_miniapp_admin_login_rejects_wrong_token(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "correct-token")
    monkeypatch.delenv("SHUXIN_MINIAPP_ADMIN_TOKEN", raising=False)
    from shuxin.voice.server import create_app

    app = create_app()
    with TestClient(app) as client:
        res = client.post("/miniapp-admin/api/login", json={"token": "wrong"})
    assert res.status_code == 403
    assert res.json().get("error") == "invalid admin token"


def test_miniapp_admin_login_ok_sets_cookie(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_MINIAPP_ADMIN_TOKEN", "mini-secret")
    from shuxin.voice.server import create_app

    app = create_app()
    with TestClient(app) as client:
        res = client.post("/miniapp-admin/api/login", json={"token": "mini-secret"})
        assert res.status_code == 200
        assert res.json().get("ok") is True
        assert client.cookies.get("shuxin_miniapp_admin") == "mini-secret"
        portal = client.get("/miniapp-admin")
    assert portal.status_code == 200
    assert "authenticated" in portal.text
    assert "true" in portal.text  # authenticated inject


def test_miniapp_admin_mall_api_requires_auth(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    from shuxin.voice.server import create_app

    app = create_app()
    with TestClient(app) as client:
        res = client.get("/miniapp-admin/api/mall/products")
    assert res.status_code == 401


def test_text_billing_settings_requires_auth(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    from shuxin.voice.server import create_app

    app = create_app()
    with TestClient(app) as client:
        res = client.get("/miniapp-admin/api/investor/text-billing-settings")
    assert res.status_code == 401


def test_text_billing_settings_get_put_ok(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_MINIAPP_ADMIN_TOKEN", "mini-secret")
    from shuxin.voice.server import create_app

    class FakeCompanions:
        def __init__(self):
            self._settings = {
                "chars_per_minute": 40.0,
                "text_max_chars": 500.0,
                "llm_input_yuan_per_m_tokens": 0.85,
                "llm_output_yuan_per_m_tokens": 1.7,
                "llm_cache_yuan_per_m_tokens": 0.02,
                "yuan_to_minutes_rate": 1.0,
            }

        async def get_text_billing_settings(self):
            return dict(self._settings)

        async def set_text_billing_settings(self, value):
            self._settings.update(value)
            return dict(self._settings)

    app = create_app()
    with TestClient(app) as client:
        app.state.repo = type("R", (), {"companions": FakeCompanions()})()
        headers = {"X-Miniapp-Admin-Token": "mini-secret"}
        got = client.get(
            "/miniapp-admin/api/investor/text-billing-settings", headers=headers
        )
        assert got.status_code == 200
        assert got.json()["chars_per_minute"] == 40.0
        put = client.put(
            "/miniapp-admin/api/investor/text-billing-settings",
            headers=headers,
            json={"chars_per_minute": 55},
        )
        assert put.status_code == 200
        assert put.json()["chars_per_minute"] == 55.0
