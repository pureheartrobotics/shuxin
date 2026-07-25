"""Unit tests for Qiniu CDN public_url helper."""

from __future__ import annotations

import os

import pytest

from shuxin.voice.cdn.qiniu import public_url, qiniu_config


@pytest.fixture(autouse=True)
def _clear_qiniu_env(monkeypatch: pytest.MonkeyPatch):
    for key in (
        "SHUXIN_QINIU_ACCESS_KEY",
        "SHUXIN_QINIU_SECRET_KEY",
        "SHUXIN_QINIU_BUCKET",
        "SHUXIN_QINIU_CDN_DOMAIN",
        "SHUXIN_QINIU_USE_HTTPS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_public_url_passthrough_absolute():
    assert public_url("https://cdn.example.com/a.png") == "https://cdn.example.com/a.png"
    assert public_url("http://cdn.example.com/a.png") == "http://cdn.example.com/a.png"
    assert public_url("//cdn.example.com/a.png") == "//cdn.example.com/a.png"


def test_public_url_relative_without_domain_returns_key():
    assert public_url("mbti/ENFJ.png") == "mbti/ENFJ.png"
    assert public_url("/mbti/ENFJ.png") == "mbti/ENFJ.png"


def test_public_url_joins_cdn_domain(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHUXIN_QINIU_CDN_DOMAIN", "cdn.example.com")
    assert public_url("mbti/ENFJ.png") == "https://cdn.example.com/mbti/ENFJ.png"
    monkeypatch.setenv("SHUXIN_QINIU_CDN_DOMAIN", "https://cdn.example.com/")
    assert public_url("mbti/ENFJ.png") == "https://cdn.example.com/mbti/ENFJ.png"
    monkeypatch.setenv("SHUXIN_QINIU_USE_HTTPS", "0")
    assert public_url("x.png") == "http://cdn.example.com/x.png"


def test_qiniu_config_reads_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHUXIN_QINIU_ACCESS_KEY", "ak")
    monkeypatch.setenv("SHUXIN_QINIU_SECRET_KEY", "sk")
    monkeypatch.setenv("SHUXIN_QINIU_BUCKET", "bucket")
    monkeypatch.setenv("SHUXIN_QINIU_CDN_DOMAIN", "cdn.example.com")
    cfg = qiniu_config()
    assert cfg["access_key"] == "ak"
    assert cfg["secret_key"] == "sk"
    assert cfg["bucket"] == "bucket"
    assert cfg["cdn_domain"] == "cdn.example.com"
    assert cfg["use_https"] is True


def test_public_url_empty():
    assert public_url("") == ""
    assert public_url("   ") == ""


def test_mbti_avatar_url_uses_zzx_xcx_prefix(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHUXIN_QINIU_CDN_DOMAIN", "cdn.example.com")
    from shuxin.voice.persistence.companion_repo import _mbti_avatar_url

    assert _mbti_avatar_url("INFJ") == "https://cdn.example.com/zzx_xcx/gacha/mbti/INFJ.png"
    assert _mbti_avatar_url("") == ""
