"""Admin 七牛上传凭证 API 测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_upload_token_unauthorized(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("SHUXIN_MINIAPP_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("SHUXIN_QINIU_ACCESS_KEY", "ak")
    monkeypatch.setenv("SHUXIN_QINIU_SECRET_KEY", "sk")
    monkeypatch.setenv("SHUXIN_QINIU_BUCKET", "bucket")
    monkeypatch.setenv("SHUXIN_QINIU_CDN_DOMAIN", "cdn.example.com")
    from shuxin.voice.server import create_app

    app = create_app()
    with TestClient(app) as client:
        res = client.post(
            "/miniapp-admin/api/upload/token",
            json={"purpose": "mall_product_cover", "entity_id": "prod_1"},
        )
    assert res.status_code == 401


def test_upload_token_ok_for_mall_cover(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("SHUXIN_MINIAPP_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("SHUXIN_QINIU_ACCESS_KEY", "ak")
    monkeypatch.setenv("SHUXIN_QINIU_SECRET_KEY", "sk-never-leak")
    monkeypatch.setenv("SHUXIN_QINIU_BUCKET", "bucket")
    monkeypatch.setenv("SHUXIN_QINIU_CDN_DOMAIN", "cdn.example.com")
    from shuxin.voice.server import create_app

    app = create_app()
    with TestClient(app) as client:
        res = client.post(
            "/miniapp-admin/api/upload/token",
            json={"purpose": "mall_product_cover", "entity_id": "prod_1"},
            headers={"X-Miniapp-Admin-Token": "admin-secret"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["key"] == "zzx_xcx/mall/products/prod_1/cover.webp"
    assert "up-z2.qiniup.com" in body["upload_url"]
    assert "sk-never-leak" not in res.text


def test_upload_token_rejects_ugc_purpose(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("SHUXIN_MINIAPP_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("SHUXIN_QINIU_ACCESS_KEY", "ak")
    monkeypatch.setenv("SHUXIN_QINIU_SECRET_KEY", "sk")
    monkeypatch.setenv("SHUXIN_QINIU_BUCKET", "bucket")
    from shuxin.voice.server import create_app

    app = create_app()
    with TestClient(app) as client:
        res = client.post(
            "/miniapp-admin/api/upload/token",
            json={"purpose": "ugc_avatar", "entity_id": "x"},
            headers={"X-Miniapp-Admin-Token": "admin-secret"},
        )
    assert res.status_code == 400
