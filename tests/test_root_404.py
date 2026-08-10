"""Root path must return a browser-facing HTTP 404 (备案：主域名无网站内容)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_root_returns_html_404():
    from shuxin.voice.server import create_app

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 404
        assert "application/json" not in (response.headers.get("content-type") or "")
        assert "text/html" in (response.headers.get("content-type") or "")
        assert "<h1>404 Not Found</h1>" in response.text
        assert "nginx" not in response.text.lower()
        assert '{"error"' not in response.text


def test_health_still_ok():
    from shuxin.voice.server import create_app

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json().get("status") == "ok"
