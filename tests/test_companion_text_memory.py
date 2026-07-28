"""文字聊天：历史、Mem0 flush、18+ 门控。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from shuxin.voice.age_consent import (
    AGE_CONSENT_META_KEY,
    AGE_CONSENT_VERSION,
    age_consent_ok,
    build_age_consent_record,
)
from shuxin.voice.api.routers.text_chat import (
    TextChatPrepError,
    _assert_age_consent,
    _seed_agent_short_term,
    finalize_text_chat_billing,
    shutdown_agent,
)


def test_age_consent_version_gate() -> None:
    assert age_consent_ok({}) is False
    assert age_consent_ok({AGE_CONSENT_META_KEY: {"version": "old"}}) is False
    assert age_consent_ok(
        {AGE_CONSENT_META_KEY: build_age_consent_record()}
    )


def test_assert_age_consent_blocks() -> None:
    class _Repo:
        async def get_user_age_consent_meta(self, user_id: str):
            return {}

    with pytest.raises(TextChatPrepError) as exc:
        asyncio.run(_assert_age_consent(_Repo(), "u1"))
    assert exc.value.status_code == 403
    assert exc.value.payload["error"] == "age_consent_required"


def test_seed_agent_short_term_does_not_call_add_message() -> None:
    from shuxin.core.memory import MemoryManager

    mem = MemoryManager(data_dir=str(Path("/tmp/shuxin-test-mem-seed")))
    agent = SimpleNamespace(memory=mem)
    _seed_agent_short_term(
        agent,
        [
            {"user_text": "我叫小明", "reply_text": "你好小明"},
            {"user_text": "我住上海", "reply_text": "记下了"},
        ],
    )
    assert len(mem.short_term) == 4
    assert mem.short_term[0].content == "我叫小明"
    assert mem.short_term[-1].content == "记下了"


def test_shutdown_agent_flushes_mem0() -> None:
    calls: list[bool] = []

    class _Mem:
        def flush_deferred_mem0(self, *, force: bool = False) -> int:
            calls.append(force)
            return 1

    class _Agent:
        memory = _Mem()

        def shutdown(self) -> None:
            return None

    shutdown_agent(_Agent())
    assert calls == [True]


def test_finalize_text_chat_records_companion_channel() -> None:
    recorded: dict[str, Any] = {}

    class _Companions:
        async def record_text_turn(self, **kwargs):
            return None

        async def after_companion_turn(self, **kwargs):
            return None

        async def get_engagement_for_user(self, **kwargs):
            return {}

    class _Repo:
        companions = _Companions()

        async def deduct_device_minutes_quota(self, soft_id, cost):
            return None

        async def record_turn(self, **kwargs):
            recorded.update(kwargs)

    agent = SimpleNamespace(last_usage={"prompt_tokens": 10, "completion_tokens": 5})
    ctx = {
        "text": "你好",
        "billing_settings": {},
        "soft_id": "soft_u1",
        "user_id": "u1",
        "companion_id": "cmp_1",
        "companion": {"mbti": "INFJ"},
        "agent": agent,
        "estimate": 0.1,
        "estimate_token": 0.1,
        "estimate_typing": 0.1,
        "user_settings": SimpleNamespace(user_id="u1"),
        "session_id": "text-sess",
    }
    body = asyncio.run(finalize_text_chat_billing(_Repo(), ctx=ctx, reply="在呢"))
    assert body["reply"] == "在呢"
    assert recorded["companion_id"] == "cmp_1"
    assert recorded["channel"] == "text"
    assert recorded["user_text"] == "你好"


def test_list_companion_chat_history_filters(tmp_path: Path) -> None:
    from shuxin.voice.persistence.storage import UserVoiceStorage
    from shuxin.voice.persistence.users import UserSettings

    home = tmp_path / "home"
    out = tmp_path / "out"

    async def _run() -> list:
        storage = UserVoiceStorage(home, out, "alice")
        settings = UserSettings(user_id="alice", token="")
        await storage.record_turn(
            user_settings=settings,
            device_id="soft_alice",
            client_id="text",
            session_id="s1",
            turn_id="t1",
            user_text="A1",
            reply_text="B1",
            input_audio=None,
            reply_audio=None,
            timings={},
            companion_id="cmp_a",
            channel="text",
        )
        await storage.record_turn(
            user_settings=settings,
            device_id="soft_alice",
            client_id="text",
            session_id="s2",
            turn_id="t2",
            user_text="A2",
            reply_text="B2",
            input_audio=None,
            reply_audio=None,
            timings={},
            companion_id="cmp_b",
            channel="text",
        )
        hist_a = storage.list_companion_chat_history(companion_id="cmp_a", limit=50)
        return [m["text"] for m in hist_a["messages"]]

    texts = asyncio.run(_run())
    assert "A1" in texts and "B1" in texts
    assert "A2" not in texts
