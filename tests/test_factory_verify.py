from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from shuxin.voice.mbti_reveal import build_factory_verify_mbti_payload
from shuxin.voice.postgres_repository import VoicePostgresRepository
from shuxin.voice.server import create_app, _FACTORY_ACCEPTANCE_DISABLED
from shuxin.voice import voice_session_registry as vsr
from shuxin.voice.users import FACTORY_PROBE_USER_ID, UserSettings


class FakePool:
    def __init__(self, *, fetchrow=None, fetch_rows=None, execute_result: str = "DELETE 0") -> None:
        self.fetchrow_value = fetchrow
        self.fetch_rows = fetch_rows or []
        self.execute_result = execute_result
        self.executed: list[tuple] = []
        self.fetched: list[tuple] = []

    async def fetchrow(self, *_args, **_kwargs):
        return self.fetchrow_value

    async def fetch(self, query, *args):
        self.fetched.append((query, args))
        return self.fetch_rows

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return self.execute_result


def test_build_factory_verify_mbti_payload_includes_status() -> None:
    payload = build_factory_verify_mbti_payload(
        {"mbti": "INFJ", "mbti_status": "sealed"},
    )
    assert payload is not None
    assert payload["mbti"] == "INFJ"
    assert payload["display_name"]
    assert payload["tagline"]
    assert payload["mbti_status"] == "sealed"


def test_build_factory_verify_mbti_payload_missing_mbti() -> None:
    assert build_factory_verify_mbti_payload({"mbti_status": "sealed"}) is None


def test_factory_verify_pass_includes_mbti(monkeypatch) -> None:
    device_id = "SX-000116"
    vsr.reset_for_tests()

    async def fake_send_json(msg: dict) -> None:
        if msg.get("type") == "factory_verify":
            vsr.factory_verify_ack(device_id)

    session = SimpleNamespace(_send_json=AsyncMock(side_effect=fake_send_json))
    vsr.register(device_id, session)

    lookup = {
        "device_id": device_id,
        "claim_code_status": "active",
        "metadata": {"mbti": "INFJ", "mbti_status": "sealed"},
        "mbti": "INFJ",
        "mbti_status": "sealed",
    }

    class FakeRepo:
        async def factory_verify_user_has_role(self, session_token: str) -> str:
            if session_token != "qa-token":
                raise PermissionError("user does not have factory_role")
            return "qa-user"

        async def factory_verify_lookup(self, claim_code: str) -> dict:
            assert claim_code == "CLM-A001-0116"
            return lookup

        async def factory_verify_log(self, **kwargs) -> None:
            assert kwargs["result"] == "PASS"
            assert kwargs["meta"]["mbti"] == "INFJ"

    app = create_app()
    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        res = client.post(
            "/api/factory/verify",
            json={"session_token": "qa-token", "claim_code": "CLM-A001-0116"},
        )

    assert res.status_code == 200
    body = res.json()
    assert body["result"] == "PASS"
    assert body["device_id"] == device_id
    assert body["mbti"]["mbti"] == "INFJ"
    assert body["mbti"]["mbti_status"] == "sealed"
    vsr.reset_for_tests()


def test_factory_verify_requires_factory_role() -> None:
    class FakeRepo:
        async def factory_verify_user_has_role(self, session_token: str) -> str:
            raise PermissionError("user does not have factory_role")

    app = create_app()
    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        res = client.post(
            "/api/factory/verify",
            json={"session_token": "bad", "claim_code": "CLM-A001-0001"},
        )

    assert res.status_code == 403
    assert "factory_role" in res.json()["error"]


