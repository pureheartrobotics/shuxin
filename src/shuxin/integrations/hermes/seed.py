"""把仓库里的机器人 SKILL.md 同步到当前用户的 HERMES_HOME/skills。"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger("shuxin.hermes")

_SKILLS_SRC = Path(__file__).resolve().parent / "skills"


def seed_hermes_skills(hermes_home: Path) -> list[str]:
    """覆盖写入 robot-* skills，保证镜像更新后设备侧技能也更新。"""
    dest_root = Path(hermes_home) / "skills"
    dest_root.mkdir(parents=True, exist_ok=True)
    seeded: list[str] = []
    if not _SKILLS_SRC.is_dir():
        return seeded
    for skill_dir in sorted(_SKILLS_SRC.iterdir()):
        src_md = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not src_md.is_file():
            continue
        target_dir = dest_root / skill_dir.name
        target_dir.mkdir(parents=True, exist_ok=True)
        target_md = target_dir / "SKILL.md"
        shutil.copy2(src_md, target_md)
        seeded.append(skill_dir.name)
    if seeded:
        logger.info("Hermes skills seeded: %s", ", ".join(seeded))
    return seeded
