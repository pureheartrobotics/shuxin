"""MemoryManager 单元测试（Mem0 关闭，不依赖 Qdrant）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from shuxin.core.memory import MemoryManager, _user_id_from_data_dir


@pytest.fixture(autouse=True)
def _mem0_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHUXIN_MEM0_ENABLED", "0")


def test_user_id_from_users_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "users" / "alice" / "memory"
    data_dir.mkdir(parents=True)
    assert _user_id_from_data_dir(data_dir) == "alice"


def test_user_id_default(tmp_path: Path) -> None:
    data_dir = tmp_path / "memory"
    data_dir.mkdir()
    assert _user_id_from_data_dir(data_dir) == "default"


def test_legacy_facts_summary(tmp_path: Path) -> None:
    mem = MemoryManager(data_dir=str(tmp_path / "memory"))
    mem.add_fact("名字", "小明", category="general")
    summary = mem.get_facts_summary()
    assert "小明" in summary
    assert "名字" in summary


def test_search_mem0_uses_filters_v2_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHUXIN_MEM0_ENABLED", "1")
    monkeypatch.setenv("SHUXIN_MEM0_SEARCH_TOP_K", "5")
    mem = MemoryManager(data_dir=str(tmp_path / "users" / "alice" / "memory"))

    class _FakeMem0:
        def search(self, query: str, *, filters=None, top_k=20, **kwargs):
            assert filters == {"user_id": "alice"}
            assert top_k == 5
            return {"results": [{"memory": f"hit:{query}"}]}

    mem._mem0_client = _FakeMem0()
    mem._mem0_init_attempted = True
    assert mem._search_mem0("面试") == ["hit:面试"]


def test_add_message_short_term(tmp_path: Path) -> None:
    mem = MemoryManager(data_dir=str(tmp_path / "memory"))
    mem.add_message("user", "你好")
    mem.add_message("assistant", "你好呀")
    assert len(mem.short_term) == 2
    assert "暂无可用长期记忆" in mem.get_facts_summary()
    assert "禁止声称记得" in mem.get_facts_summary()


def test_search_mem0_clips_to_top_k(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """即使 Mem0 返回 20 条，注入上限仍为 SHUXIN_MEM0_SEARCH_TOP_K。"""
    monkeypatch.setenv("SHUXIN_MEM0_ENABLED", "1")
    monkeypatch.setenv("SHUXIN_MEM0_SEARCH_TOP_K", "5")
    mem = MemoryManager(data_dir=str(tmp_path / "users" / "alice" / "memory"))

    class _FakeMem0:
        def search(self, query: str, *, filters=None, top_k=20, **kwargs):
            return {"results": [{"memory": f"fact-{i}"} for i in range(20)]}

    mem._mem0_client = _FakeMem0()
    mem._mem0_init_attempted = True
    hits = mem._search_mem0("测试")
    assert len(hits) == 5
    assert hits[0] == "fact-0"
    assert hits[4] == "fact-4"


def test_get_facts_summary_respects_top_k(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHUXIN_MEM0_ENABLED", "1")
    monkeypatch.setenv("SHUXIN_MEM0_SEARCH_TOP_K", "5")
    mem = MemoryManager(data_dir=str(tmp_path / "users" / "alice" / "memory"))

    class _FakeMem0:
        def search(self, query: str, *, filters=None, top_k=20, **kwargs):
            return {"results": [{"memory": f"fact-{i}"} for i in range(20)]}

    mem._mem0_client = _FakeMem0()
    mem._mem0_init_attempted = True
    mem.add_message("user", "面试准备")
    summary = mem.get_facts_summary()
    assert summary.count("fact-") == 5


def test_low_semantic_query_bypass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHUXIN_MEM0_ENABLED", "1")
    mem = MemoryManager(data_dir=str(tmp_path / "users" / "alice" / "memory"))

    search_count = 0

    class _FakeMem0:
        def search(self, query: str, *, filters=None, top_k=20, **kwargs):
            nonlocal search_count
            search_count += 1
            return {"results": [{"memory": "user likes coffee"}]}

    mem._mem0_client = _FakeMem0()
    mem._mem0_init_attempted = True

    # 1. First search: substantive query, search_count should increment
    hits = mem._search_mem0("我最喜欢喝咖啡了")
    assert hits == ["user likes coffee"]
    assert search_count == 1

    # 2. Second search: low semantic query ("哈哈"), should bypass search and reuse previous results
    hits2 = mem._search_mem0("哈哈")
    assert hits2 == ["user likes coffee"]
    assert search_count == 1

    # 3. Third search: contains special memory command prefix ("记住我"), should NOT bypass
    hits3 = mem._search_mem0("记住我")
    assert hits3 == ["user likes coffee"]
    assert search_count == 2


def test_get_facts_summary_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import time
    monkeypatch.setenv("SHUXIN_MEM0_ENABLED", "1")
    monkeypatch.setenv("SHUXIN_MEM0_SEARCH_TIMEOUT_MS", "50")
    mem = MemoryManager(data_dir=str(tmp_path / "users" / "alice" / "memory"))
    mem._last_mem0_results = ["user likes tea"]

    def _slow_search(query):
        time.sleep(0.2)
        return ["user likes cookies"]

    mem._search_mem0 = _slow_search
    mem._last_user_text = "我喜欢吃饼干"

    t0 = time.perf_counter()
    summary = mem.get_facts_summary()
    elapsed = time.perf_counter() - t0

    # It should timeout and fallback to _last_mem0_results (likes tea)
    assert "user likes tea" in summary
    assert "user likes cookies" not in summary
    assert elapsed < 0.15


def test_deferred_mem0_stores_ordered_turns_only_when_flushed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """语音通话中只积累短期原文，检查点再顺序提炼长期记忆。"""
    monkeypatch.setenv("SHUXIN_MEM0_ENABLED", "1")
    mem = MemoryManager(
        data_dir=str(tmp_path / "users" / "alice" / "companions" / "c1" / "memory"),
        mem0_user_id="alice::companion::c1",
        defer_mem0_writes=True,
        mem0_checkpoint_turns=2,
    )
    calls: list[tuple[Any, str]] = []

    class _FakeMem0:
        def add(self, messages, *, user_id, **kwargs):
            calls.append((messages, user_id))
            return {"results": []}

    mem._mem0_client = _FakeMem0()
    mem._mem0_init_attempted = True

    # 避免触发「我叫/记住」同步写，专注验证 defer 队列
    mem.add_message("user", "我住在上海")
    mem.add_message("assistant", "记下了")
    mem.add_message("user", "我养了一只猫")
    mem.add_message("assistant", "它叫什么？")

    assert calls == []
    assert mem.flush_deferred_mem0(force=False) == 2
    # infer 空结果时会追加一条 infer=False digest
    assert len(calls) == 2
    assert calls[0][1] == "alice::companion::c1"
    assert calls[0][0][0]["content"] == "我住在上海"
    assert isinstance(calls[1][0], str)
    assert "本通对话要点" in calls[1][0]
    assert mem.flush_deferred_mem0(force=True) == 0


def test_deferred_mem0_keeps_turns_when_flush_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHUXIN_MEM0_ENABLED", "1")
    mem = MemoryManager(
        data_dir=str(tmp_path / "users" / "alice" / "memory"),
        defer_mem0_writes=True,
        mem0_checkpoint_turns=1,
    )
    attempts = 0

    class _FakeMem0:
        def add(self, messages, *, user_id, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary failure")
            return {"results": [{"memory": "ok"}]}

    mem._mem0_client = _FakeMem0()
    mem._mem0_init_attempted = True
    mem.add_message("user", "我喜欢喝茶")
    mem.add_message("assistant", "好的")

    assert mem.flush_deferred_mem0(force=False) == 0
    assert mem.deferred_mem0_turn_count == 1
    assert (tmp_path / "users" / "alice" / "memory" / "pending_mem0.json").exists()
    assert mem.flush_deferred_mem0(force=True) == 1
    assert mem.deferred_mem0_turn_count == 0


def test_low_semantic_skips_search_when_no_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHUXIN_MEM0_ENABLED", "1")
    mem = MemoryManager(data_dir=str(tmp_path / "users" / "alice" / "memory"))
    search_count = 0

    class _FakeMem0:
        def search(self, query: str, *, filters=None, top_k=20, **kwargs):
            nonlocal search_count
            search_count += 1
            return {"results": [{"memory": "x"}]}

        def get_all(self, **kwargs):
            return {"results": []}

    mem._mem0_client = _FakeMem0()
    mem._mem0_init_attempted = True
    assert mem._search_mem0("嗯") == []
    assert search_count == 0


def test_get_facts_summary_falls_back_to_get_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHUXIN_MEM0_ENABLED", "1")
    mem = MemoryManager(data_dir=str(tmp_path / "users" / "alice" / "memory"))

    class _FakeMem0:
        def search(self, query: str, *, filters=None, top_k=20, **kwargs):
            return {"results": []}

        def get_all(self, **kwargs):
            return {"results": [{"memory": "用户住在上海"}]}

    mem._mem0_client = _FakeMem0()
    mem._mem0_init_attempted = True
    mem.add_message("user", "你还记得我住哪吗？")
    summary = mem.get_facts_summary()
    assert "用户住在上海" in summary


def test_explicit_remember_syncs_even_when_deferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHUXIN_MEM0_ENABLED", "1")
    mem = MemoryManager(
        data_dir=str(tmp_path / "users" / "alice" / "memory"),
        defer_mem0_writes=True,
    )
    calls: list[Any] = []

    class _FakeMem0:
        def add(self, messages, *, user_id, **kwargs):
            calls.append({"messages": messages, "infer": kwargs.get("infer", True)})
            return {"results": []}

    mem._mem0_client = _FakeMem0()
    mem._mem0_init_attempted = True
    mem.add_message("user", "记住我喜欢猫")
    assert len(calls) == 1
    assert calls[0]["infer"] is False
    assert "记住我喜欢猫" in calls[0]["messages"]
