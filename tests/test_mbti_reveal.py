from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from shuxin.core.identity import IdentityEngine, load_mbti_profiles
from shuxin.voice.config.config import DeviceConfig
from shuxin.voice.config.mbti_reveal import MBTI_STATUS_LOCKED, MBTI_STATUS_SEALED, needs_mbti_reveal
from shuxin.voice.api.ws_session import _VoiceWebSocketSession
from shuxin.voice.server import create_app

REPO = Path("src/shuxin/voice/persistence/postgres_repository.py")

class VoiceSourceAggregator:
    def read_text(self, encoding="utf-8"):
        parts = []
        for path in [
            Path("src/shuxin/voice/server.py"),
            Path("src/shuxin/voice/api/routers/admin.py"),
            Path("src/shuxin/voice/api/routers/user.py"),
            Path("src/shuxin/voice/api/routers/factory.py"),
            Path("src/shuxin/voice/api/routers/payment.py"),
            Path("src/shuxin/voice/api/ws_session.py"),
            Path("src/shuxin/voice/static/admin.html"),
        ]:
            if path.exists():
                text = path.read_text(encoding=encoding)
                if path.name == "admin.py":
                    text = text.replace('@router.get("', '@router.get("/admin/api')
                    text = text.replace('@router.post("', '@router.post("/admin/api')
                    text = text.replace('@router.patch("', '@router.patch("/admin/api')
                    text = text.replace('@router.delete("', '@router.delete("/admin/api')
                parts.append(text)
        return "\n".join(parts)

SERVER = VoiceSourceAggregator()


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"mbti": "INFJ", "mbti_status": MBTI_STATUS_SEALED}, True),
        ({"mbti": "INFJ", "mbti_status": MBTI_STATUS_LOCKED}, False),
        ({"mbti": "INFJ"}, False),
        ({"mbti_status": MBTI_STATUS_SEALED}, False),
        ({"mbti": "XXXX", "mbti_status": MBTI_STATUS_SEALED}, False),
        (None, False),
    ],
)
def test_needs_mbti_reveal(metadata, expected) -> None:
    assert needs_mbti_reveal(metadata) is expected


def test_batch_provision_writes_sealed_status() -> None:
    source = Path("src/shuxin/voice/persistence/device_repo.py").read_text(encoding="utf-8")
    assert '"mbti_status": "sealed"' in source
    assert "blind_mbti = random.choice" in source


def test_update_device_mbti_does_not_touch_status() -> None:
    source = Path("src/shuxin/voice/persistence/mbti_repo.py").read_text(encoding="utf-8")
    start = source.index("async def update_device_mbti")
    end = source.index("async def mark_mbti_locked")
    block = source[start:end]
    assert "mbti_status" not in block
    assert "jsonb_build_object('mbti', $2::text)" in block


def test_admin_mbti_routes_and_ui_present() -> None:
    server = SERVER.read_text(encoding="utf-8")
    assert "/admin/api/devices/{device_id}/mbti" in server
    assert "/admin/api/mbti/types" in server
    assert "saveDeviceMbti" in server
    assert "loadMbtiTypes" in server
    assert 'field-label">MBTI</span>' in server


