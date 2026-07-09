from __future__ import annotations

from pathlib import Path

from shuxin.voice.config.mbti_reveal import (
    MBTI_STATUS_LOCKED,
    MBTI_STATUS_SEALED,
    build_device_intro_text,
    build_mbti_client_payload,
    is_mbti_locked,
    needs_device_intro,
    sanitize_device_metadata_for_client,
)

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
INDEX = Path("apps/wechat-miniprogram/src/pages/index/index.vue")


def test_build_device_intro_text_prefix() -> None:
    text = build_device_intro_text("ENFP", bind_success_prefix=True)
    assert text == "你好！绑定成功，我是 ENFP 型的初心。"


def test_build_mbti_client_payload_first_reveal() -> None:
    payload = build_mbti_client_payload(
        {"mbti": "INFJ", "mbti_status": MBTI_STATUS_SEALED},
        is_first_reveal=True,
    )
    assert payload is not None
    assert payload["is_first_reveal"] is True
    assert payload["mbti"] == "INFJ"
    assert payload["display_name"] == "提倡者"
    assert payload["tagline"]


def test_sanitize_hides_sealed_mbti() -> None:
    sanitized = sanitize_device_metadata_for_client(
        {"mbti": "INFJ", "mbti_status": MBTI_STATUS_SEALED, "provisioned_by": "admin_batch"}
    )
    assert "mbti" not in sanitized
    assert sanitized["mbti_status"] == MBTI_STATUS_SEALED


def test_sanitize_locked_returns_card_fields() -> None:
    sanitized = sanitize_device_metadata_for_client(
        {
            "mbti": "ENFP",
            "mbti_status": MBTI_STATUS_LOCKED,
            "reveal_script": "secret",
            "device_intro_played": False,
        }
    )
    assert sanitized["mbti"] == "ENFP"
    assert sanitized["display_name"] == "竞选者"
    assert sanitized["tagline"]
    assert "reveal_script" not in sanitized
    assert "device_intro_played" not in sanitized


def test_needs_device_intro_when_locked_and_not_played() -> None:
    metadata = {
        "mbti": "ISTJ",
        "mbti_status": MBTI_STATUS_LOCKED,
        "device_intro_played": False,
    }
    assert is_mbti_locked(metadata)
    assert needs_device_intro(metadata)


def test_needs_device_intro_false_after_played() -> None:
    metadata = {
        "mbti": "ISTJ",
        "mbti_status": MBTI_STATUS_LOCKED,
        "device_intro_played": True,
    }
    assert not needs_device_intro(metadata)


def test_bind_attach_reveal_helpers_present() -> None:
    source = Path("src/shuxin/voice/persistence/mbti_repo.py").read_text(encoding="utf-8")
    assert "_attach_mbti_reveal_on_bind" in source
    assert "_try_reveal_and_lock_conn" in source
    assert "device_intro_played" in source
    assert "miniprogram_bind" in source


def test_hello_intro_playback_present() -> None:
    server = SERVER.read_text(encoding="utf-8")
    assert "needs_device_intro" in server
    assert "play_pending_device_intro" in server
    assert "build_device_intro_text" in server
    assert "maybe_push_intro_after_bind" in server
    assert "mark_device_intro_played" in server


def test_miniprogram_modal_and_no_unbind() -> None:
    index = INDEX.read_text(encoding="utf-8")
    assert "revealMbti" in index
    assert "unbindDevice" not in index
    assert "解绑" not in index
