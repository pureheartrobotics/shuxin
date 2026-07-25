"""TokenSigner 单元测试（不回显密钥）。"""

from __future__ import annotations

import json

import pytest

from shuxin.voice.cdn.token_signer import issue_upload_token


@pytest.fixture
def qiniu_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHUXIN_QINIU_ACCESS_KEY", "test-ak")
    monkeypatch.setenv("SHUXIN_QINIU_SECRET_KEY", "test-sk-secret-value")
    monkeypatch.setenv("SHUXIN_QINIU_BUCKET", "test-bucket")
    monkeypatch.setenv("SHUXIN_QINIU_CDN_DOMAIN", "cdn.example.com")
    monkeypatch.setenv("SHUXIN_QINIU_USE_HTTPS", "1")
    monkeypatch.delenv("SHUXIN_QINIU_UPLOAD_HOST", raising=False)


def test_issue_upload_token_shape(qiniu_env):
    out = issue_upload_token(purpose="mall_product_cover", entity_id="prod_1")
    assert out["key"] == "zzx_xcx/mall/products/prod_1/cover.webp"
    assert "up-z2.qiniup.com" in out["upload_url"]
    assert out["cdn_url"] == "https://cdn.example.com/zzx_xcx/mall/products/prod_1/cover.webp"
    assert out["token"]
    assert out["expires_in"] >= 60
    blob = json.dumps(out, ensure_ascii=False)
    assert "test-sk-secret-value" not in blob


def test_issue_gacha_mbti(qiniu_env):
    out = issue_upload_token(purpose="gacha_mbti", entity_id="INFJ")
    assert out["key"] == "zzx_xcx/gacha/mbti/INFJ.png"


def test_issue_requires_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SHUXIN_QINIU_ACCESS_KEY", raising=False)
    monkeypatch.delenv("SHUXIN_QINIU_SECRET_KEY", raising=False)
    monkeypatch.delenv("SHUXIN_QINIU_BUCKET", raising=False)
    with pytest.raises(RuntimeError):
        issue_upload_token(purpose="system_ui", entity_id="banner.png")
