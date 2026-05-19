"""舒心技能系统

对标 Hermes 的 skills/ 系统，支持从 SKILL.md 加载技能定义。

SKILL.md 格式：
```yaml
---
name: my-skill
description: 技能描述
category: general
platforms: [cli, api]
---
技能内容...
```

技能搜索路径：
1. shuxin/skills/ 包目录
2. ./skills/ 当前工作目录
3. ~/.shuxin/skills/ 用户目录
"""

from __future__ import annotations

import os
import yaml
import logging
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.skills")


@dataclass
class SkillDefinition:
    """技能定义 — 从 SKILL.md 解析而来。

    Attributes:
        name: 技能名称。
        description: 技能描述。
        category: 技能分类。
        platforms: 支持的平台列表。
        content: 技能内容（去除 frontmatter 后的 Markdown）。
        path: SKILL.md 文件路径。
    """
    name: str
    description: str
    category: str = "general"
    platforms: List[str] = field(default_factory=list)
    content: str = ""
    path: str = ""


class SkillManager:
    """技能管理器 — 发现、加载和管理技能。

    从多个搜索路径发现 SKILL.md 文件，解析 frontmatter 和内容，
    提供技能查询和系统提示生成功能。

    Attributes:
        _skills: 技能名称到定义的映射字典。
        _search_paths: 技能搜索路径列表。
    """

    def __init__(self) -> None:
        """初始化技能管理器。"""
        self._skills: Dict[str, SkillDefinition] = {}
        self._search_paths: List[Path] = []
        self._lock = threading.Lock()

    def initialize(self) -> None:
        """初始化技能系统，发现并加载所有技能。

        搜索路径（按优先级）：
        1. shuxin/skills/ 包目录
        2. ./skills/ 当前工作目录
        3. ~/.shuxin/skills/ 用户目录
        """
        self._search_paths = [
            Path(__file__).parent,
            Path.cwd() / "skills",
            Path.home() / ".shuxin" / "skills",
        ]
        self._discover()

    def _discover(self) -> None:
        """发现并加载所有技能。

        遍历搜索路径中的每个子目录，查找 SKILL.md 文件。
        """
        loaded_count = 0
        for skills_dir in self._search_paths:
            if not skills_dir.exists() or not skills_dir.is_dir():
                continue
            try:
                for item in skills_dir.iterdir():
                    if item.is_dir():
                        skill_file = item / "SKILL.md"
                        if skill_file.exists():
                            skill = self._load_skill(skill_file)
                            if skill:
                                with self._lock:
                                    self._skills[skill.name] = skill
                                loaded_count += 1
            except OSError as e:
                logger.warning("无法扫描技能目录 %s: %s", skills_dir, e)

        logger.info("已加载 %d 个技能: %s", loaded_count, list(self._skills.keys()))

    @staticmethod
    def _load_skill(skill_file: Path) -> Optional[SkillDefinition]:
        """加载单个 SKILL.md 文件。

        Args:
            skill_file: SKILL.md 文件路径。

        Returns:
            Optional[SkillDefinition]: 解析后的技能定义，失败返回 None。
        """
        try:
            content = skill_file.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("无法读取技能文件 %s: %s", skill_file, e)
            return None

        # 解析 frontmatter
        frontmatter: Dict[str, Any] = {}
        skill_content = content

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    parsed = yaml.safe_load(parts[1])
                    if isinstance(parsed, dict):
                        frontmatter = parsed
                except yaml.YAMLError:
                    logger.debug("技能文件 frontmatter 解析失败: %s", skill_file)
                skill_content = parts[2].strip()

        name = frontmatter.get("name", skill_file.parent.name)
        return SkillDefinition(
            name=name,
            description=frontmatter.get("description", ""),
            category=frontmatter.get("category", "general"),
            platforms=frontmatter.get("platforms", []),
            content=skill_content,
            path=str(skill_file),
        )

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        """根据名称获取技能定义。

        Args:
            name: 技能名称。

        Returns:
            Optional[SkillDefinition]: 技能定义，如果不存在返回 None。
        """
        return self._skills.get(name)

    def list_skills(self, category: Optional[str] = None) -> List[SkillDefinition]:
        """列出技能，可按分类筛选。

        Args:
            category: 可选的分类筛选条件。

        Returns:
            List[SkillDefinition]: 匹配的技能定义列表。
        """
        with self._lock:
            if category:
                return [s for s in self._skills.values() if s.category == category]
            return list(self._skills.values())

    def get_skills_prompt_block(self) -> str:
        """生成技能索引块（用于系统提示注入）。

        Returns:
            str: 格式化的技能索引文本。如果没有技能，返回空字符串。

        Example:
            >>> manager.get_skills_prompt_block()
            '## 可用技能\\n- my-skill: 技能描述'
        """
        if not self._skills:
            return ""

        lines = ["## 可用技能"]
        with self._lock:
            for skill in self._skills.values():
                lines.append(f"- {skill.name}: {skill.description}")
        return "\n".join(lines)
