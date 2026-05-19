"""舒心技能系统

对标 Hermes 的 skills/ 系统，支持从 SKILL.md 加载技能定义。
"""

from __future__ import annotations

import os
import yaml
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.skills")


@dataclass
class SkillDefinition:
    """技能定义"""
    name: str
    description: str
    category: str = "general"
    platforms: List[str] = field(default_factory=list)
    content: str = ""
    path: str = ""


class SkillManager:
    """技能管理器"""

    def __init__(self):
        self._skills: Dict[str, SkillDefinition] = {}
        self._search_paths: List[Path] = []

    def initialize(self) -> None:
        """初始化技能系统"""
        self._search_paths = [
            Path(__file__).parent,
            Path.cwd() / "skills",
            Path.home() / ".shuxin" / "skills",
        ]
        self._discover()

    def _discover(self) -> None:
        """发现并加载所有技能"""
        for skills_dir in self._search_paths:
            if not skills_dir.exists():
                continue
            for item in skills_dir.iterdir():
                if item.is_dir():
                    skill_file = item / "SKILL.md"
                    if skill_file.exists():
                        skill = self._load_skill(skill_file)
                        if skill:
                            self._skills[skill.name] = skill

        logger.info(f"已加载 {len(self._skills)} 个技能: {list(self._skills.keys())}")

    def _load_skill(self, skill_file: Path) -> Optional[SkillDefinition]:
        """加载单个技能"""
        try:
            content = skill_file.read_text(encoding="utf-8")

            # 解析 frontmatter
            frontmatter = {}
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        frontmatter = yaml.safe_load(parts[1]) or {}
                    except Exception:
                        pass
                    content = parts[2].strip()

            name = frontmatter.get("name", skill_file.parent.name)
            return SkillDefinition(
                name=name,
                description=frontmatter.get("description", ""),
                category=frontmatter.get("category", "general"),
                platforms=frontmatter.get("platforms", []),
                content=content,
                path=str(skill_file),
            )
        except Exception as e:
            logger.warning(f"加载技能失败 {skill_file}: {e}")
            return None

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        """获取技能"""
        return self._skills.get(name)

    def list_skills(self, category: Optional[str] = None) -> List[SkillDefinition]:
        """列出技能"""
        if category:
            return [s for s in self._skills.values() if s.category == category]
        return list(self._skills.values())

    def get_skills_prompt_block(self) -> str:
        """生成技能索引块（用于系统提示）"""
        if not self._skills:
            return ""

        lines = ["## 可用技能"]
        for skill in self._skills.values():
            lines.append(f"- {skill.name}: {skill.description}")
        return "\n".join(lines)
