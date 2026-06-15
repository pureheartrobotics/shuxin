"""user_profile 单元测试。"""

from __future__ import annotations

from pathlib import Path

from shuxin.voice.user_profile import (
    extract_profile_facts,
    format_profile_context,
    load_profile,
    update_profile_from_text,
)


def test_extract_profile_facts() -> None:
    text = "我叫阿明，住杭州，养了一只猫叫豆腐，喜欢喝美式咖啡。"
    facts = extract_profile_facts(text)
    assert facts["nickname"] == "阿明"
    assert facts["location"] == "杭州"
    assert facts["preferences"] == ["美式咖啡"]
    assert facts["pets"] == [{"type": "猫", "name": "豆腐"}]


def test_update_and_format(tmp_path: Path) -> None:
    user_home = tmp_path / "users" / "alice"
    profile = update_profile_from_text(user_home, "我叫阿明，住杭州。")
    assert profile["nickname"] == "阿明"
    assert profile["location"] == "杭州"
    reloaded = load_profile(user_home)
    assert reloaded["nickname"] == "阿明"
    ctx = format_profile_context(reloaded)
    assert "阿明" in ctx
    assert "杭州" in ctx


def test_location_update(tmp_path: Path) -> None:
    user_home = tmp_path / "users" / "alice"
    update_profile_from_text(user_home, "我住杭州。")
    profile = update_profile_from_text(user_home, "我搬到上海了。")
    assert profile["location"] == "上海"