def test_admin_list_mbti_types_returns_16(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    app = create_app()

    with TestClient(app) as client:
        forbidden = client.get("/admin/api/mbti/types")
        ok = client.get("/admin/api/mbti/types", headers={"X-Admin-Token": "admin-token"})

    assert forbidden.status_code != 200
    assert ok.status_code == 200
    items = ok.json()["items"]
    assert len(items) == 16
    assert items[0]["type"] in load_mbti_profiles()


def test_admin_patch_mbti_delegates_to_repo(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_ADMIN_TOKEN", "admin-token")
    app = create_app()

    class FakeRepo:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def update_device_mbti(self, device_id: str, payload: dict):
            self.calls.append((device_id, payload))
            return {"device_id": device_id, "mbti": payload["mbti"]}

    with TestClient(app) as client:
        fake = FakeRepo()
        app.state.repo = fake
        res = client.patch(
            "/admin/api/devices/SX-000001/mbti",
            headers={"X-Admin-Token": "admin-token"},
            json={"mbti": "ENFP"},
        )

    assert res.status_code == 200
    assert res.json() == {"device_id": "SX-000001", "mbti": "ENFP"}
    assert fake.calls == [("SX-000001", {"mbti": "ENFP"})]


def _make_session(repo, device: DeviceConfig) -> _VoiceWebSocketSession:
    session = _VoiceWebSocketSession(
        websocket=SimpleNamespace(),
        service=SimpleNamespace(),
        repo=repo,
        shuxin_home=Path("/tmp"),
        default_device_id=device.device_id,
        out_dir=Path("/tmp"),
    )
    session.device_id = device.device_id
    session.device = device
    session.sent: list[dict] = []

    async def capture(payload: dict) -> None:
        session.sent.append(payload)

    session._send_json = capture  # type: ignore[method-assign]
    session._ensure_runtime = AsyncMock()  # type: ignore[method-assign]
    session._play_proactive_tts = AsyncMock()  # type: ignore[method-assign]
    return session


def test_maybe_reveal_on_hello_sealed_plays_once(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_VOICE_E2E_SKIP_TTS", "1")
    device = DeviceConfig(
        device_id="SX-000099",
        metadata={"mbti": "INFJ", "mbti_status": MBTI_STATUS_SEALED},
    )
    reveal_payload = {
        "is_first_reveal": True,
        "mbti": "INFJ",
        "display_name": "提倡者",
        "tagline": "安静而神秘",
    }
    repo = SimpleNamespace(
        get_device=AsyncMock(return_value=device),
        try_reveal_and_lock=AsyncMock(return_value=reveal_payload),
        mark_device_intro_played=AsyncMock(return_value={"device_intro_played": True}),
    )
    session = _make_session(repo, device)

    asyncio.run(session._maybe_reveal_mbti_on_hello())

    types = [msg["type"] for msg in session.sent]
    assert "mbti/reveal" in types
    assert any(msg.get("type") == "agent" and msg.get("state") == "reply" for msg in session.sent)
    repo.try_reveal_and_lock.assert_awaited_once_with(device.device_id, "first_hello")
    repo.mark_device_intro_played.assert_awaited_once_with(device.device_id)
    assert session.device.metadata["device_intro_played"] is True
    played_text = session._play_proactive_tts.await_args.args[0]
    assert not played_text.startswith("绑定成功。")
    session._play_proactive_tts.assert_awaited_once()


def test_maybe_reveal_on_hello_locked_plays_pending_intro(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_VOICE_E2E_SKIP_TTS", "1")
    device = DeviceConfig(
        device_id="SX-000100",
        metadata={
            "mbti": "INFJ",
            "mbti_status": MBTI_STATUS_LOCKED,
            "device_intro_played": False,
        },
    )
    repo = SimpleNamespace(
        get_device=AsyncMock(return_value=device),
        try_reveal_and_lock=AsyncMock(),
        mark_device_intro_played=AsyncMock(return_value={"device_intro_played": True}),
    )
    session = _make_session(repo, device)

    asyncio.run(session._maybe_reveal_mbti_on_hello())

    assert "mbti/reveal" not in [msg["type"] for msg in session.sent]
    assert any(msg.get("type") == "agent" for msg in session.sent)
    repo.try_reveal_and_lock.assert_not_awaited()
    repo.mark_device_intro_played.assert_awaited_once()
    played_text = session._play_proactive_tts.await_args.args[0]
    assert "绑定成功" in played_text
    session._play_proactive_tts.assert_awaited_once()


def test_maybe_reveal_on_hello_locked_skips_when_intro_played(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_VOICE_E2E_SKIP_TTS", "1")
    device = DeviceConfig(
        device_id="SX-000101",
        metadata={
            "mbti": "INFJ",
            "mbti_status": MBTI_STATUS_LOCKED,
            "device_intro_played": True,
        },
    )
    repo = SimpleNamespace(
        get_device=AsyncMock(return_value=device),
        try_reveal_and_lock=AsyncMock(),
        mark_device_intro_played=AsyncMock(),
    )
    session = _make_session(repo, device)

    asyncio.run(session._maybe_reveal_mbti_on_hello())

    assert session.sent == []
    repo.mark_device_intro_played.assert_not_awaited()


def test_maybe_reveal_legacy_mbti_without_status_plays_intro_once() -> None:
    device = DeviceConfig(device_id="SX-legacy", metadata={"mbti": "ISTJ"})
    repo = SimpleNamespace(
        get_device=AsyncMock(return_value=device),
        try_reveal_and_lock=AsyncMock(),
        mark_device_intro_played=AsyncMock(return_value={"device_intro_played": True}),
    )
    session = _make_session(repo, device)

    asyncio.run(session._maybe_reveal_mbti_on_hello())

    assert any(msg.get("type") == "agent" for msg in session.sent)
    repo.try_reveal_and_lock.assert_not_awaited()
    repo.mark_device_intro_played.assert_awaited_once()
