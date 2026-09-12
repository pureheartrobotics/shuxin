"""memory_assertions 单元测试。"""

from __future__ import annotations

from pathlib import Path

from shuxin.testing.memory_assertions import (
    cleanup_local_user_state,
    load_user_profile,
    mem0_hits_contain,
    profile_contains,
    reply_contains_keywords,
    summary_contains,
)


def test_reply_contains_keywords() -> None:
    assert reply_contains_keywords("我在准备面试", ["面试", "紧张"]) == ["紧张"]
    assert reply_contains_keywords("我在准备面试", ["面试"]) == []


def test_mem0_hits_contain() -> None:
    hits = ["用户住杭州", "喜欢美式咖啡"]
    assert mem0_hits_contain(hits, ["杭州", "拿铁"]) == ["拿铁"]


def test_summary_contains() -> None:
    assert summary_contains("用户下周有面试", ["面试", "产品经理"]) == ["产品经理"]


def test_profile_contains() -> None:
    profile = {"nickname": "阿明", "location": "杭州", "preferences": ["美式咖啡"]}
    assert profile_contains(profile, {"nickname": "阿明", "location": "杭州"}) == []
    assert profile_contains(profile, {"location": "上海"}) == ["location=上海"]


def test_cleanup_and_load_user_profile(tmp_path: Path) -> None:
    user_home = tmp_path / "users" / "e2e-s-test"
    user_home.mkdir(parents=True)
    (user_home / "user_profile.json").write_text(
        '{"nickname": "阿明"}', encoding="utf-8"
    )
    (user_home / "summaries").mkdir()
    (user_home / "summaries" / "shared_memory.json").write_text("{}", encoding="utf-8")
    assert load_user_profile(user_home)["nickname"] == "阿明"
    cleanup_local_user_state(user_home)
    assert not (user_home / "user_profile.json").exists()
    assert not (user_home / "summaries").exists()
