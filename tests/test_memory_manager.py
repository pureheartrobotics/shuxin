"""MemoryManager 单元测试（Mem0 关闭，不依赖 Qdrant）。"""

from __future__ import annotations

import os
from pathlib import Path

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
    assert mem.get_facts_summary() == "暂无关于用户的长期记忆。"


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
