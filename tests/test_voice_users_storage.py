from __future__ import annotations

import asyncio
import shutil
import sqlite3

import pytest

from shuxin.voice.config import ProviderConfig
from shuxin.voice.providers import create_stt_provider, create_tts_provider
from shuxin.voice.storage import UserVoiceStorage
from shuxin.voice.users import UserConfigProvider, UserSettings


def test_user_config_auth_and_quota_reload(tmp_path):
    config = tmp_path / "users.yaml"
    config.write_text(
        """
defaults:
  audio_quota_mb: 5
users:
  user-001:
    token: secret
    audio_quota_mb: 7
""",
        encoding="utf-8",
    )
    provider = UserConfigProvider(config)

    settings = provider.authenticate("user-001", "secret")

    assert settings.user_id == "user-001"
    assert settings.audio_quota_mb == 7
    with pytest.raises(PermissionError):
        provider.authenticate("user-001", "bad")


def test_fake_voice_providers(tmp_path):
    async def run():
        stt = create_stt_provider(ProviderConfig(type="fake", model="你好"))
        tts = create_tts_provider(ProviderConfig(type="fake"))
        text = await stt.transcribe(tmp_path / "missing.wav")
        output = await tts.synthesize("回复", tmp_path / "reply.mp3")
        return text, output.read_bytes()

    text, payload = asyncio.run(run())

    assert text == "你好"
    assert payload.startswith(b"FAKE_MP3:")


def test_storage_records_turn_summary_and_facts(tmp_path):
    async def run():
        storage = UserVoiceStorage(tmp_path / "home", tmp_path / "outputs", "user-001")
        settings = UserSettings(user_id="user-001", token="secret", audio_quota_mb=1)
        paths = storage.new_turn_paths("device-001", "session-001")
        storage.write_input_wav(b"\0" * 16000, paths.input_wav)
        paths.reply_mp3.write_bytes(b"reply")
        await storage.record_turn(
            user_settings=settings,
            device_id="device-001",
            client_id="client-001",
            session_id=paths.session_id,
            turn_id=paths.turn_id,
            user_text="我喜欢苹果",
            reply_text="我记住了",
            input_audio=paths.input_wav,
            reply_audio=paths.reply_mp3,
            timings={"total_elapsed_ms": 1},
        )
        return storage, await storage.status(settings)

    storage, status = asyncio.run(run())

    assert status["audio_used_bytes"] > 0
    assert storage.export_summary()["turn_count"] == 1
    facts = (storage.memory_dir / "facts.json").read_text(encoding="utf-8")
    assert "苹果" in facts

    with sqlite3.connect(storage.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 2


def test_storage_compresses_old_wav_when_ffmpeg_available(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")

    async def run():
        storage = UserVoiceStorage(tmp_path / "home", tmp_path / "outputs", "user-001")
        settings = UserSettings(user_id="user-001", token="secret", audio_quota_mb=1)
        paths = storage.new_turn_paths("device-001", "session-001")
        storage.write_input_wav(b"\0" * 16000 * 80, paths.input_wav)
        paths.reply_mp3.write_bytes(b"reply")
        await storage.record_turn(
            user_settings=settings,
            device_id="device-001",
            client_id="client-001",
            session_id=paths.session_id,
            turn_id=paths.turn_id,
            user_text="你好",
            reply_text="你好",
            input_audio=paths.input_wav,
            reply_audio=paths.reply_mp3,
            timings={"total_elapsed_ms": 1},
        )
        tiny_quota = UserSettings(user_id="user-001", token="secret", audio_quota_mb=1)
        result = await storage.compress_if_needed(tiny_quota)
        return paths, result

    paths, result = asyncio.run(run())

    assert result["compressed"] >= 1
    assert not paths.input_wav.exists()
    assert paths.input_wav.with_suffix(".mp3").exists()
