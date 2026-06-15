from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from shuxin.voice.postgres_repository import VoicePostgresRepository
from shuxin.voice.server import create_app


class FakePool:
    def __init__(self, *, fetchrow=None, fetchval=None) -> None:
        self.fetchrow_value = fetchrow
        self.fetchval_value = fetchval

    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def fetchrow(self, *_args, **_kwargs):
        return self.fetchrow_value

    async def fetchval(self, *_args, **_kwargs):
        return self.fetchval_value


def test_user_me_route_returns_factory_qa() -> None:
    app = create_app()

    class FakeRepo:
        async def get_user_profile_by_session(self, session_token: str):
            assert session_token == "app-session"
            return {
                "user_id": "wx_qa_user",
                "roles": {"factory_qa": True},
                "quota": {
                    "configured": True,
                    "remain_yuan": 12.0,
                    "used_yuan": 0.0,
                    "exhausted": False,
                    "message": "",
                },
            }

    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        response = client.post("/api/users/me", json={"session_token": "app-session"})

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "wx_qa_user"
    assert body["roles"]["factory_qa"] is True
    assert body["quota"]["remain_yuan"] == 12.0


def test_user_me_route_factory_qa_false() -> None:
    app = create_app()

    class FakeRepo:
        async def get_user_profile_by_session(self, session_token: str):
            return {
                "user_id": "wx_normal_user",
                "roles": {"factory_qa": False},
                "quota": {"configured": False, "message": ""},
            }

    with TestClient(app) as client:
        app.state.repo = FakeRepo()
        response = client.post("/api/users/me", json={"session_token": "app-session"})

    assert response.status_code == 200
    assert response.json()["roles"]["factory_qa"] is False


def test_user_me_route_requires_session_token() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/api/users/me", json={})
    assert response.status_code == 400
    assert "session_token" in response.json()["error"]


def test_get_user_profile_by_session_reads_factory_role(monkeypatch) -> None:
    repo = VoicePostgresRepository(pool=FakePool(fetchrow={"metadata": {"factory_role": "true"}}))

    async def fake_user_id_from_wechat_auth(_conn, *, session_token: str = "", wx_code: str = ""):
        assert session_token == "tok"
        return "wx_qa_user"

    async def fake_quota(_user_id: str):
        return {
            "user_id": "wx_qa_user",
            "configured": True,
            "remain_yuan": 5.0,
            "used_yuan": 0.0,
            "exhausted": False,
            "message": "",
        }

    monkeypatch.setattr(repo, "_user_id_from_wechat_auth", fake_user_id_from_wechat_auth)
    monkeypatch.setattr(repo, "get_user_quota_by_user_id", fake_quota)

    profile = asyncio.run(repo.get_user_profile_by_session("tok"))
    assert profile["user_id"] == "wx_qa_user"
    assert profile["roles"]["factory_qa"] is True
    assert profile["quota"]["remain_yuan"] == 5.0


def test_get_user_profile_by_session_factory_role_false(monkeypatch) -> None:
    repo = VoicePostgresRepository(pool=FakePool(fetchrow={"metadata": {}}))

    async def fake_user_id_from_wechat_auth(_conn, *, session_token: str = "", wx_code: str = ""):
        return "wx_user"

    async def fake_quota(_user_id: str):
        return {"user_id": "wx_user", "configured": False, "message": ""}

    monkeypatch.setattr(repo, "_user_id_from_wechat_auth", fake_user_id_from_wechat_auth)
    monkeypatch.setattr(repo, "get_user_quota_by_user_id", fake_quota)

    profile = asyncio.run(repo.get_user_profile_by_session("tok"))
    assert profile["roles"]["factory_qa"] is False
