"""soft companion 中期摘要路径：应读 users/{uid}/summaries，而非 companions/summaries。"""

from __future__ import annotations

import json
from pathlib import Path

from shuxin.plugins.companion import (
    CompanionPlugin,
    _resolve_user_home_for_companion_data,
)


def test_resolve_user_home_soft_companion(tmp_path: Path) -> None:
    soft = tmp_path / "users" / "alice" / "companions" / "cmp_1"
    soft.mkdir(parents=True)
    assert _resolve_user_home_for_companion_data(soft) == tmp_path / "users" / "alice"


def test_resolve_user_home_hardware_companion(tmp_path: Path) -> None:
    hard = tmp_path / "users" / "alice" / "companion"
    hard.mkdir(parents=True)
    assert _resolve_user_home_for_companion_data(hard) == tmp_path / "users" / "alice"


def test_growth_context_reads_user_level_shared_memory(tmp_path: Path) -> None:
    user_home = tmp_path / "users" / "alice"
    soft_dir = user_home / "companions" / "cmp_1"
    soft_dir.mkdir(parents=True)
    summaries = user_home / "summaries"
    summaries.mkdir(parents=True)
    (summaries / "shared_memory.json").write_text(
        json.dumps(
            {
                "turn_count": 12,
                "rolling_summary": "用户住在上海，养了一只猫",
                "recent_topics": ["猫", "上海"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (soft_dir / "personality.json").write_text(
        json.dumps({"stage": "熟悉", "shared_rituals": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    plugin = CompanionPlugin.__new__(CompanionPlugin)
    plugin.data_dir = str(soft_dir)
    text = plugin._get_growth_context()
    assert "累计对话: 12 次" in text
    assert "用户住在上海" in text
    assert "近期话题: 猫、上海" in text
