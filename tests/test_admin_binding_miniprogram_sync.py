from __future__ import annotations

from fastapi.testclient import TestClient

from shuxin.voice.server import create_app


def test_admin_unbind_removes_device_from_miniprogram_my_list(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    app = create_app()

    class FakeRepo:
        def __init__(self) -> None:
            self.bindings: dict[str, dict[str, str]] = {
                "bind-001": {
                    "binding_id": "bind-001",
                    "user_id": "wx_user_a",
                    "device_id": "SX-000001",
                    "status": "active",
                }
            }
            self.user_devices: dict[str, list[str]] = {"wx_user_a": ["SX-000001"]}
            self.session_users = {"sess-a": "wx_user_a"}

        async def admin_bind_device(self, *, user_id: str, device_id: str) -> dict:
            binding_id = f"bind-{len(self.bindings) + 1:03d}"
            self.bindings[binding_id] = {
                "binding_id": binding_id,
                "user_id": user_id,
                "device_id": device_id,
                "status": "active",
            }
            self.user_devices.setdefault(user_id, []).append(device_id)
            return {"binding_id": binding_id, "user_id": user_id, "device_id": device_id}

        async def admin_unbind_device(self, *, binding_id: str) -> dict:
            row = self.bindings.get(binding_id)
            if not row or row["status"] != "active":
                return {"ok": False}
            row["status"] = "unbound"
            devices = self.user_devices.get(row["user_id"], [])
            self.user_devices[row["user_id"]] = [d for d in devices if d != row["device_id"]]
            return {"ok": True, "binding_id": binding_id, "user_id": row["user_id"], "device_id": row["device_id"]}

        async def list_my_devices(self, *, wx_code: str = "", session_token: str = "") -> dict:
            user_id = self.session_users.get(session_token, "")
            device_ids = self.user_devices.get(user_id, [])
            return {
                "items": [
                    {
                        "binding_id": bid,
                        "device_id": row["device_id"],
                        "device_code": row["device_id"],
                    }
                    for bid, row in self.bindings.items()
                    if row["status"] == "active" and row["user_id"] == user_id and row["device_id"] in device_ids
                ]
            }

    with TestClient(app) as client:
        fake = FakeRepo()
        app.state.repo = fake
        headers = {"X-Admin-Token": "admin-token"}

        before = client.post("/api/devices/my", json={"session_token": "sess-a"})
        assert before.status_code == 200
        assert len(before.json()["items"]) == 1
        assert before.json()["items"][0]["device_id"] == "SX-000001"

        unbind = client.post(
            "/admin/api/bindings/unbind",
            headers=headers,
            json={"binding_id": "bind-001"},
        )
        assert unbind.status_code == 200
        assert unbind.json()["ok"] is True

        after = client.post("/api/devices/my", json={"session_token": "sess-a"})
        assert after.status_code == 200
        assert after.json()["items"] == []


def test_admin_device_list_includes_active_binding_id(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    app = create_app()

    class FakeRepo:
        async def list_devices(self, *, limit: int = 50, cursor: str = "", q: str = "") -> dict:
            return {
                "items": [
                    {
                        "device_id": "SX-000002",
                        "bound_user_id": "wx_user_b",
                        "active_binding_id": "bind-002",
                        "note": "售后备注",
                    }
                ],
                "next_cursor": "",
            }

    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        res = client.get("/admin/api/devices", headers={"X-Admin-Token": "admin-token"})

    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["active_binding_id"] == "bind-002"
    assert item["bound_user_id"] == "wx_user_b"


def test_admin_patch_note_without_claim_code(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    app = create_app()

    class FakeRepo:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def update_device_label(self, device_id: str, payload: dict) -> dict:
            self.calls.append({"device_id": device_id, **payload})
            return {"device_id": device_id}

    with TestClient(app) as client:
        fake = FakeRepo()
        app.state.repo = fake
        res = client.patch(
            "/admin/api/devices/SX-000003",
            headers={"X-Admin-Token": "admin-token"},
            json={"note": "展厅样机", "enabled": True},
        )

    assert res.status_code == 200
    assert fake.calls == [{"device_id": "SX-000003", "note": "展厅样机", "enabled": True}]
    assert "claim_code" not in fake.calls[0]


def test_admin_ui_has_note_and_unbind_helpers() -> None:
    from pathlib import Path

    server = Path("src/shuxin/voice/static/admin.html").read_text(encoding="utf-8")
    assert "saveDeviceNote" in server
    assert "clearDeviceNote" in server
    assert "active_binding_id" in server
    assert "device-card" in server
    assert "claim-code" in server
    assert "copyClaimCode" in server
    assert "更新外壳码" not in server
    assert "resetClaim" not in server
    assert "deleteDevice" not in server
