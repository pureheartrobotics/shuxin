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


def test_add_message_short_term(tmp_path: Path) -> None:
    mem = MemoryManager(data_dir=str(tmp_path / "memory"))
    mem.add_message("user", "你好")
    mem.add_message("assistant", "你好呀")
    assert len(mem.short_term) == 2
    assert mem.get_facts_summary() == "暂无关于用户的长期记忆。"
