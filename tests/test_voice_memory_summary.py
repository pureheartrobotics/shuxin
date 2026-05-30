from __future__ import annotations

import asyncio
import json

import pytest

from shuxin.core.config import Config
from shuxin.voice.memory_summary import (
    apply_turn_to_summary,
    memory_field_defaults,
    should_merge_summary,
    summary_every_n,
)
from shuxin.voice.storage import UserVoiceStorage
from shuxin.voice.users import UserSettings


def test_memory_field_defaults_present():
    fields = memory_field_defaults()
    assert fields["summary_window_days"] == 7
    assert fields["turns_since_summary"] == 0
    assert fields["recent_topics"] == []


def test_apply_turn_increments_counter_and_topics():
    summary = {**memory_field_defaults(), "recent_topics": []}
    updated = apply_turn_to_summary(summary, "我最近工作压力很大，想聊聊放松")
    assert updated["turns_since_summary"] == 1
    assert updated["recent_topics"]


def test_should_merge_after_every_n():
    n = summary_every_n()
    summary = {**memory_field_defaults(), "turns_since_summary": n}
    assert should_merge_summary(summary, force=False) is True
    assert should_merge_summary(summary, force=True) is True
    summary["turns_since_summary"] = n - 1
    assert should_merge_summary(summary, force=False) is False


def test_config_default_max_history_is_30():
    assert Config().max_history == 30


def test_storage_record_turn_keeps_memory_fields(tmp_path):
    async def run():
        storage = UserVoiceStorage(tmp_path / "home", tmp_path / "outputs", "user-001")
        settings = UserSettings(user_id="user-001", token="secret", audio_quota_mb=5)
        paths = storage.new_turn_paths("device-001", "session-001")
        paths.reply_mp3.write_bytes(b"reply")
        await storage.record_turn(
            user_settings=settings,
            device_id="device-001",
            client_id="client-001",
            session_id=paths.session_id,
            turn_id=paths.turn_id,
            user_text="我喜欢夜跑",
            reply_text="记住了",
            input_audio=None,
            reply_audio=paths.reply_mp3,
            timings={"total_elapsed_ms": 1},
        )
        return storage.export_summary()

    summary = asyncio.run(run())
    assert summary["turn_count"] == 1
    assert summary["turns_since_summary"] == 1
    assert summary["summary_window_days"] == 7


def test_storage_merge_every_five_turns_and_sync_json(tmp_path, monkeypatch):
    monkeypatch.setenv("SHUXIN_SUMMARY_EVERY_N", "5")

    async def run():
        storage = UserVoiceStorage(tmp_path / "home", tmp_path / "outputs", "user-001")
        settings = UserSettings(user_id="user-001", token="secret", audio_quota_mb=5)
        for index in range(5):
            paths = storage.new_turn_paths("device-001", "session-001")
            paths.reply_mp3.write_bytes(b"reply")
            await storage.record_turn(
                user_settings=settings,
                device_id="device-001",
                client_id="client-001",
                session_id=paths.session_id,
                turn_id=paths.turn_id,
                user_text=f"关于话题{index}今天怎么样",
                reply_text=f"回复{index}",
                input_audio=None,
                reply_audio=paths.reply_mp3,
                timings={"total_elapsed_ms": 1},
            )
        result = await storage.maybe_merge_rolling_summary(None, force=False)
        summary = storage.export_summary()
        synced = json.loads(
            (tmp_path / "home" / "users" / "user-001" / "summaries" / "shared_memory.json").read_text(
                encoding="utf-8"
            )
        )
        return result, summary, synced

    monkeypatch.setattr(
        "shuxin.voice.storage.merge_summary_with_llm",
        lambda **_kwargs: "合并后的七日摘要",
    )
    result, summary, synced = asyncio.run(run())

    assert result["merged"] is True
    assert summary["rolling_summary"] == "合并后的七日摘要"
    assert summary["turns_since_summary"] == 0
    assert summary["summary_updated_at"]
    assert synced["rolling_summary"] == "合并后的七日摘要"


def test_storage_force_merge_on_disconnect_path(tmp_path, monkeypatch):
    async def run():
        storage = UserVoiceStorage(tmp_path / "home", tmp_path / "outputs", "user-001")
        settings = UserSettings(user_id="user-001", token="secret", audio_quota_mb=5)
        paths = storage.new_turn_paths("device-001", "session-001")
        paths.reply_mp3.write_bytes(b"reply")
        await storage.record_turn(
            user_settings=settings,
            device_id="device-001",
            client_id="client-001",
            session_id=paths.session_id,
            turn_id=paths.turn_id,
            user_text="你好",
            reply_text="你好呀",
            input_audio=None,
            reply_audio=paths.reply_mp3,
            timings={"total_elapsed_ms": 1},
        )
        return await storage.maybe_merge_rolling_summary(None, force=True)

    monkeypatch.setattr(
        "shuxin.voice.storage.merge_summary_with_llm",
        lambda **_kwargs: "断线摘要",
    )
    result = asyncio.run(run())
    assert result["merged"] is True
