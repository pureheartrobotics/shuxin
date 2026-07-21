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
