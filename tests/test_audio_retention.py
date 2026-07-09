from __future__ import annotations

import asyncio
import shutil
import sqlite3

import pytest

from shuxin.voice.persistence.storage import UserVoiceStorage
from shuxin.voice.persistence.users import UserSettings


def test_purge_expired_audio_deletes_files_and_soft_deletes_attachments(tmp_path):
    async def run():
        storage = UserVoiceStorage(tmp_path / "home", tmp_path / "outputs", "user-001")
        settings = UserSettings(user_id="user-001", token="secret", audio_quota_mb=512)
        paths = storage.new_turn_paths("device-001", "session-001")
        storage.write_input_wav(b"\0" * 16000, paths.input_wav)
        paths.reply_mp3.write_bytes(b"reply-bytes")
        await storage.record_turn(
            user_settings=settings,
            device_id="device-001",
            client_id="client-001",
            session_id=paths.session_id,
            turn_id=paths.turn_id,
            user_text="你好",
            reply_text="你好呀",
            input_audio=paths.input_wav,
            reply_audio=paths.reply_mp3,
            timings={"total_elapsed_ms": 1},
        )
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "UPDATE attachments SET created_at = '2020-01-01T00:00:00' WHERE deleted_at IS NULL"
            )
        result = await storage.purge_expired_audio_attachments(retention_hours=12)
        return storage, paths, result

    storage, paths, result = asyncio.run(run())

    assert result["purged"] == 2
    assert result["bytes_freed"] > 0
    assert not paths.input_wav.exists()
    assert not paths.reply_mp3.exists()

    with sqlite3.connect(storage.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM events WHERE deleted_at IS NULL").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT user_text, reply_text FROM events WHERE deleted_at IS NULL"
            ).fetchone()
            == ("你好", "你好呀")
        )
        active = conn.execute(
            "SELECT COUNT(*) FROM attachments WHERE deleted_at IS NULL"
        ).fetchone()[0]
        deleted = conn.execute(
            "SELECT COUNT(*) FROM attachments WHERE deleted_at IS NOT NULL"
        ).fetchone()[0]
        assert active == 0
        assert deleted == 2


def test_purge_retention_zero_is_noop(tmp_path):
    async def run():
        storage = UserVoiceStorage(tmp_path / "home", tmp_path / "outputs", "user-001")
        settings = UserSettings(user_id="user-001", token="secret", audio_quota_mb=512)
        paths = storage.new_turn_paths("device-001", "session-001")
        storage.write_input_wav(b"\0" * 16000, paths.input_wav)
        paths.reply_mp3.write_bytes(b"reply")
        await storage.record_turn(
            user_settings=settings,
            device_id="device-001",
            client_id="client-001",
            session_id=paths.session_id,
            turn_id=paths.turn_id,
            user_text="测试",
            reply_text="收到",
            input_audio=paths.input_wav,
            reply_audio=paths.reply_mp3,
            timings={"total_elapsed_ms": 1},
        )
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "UPDATE attachments SET created_at = '2020-01-01T00:00:00' WHERE deleted_at IS NULL"
            )
        result = await storage.purge_expired_audio_attachments(retention_hours=0)
        return paths, result

    paths, result = asyncio.run(run())

    assert result == {"purged": 0, "bytes_freed": 0}
    assert paths.input_wav.exists()
    assert paths.reply_mp3.exists()


def test_compress_if_needed_still_works_after_purge_api_exists(tmp_path):
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
        return paths, await storage.compress_if_needed(settings)

    paths, result = asyncio.run(run())

    assert result["compressed"] >= 1
    assert not paths.input_wav.exists()
    assert paths.input_wav.with_suffix(".mp3").exists()
