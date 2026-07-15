from __future__ import annotations

from fastapi.testclient import TestClient

from shuxin.voice.server import create_app


def test_mall_products_route_returns_items() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/mall/products")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)


def test_mall_cart_requires_session() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/api/mall/cart", json={"session_token": ""})
    assert response.status_code == 403


def test_mall_admin_products_requires_auth() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/admin/api/mall/products")
    assert response.status_code in (401, 403)


def test_local_repo_exposes_mall_stub() -> None:
    from shuxin.voice.persistence.mall_local_repo import MallLocalRepository

    repo = MallLocalRepository(parent=object())
    assert hasattr(repo, "list_products")
