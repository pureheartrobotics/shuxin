from __future__ import annotations

import asyncio

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from shuxin.voice.persistence.postgres_repository import VoicePostgresRepository
from shuxin.voice.server import create_app


def test_provision_devices_batch_requires_encryption(monkeypatch) -> None:
    monkeypatch.delenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", raising=False)
    repo = VoicePostgresRepository(pool=None)

    async def run() -> None:
        await repo.provision_devices_batch({"quantity": 1})

    with pytest.raises(PermissionError, match="SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY"):
        asyncio.run(run())


def test_provision_device_requires_encryption(monkeypatch) -> None:
    monkeypatch.delenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", raising=False)
    repo = VoicePostgresRepository(pool=None)

    async def run() -> None:
        await repo.provision_device("SX-000099")

    with pytest.raises(PermissionError, match="SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY"):
        asyncio.run(run())


def test_rotate_device_secret_requires_encryption(monkeypatch) -> None:
    monkeypatch.delenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", raising=False)
    repo = VoicePostgresRepository(pool=None)

    async def run() -> None:
        await repo.rotate_device_secret("SX-000099")

    with pytest.raises(PermissionError, match="SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY"):
        asyncio.run(run())


def test_admin_batch_api_fails_without_encryption_key(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    monkeypatch.delenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", raising=False)
    app = create_app()

    class FakeRepo:
        async def provision_devices_batch(self, payload: dict) -> dict:
            return await VoicePostgresRepository(pool=None).provision_devices_batch(payload)

    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        res = client.post(
            "/admin/api/factory/devices/batch",
            headers={"X-Admin-Token": "admin-token"},
            json={"quantity": 1},
        )

    assert res.status_code == 400
    assert "SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY" in res.json()["error"]


def test_list_devices_reports_encryption_configured(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY", key)
    app = create_app()

    class FakeRepo:
        async def list_devices(self, *, limit: int = 50, cursor: str = "", q: str = "") -> dict:
            return {"items": [], "next_cursor": "", "device_secret_encryption_configured": True}

    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        res = client.get("/admin/api/devices", headers={"X-Admin-Token": "admin-token"})

    assert res.status_code == 200
    assert res.json()["device_secret_encryption_configured"] is True