def test_authenticate_device_for_factory_ok(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_DEVICE_SHARED_SECRET", "secret-abc")
    row = {
        "device_id": "SX-000116",
        "auth_mode": "shared_secret",
        "device_secret_hash": None,
        "status": "provisioned",
        "has_active_binding": False,
    }
    repo = VoicePostgresRepository(pool=FakePool(fetchrow=row))

    async def run() -> UserSettings:
        return await repo.authenticate_device_for_factory("SX-000116", "secret-abc")

    settings = asyncio.run(run())
    assert settings.user_id == FACTORY_PROBE_USER_ID
    assert settings.llm_config == {}
    assert settings.agent_id == ""


def test_authenticate_device_for_factory_rejects_bound(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_DEVICE_SHARED_SECRET", "secret-abc")
    row = {
        "device_id": "SX-000116",
        "auth_mode": "shared_secret",
        "device_secret_hash": None,
        "status": "provisioned",
        "has_active_binding": True,
    }
    repo = VoicePostgresRepository(pool=FakePool(fetchrow=row))

    async def run() -> None:
        await repo.authenticate_device_for_factory("SX-000116", "secret-abc")

    with pytest.raises(PermissionError, match="already bound"):
        asyncio.run(run())


def test_factory_hello_unbound_skips_reveal_and_ensure_session() -> None:
    device_id = "SX-000116"
    vsr.reset_for_tests()
    mock_ensure_session = AsyncMock()
    mock_try_reveal = AsyncMock(return_value=None)

    class FakeRepo:
        async def authenticate_device(self, device_code: str, device_secret: str) -> UserSettings:
            raise PermissionError("device is not bound or disabled")

        async def authenticate_device_for_factory(
            self,
            device_code: str,
            device_secret: str,
        ) -> UserSettings:
            assert device_code == device_id
            assert device_secret == "secret-abc"
            return UserSettings(user_id=FACTORY_PROBE_USER_ID, llm_config={}, agent_id="")

        async def ensure_session(self, **kwargs) -> None:
            await mock_ensure_session(**kwargs)

        async def touch_device_status(self, **kwargs) -> None:
            assert kwargs["device_id"] == device_id
            assert kwargs["online"] is True

        async def try_reveal_and_lock(self, device_id: str, revealed_by: str):
            return await mock_try_reveal(device_id, revealed_by)

    app = create_app()
    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        with client.websocket_connect("/ws/voice") as ws:
            ready = ws.receive_json()
            assert ready["state"] == "ready"
            ws.send_json(
                {
                    "type": "hello",
                    "device_code": device_id,
                    "device_secret": "secret-abc",
                    "client_id": "factory-hw",
                }
            )
            hello_ok = ws.receive_json()
            assert hello_ok["state"] == "ok"
            assert hello_ok["factory_acceptance"] is True
            assert hello_ok["device_id"] == device_id

    mock_ensure_session.assert_not_called()
    mock_try_reveal.assert_not_called()
    vsr.reset_for_tests()


def test_factory_hello_then_verify_pass() -> None:
    device_id = "SX-000116"
    vsr.reset_for_tests()

    class FakeRepo:
        async def authenticate_device(self, device_code: str, device_secret: str) -> UserSettings:
            raise PermissionError("device is not bound or disabled")

        async def authenticate_device_for_factory(
            self,
            device_code: str,
            device_secret: str,
        ) -> UserSettings:
            return UserSettings(user_id=FACTORY_PROBE_USER_ID, llm_config={}, agent_id="")

        async def touch_device_status(self, **kwargs) -> None:
            return None

        async def factory_verify_user_has_role(self, session_token: str) -> str:
            return "qa-user"

        async def factory_verify_lookup(self, claim_code: str) -> dict:
            return {
                "device_id": device_id,
                "claim_code_status": "active",
                "metadata": {"mbti": "INFJ", "mbti_status": "sealed"},
                "mbti": "INFJ",
                "mbti_status": "sealed",
            }

        async def factory_verify_log(self, **kwargs) -> None:
            return None

    app = create_app()
    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        with client.websocket_connect("/ws/voice") as ws:
            ws.receive_json()
            ws.send_json(
                {
                    "type": "hello",
                    "device_code": device_id,
                    "device_secret": "secret-abc",
                }
            )
            hello_ok = ws.receive_json()
            assert hello_ok.get("factory_acceptance") is True

            session = vsr.get_active_session(device_id)
            assert session is not None
            original_send_json = session._send_json

            async def send_json_with_auto_ack(data: dict) -> None:
                await original_send_json(data)
                if data.get("type") == "factory_verify":
                    vsr.factory_verify_ack(device_id)

            session._send_json = send_json_with_auto_ack

            res = client.post(
                "/api/factory/verify",
                json={"session_token": "qa-token", "claim_code": "CLM-A001-0116"},
            )
            assert res.status_code == 200
            body = res.json()
            assert body["result"] == "PASS"
            assert body["mbti"]["mbti"] == "INFJ"

    vsr.reset_for_tests()


def test_purge_expired_factory_verify_logs_noop_when_zero() -> None:
    pool = FakePool(execute_result="DELETE 5")
    repo = VoicePostgresRepository(pool=pool)

    async def run() -> dict[str, int]:
        return await repo.purge_expired_factory_verify_logs(retention_days=0)

    assert asyncio.run(run()) == {"purged": 0}
    assert pool.executed == []


def test_purge_expired_factory_verify_logs_deletes_old_rows() -> None:
    pool = FakePool(execute_result="DELETE 2")
    repo = VoicePostgresRepository(pool=pool)

    async def run() -> dict[str, int]:
        return await repo.purge_expired_factory_verify_logs(retention_days=15)

    result = asyncio.run(run())
    assert result == {"purged": 2}
    assert len(pool.executed) == 1
    query, args = pool.executed[0]
    assert "DELETE FROM factory_verify_logs" in query
    assert args == (15,)


def test_factory_verify_logs_list_applies_retention_filter() -> None:
    from datetime import datetime, timezone

    pool = FakePool(
        fetch_rows=[
            {
                "verify_id": "v1",
                "claim_code": "CLM-1",
                "device_id": "SX-1",
                "operator_user": "qa",
                "result": "PASS",
                "fail_reason": "",
                "verified_at": datetime.now(timezone.utc),
                "meta": {},
            }
        ]
    )
    repo = VoicePostgresRepository(pool=pool)

    async def run() -> list[dict]:
        return await repo.factory_verify_logs_list(
            operator_user="qa",
            retention_days=15,
            limit=20,
        )

    logs = asyncio.run(run())
    assert len(logs) == 1
    assert logs[0]["verify_id"] == "v1"
    query, args = pool.fetched[0]
    assert "make_interval(days => $3)" in query
    assert args == ("qa", "", 15, 20)


def test_factory_verify_logs_list_skips_retention_when_zero() -> None:
    pool = FakePool(fetch_rows=[])
    repo = VoicePostgresRepository(pool=pool)

    async def run() -> list[dict]:
        return await repo.factory_verify_logs_list(retention_days=0, limit=10)

    assert asyncio.run(run()) == []
    query, args = pool.fetched[0]
    assert "make_interval" not in query
    assert args == ("", "", 10)


def test_factory_listen_rejected() -> None:
    device_id = "SX-000116"
    vsr.reset_for_tests()

    class FakeRepo:
        async def authenticate_device(self, device_code: str, device_secret: str) -> UserSettings:
            raise PermissionError("device is not bound or disabled")

        async def authenticate_device_for_factory(
            self,
            device_code: str,
            device_secret: str,
        ) -> UserSettings:
            return UserSettings(user_id=FACTORY_PROBE_USER_ID, llm_config={}, agent_id="")

        async def touch_device_status(self, **kwargs) -> None:
            return None

    app = create_app()
    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        with client.websocket_connect("/ws/voice") as ws:
            ws.receive_json()
            ws.send_json(
                {
                    "type": "hello",
                    "device_code": device_id,
                    "device_secret": "secret-abc",
                }
            )
            hello_ok = ws.receive_json()
            assert hello_ok.get("factory_acceptance") is True
            ws.send_json({"type": "listen", "state": "start"})
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["message"] == _FACTORY_ACCEPTANCE_DISABLED

    vsr.reset_for_tests()
