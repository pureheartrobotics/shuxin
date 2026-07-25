"""User profile avatar + nickname APIs and Qiniu delete helpers."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def _qiniu_env(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "t")
    monkeypatch.setenv("SHUXIN_QINIU_ACCESS_KEY", "ak")
    monkeypatch.setenv("SHUXIN_QINIU_SECRET_KEY", "sk-secret")
    monkeypatch.setenv("SHUXIN_QINIU_BUCKET", "bucket")
    monkeypatch.setenv("SHUXIN_QINIU_CDN_DOMAIN", "cdn.example.com")


def test_public_url_with_version(monkeypatch) -> None:
    _qiniu_env(monkeypatch)
    from shuxin.voice.cdn.qiniu import public_url_with_version

    url = public_url_with_version("zzx_xcx/ugc/u1/avatar.webp", "2026-07-24T00:00:00Z")
    assert url.startswith("https://cdn.example.com/zzx_xcx/ugc/u1/avatar.webp")
    assert "v=" in url


def test_encoded_entry_and_auth_shape() -> None:
    from shuxin.voice.cdn.qiniu_delete import (
        build_management_authorization,
        encoded_entry_uri,
    )

    entry = encoded_entry_uri("bucket", "zzx_xcx/ugc/u1/avatar.webp")
    assert entry
    auth = build_management_authorization(
        access_key="ak",
        secret_key="sk",
        method="POST",
        path="/delete/%s" % entry,
        host="rs.qiniuapi.com",
    )
    assert auth.startswith("Qiniu ak:")
    assert "sk" not in auth.split(":", 1)[0]


def test_delete_object_treats_612_as_ok(monkeypatch) -> None:
    _qiniu_env(monkeypatch)
    import urllib.error

    from shuxin.voice.cdn import qiniu_delete

    def _raise(*_a, **_k):
        raise urllib.error.HTTPError(
            url="https://rs.qiniuapi.com/delete/x",
            code=612,
            msg="no such file",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(qiniu_delete.urllib.request, "urlopen", _raise)
    out = qiniu_delete.delete_object("zzx_xcx/ugc/u1/avatar.webp")
    assert out["ok"] is True
    assert out["status"] == 612


def test_user_upload_token_and_profile_flow(monkeypatch) -> None:
    _qiniu_env(monkeypatch)
    from shuxin.voice.server import create_app

    class FakeRepo:
        def __init__(self):
            self.meta = {"nickname": "", "avatar_key": ""}

        async def get_user_profile_by_session(self, session_token: str):
            assert session_token == "sess"
            from shuxin.voice.cdn.qiniu import public_url_with_version
            from shuxin.voice.cdn.purposes import resolve_key

            key = self.meta.get("avatar_key") or ""
            return {
                "user_id": "wx_u1",
                "nickname": self.meta.get("nickname") or "",
                "avatar_key": key,
                "avatar_url": public_url_with_version(key, "v1") if key else "",
                "roles": {"factory_qa": False},
                "quota": {"configured": False},
            }

        async def update_user_profile_by_session(
            self, session_token: str, *, nickname=None, avatar_key=None
        ):
            if nickname is not None:
                self.meta["nickname"] = str(nickname or "").strip()
            if avatar_key is not None:
                from shuxin.voice.cdn.purposes import resolve_key

                expected = resolve_key("ugc_avatar", user_id="wx_u1")
                key = str(avatar_key or "").strip()
                if key and key != expected:
                    raise ValueError("avatar_key does not belong to this user")
                self.meta["avatar_key"] = key
            return await self.get_user_profile_by_session(session_token)

        async def clear_user_avatar_by_session(self, session_token: str):
            self.meta["avatar_key"] = ""
            out = await self.get_user_profile_by_session(session_token)
            out["cdn_delete"] = {"ok": True, "status": 612}
            return out

    app = create_app()
    repo = FakeRepo()
    with TestClient(app) as client:
        client.app.state.repo = repo
        bad = client.post(
            "/api/users/upload-token",
            json={"session_token": "sess", "purpose": "mall_product_cover"},
        )
        assert bad.status_code == 400

        tok = client.post(
            "/api/users/upload-token",
            json={"session_token": "sess", "purpose": "ugc_avatar"},
        )
        assert tok.status_code == 200
        body = tok.json()
        assert body["key"] == "zzx_xcx/ugc/wx_u1/avatar.webp"
        assert "sk-secret" not in tok.text

        upd = client.post(
            "/api/users/profile",
            json={
                "session_token": "sess",
                "nickname": "小明",
                "avatar_key": body["key"],
            },
        )
        assert upd.status_code == 200
        assert upd.json()["nickname"] == "小明"
        assert upd.json()["avatar_url"]

        wrong = client.post(
            "/api/users/profile",
            json={"session_token": "sess", "avatar_key": "evil/path.webp"},
        )
        assert wrong.status_code == 400

        cleared = client.post(
            "/api/users/avatar/clear",
            json={"session_token": "sess"},
        )
        assert cleared.status_code == 200
        assert cleared.json()["avatar_url"] == ""
        assert cleared.json()["cdn_delete"]["ok"] is True


def test_users_me_includes_nickname_fields(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "t")
    from shuxin.voice.server import create_app

    class FakeRepo:
        async def get_user_profile_by_session(self, session_token: str):
            return {
                "user_id": "wx_me",
                "nickname": "阿初",
                "avatar_url": "https://cdn.example.com/a.webp?v=1",
                "avatar_key": "zzx_xcx/ugc/wx_me/avatar.webp",
                "roles": {"factory_qa": False},
                "quota": {"configured": True, "remain_yuan": 1.0},
            }

    app = create_app()
    with TestClient(app) as client:
        client.app.state.repo = FakeRepo()
        res = client.post("/api/users/me", json={"session_token": "s"})
    assert res.status_code == 200
    body = res.json()
    assert body["nickname"] == "阿初"
    assert "avatar_url" in body
