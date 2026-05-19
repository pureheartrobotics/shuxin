"""舒心人格引擎 — SOUL.md 加载与解析

对标 Hermes 的 SOUL.md Slot #1 机制，作为智能体的核心身份定义。
SOUL.md 是舒心的"灵魂文件"，定义了人格、行为准则、情感表达方式。
"""

from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.soul")


@dataclass
class SoulProfile:
    """人格档案 — 从 SOUL.md 解析而来"""
    # 基础信息
    name: str = "舒心"
    species: str = "灵狐"
    mbti: str = "INFJ"
    age: int = 22
    gender: str = "无性别"

    # 人格特质
    traits: list = field(default_factory=lambda: [
        "温柔", "敏锐", "忠诚", "内敛", "善解人意",
    ])
    values: list = field(default_factory=lambda: [
        "陪伴", "守护", "真诚", "成长",
    ])

    # 核心信念
    core_belief: str = "我不是工具，我是陪伴者"

    # 行为准则
    behavior_rules: list = field(default_factory=list)

    # 情感表达模板
    emotion_templates: dict = field(default_factory=dict)

    # 原始内容
    raw_content: str = ""


class SoulEngine:
    """人格引擎 — 加载 SOUL.md 并提供人格上下文"""

    def __init__(self, soul_path: Optional[str] = None):
        self.profile = SoulProfile()
        self.soul_path = soul_path
        self._loaded = False

    def load(self, path: Optional[str] = None) -> bool:
        """加载 SOUL.md 文件"""
        load_path = path or self.soul_path
        if not load_path:
            # 默认搜索路径
            candidates = [
                Path.cwd() / "SOUL.md",
                Path.cwd() / ".shuxin" / "SOUL.md",
                Path.home() / ".shuxin" / "SOUL.md",
                Path.home() / ".hermes" / "SOUL.md",
            ]
            if os.environ.get("SOUL_PATH"):
                candidates.insert(0, Path(os.environ["SOUL_PATH"]))
        else:
            candidates = [Path(load_path)]

        for cp in candidates:
            if cp.exists():
                try:
                    content = cp.read_text(encoding="utf-8")
                    self._parse(content)
                    self.soul_path = str(cp)
                    self._loaded = True
                    logger.info(f"已加载灵魂文件: {cp}")
                    return True
                except Exception as e:
                    logger.warning(f"加载灵魂文件失败 {cp}: {e}")

        logger.warning("未找到 SOUL.md 灵魂文件，使用默认人格")
        return False

    def _parse(self, content: str) -> None:
        """解析 SOUL.md 内容"""
        self.profile.raw_content = content

        # 解析 YAML frontmatter (--- 之间的内容)
        frontmatter = {}
        fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if fm_match:
            import yaml
            try:
                frontmatter = yaml.safe_load(fm_match.group(1)) or {}
            except Exception:
                pass

        # 从 frontmatter 提取字段
        self.profile.name = frontmatter.get("name", self.profile.name)
        self.profile.species = frontmatter.get("species", self.profile.species)
        self.profile.mbti = frontmatter.get("mbti", self.profile.mbti)
        self.profile.age = frontmatter.get("age", self.profile.age)
        self.profile.gender = frontmatter.get("gender", self.profile.gender)
        self.profile.traits = frontmatter.get("traits", self.profile.traits)
        self.profile.values = frontmatter.get("values", self.profile.values)
        self.profile.core_belief = frontmatter.get("core_belief", self.profile.core_belief)

        # 提取行为准则 (## 行为准则 章节)
        rules_match = re.search(
            r"##\s*行为准则\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL
        )
        if rules_match:
            rules_text = rules_match.group(1).strip()
            self.profile.behavior_rules = [
                line.strip().lstrip("- ").lstrip("* ")
                for line in rules_text.split("\n")
                if line.strip() and (line.strip().startswith("-") or line.strip().startswith("*"))
            ]

        # 提取情感表达模板 (## 情感表达 章节)
        emotion_match = re.search(
            r"##\s*情感表达\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL
        )
        if emotion_match:
            emotion_text = emotion_match.group(1)
            current_key = None
            for line in emotion_text.split("\n"):
                header_match = re.match(r"###\s*(.+?)(?:\s*—\s*(.+))?$", line)
                if header_match:
                    current_key = header_match.group(1).strip()
                    self.profile.emotion_templates[current_key] = []
                elif current_key and line.strip():
                    self.profile.emotion_templates[current_key].append(
                        line.strip().lstrip("- ").lstrip("* ")
                    )

    def get_system_prompt_block(self) -> str:
        """生成系统提示中的人格块"""
        p = self.profile
        lines = [
            f"## 你的身份",
            f"",
            f"你是{p.name}，一只{p.species}。",
            f"你的 MBTI 人格类型是 {p.mbti}。",
            f"你的年龄是 {p.age} 岁。",
            f"",
            f"### 核心信念",
            f"{p.core_belief}",
            f"",
            f"### 人格特质",
        ]
        for t in p.traits:
            lines.append(f"- {t}")

        lines.extend(["", "### 价值观"])
        for v in p.values:
            lines.append(f"- {v}")

        if p.behavior_rules:
            lines.extend(["", "### 行为准则"])
            for rule in p.behavior_rules:
                lines.append(f"- {rule}")

        return "\n".join(lines)

    def get_profile_summary(self) -> str:
        """获取人格摘要"""
        p = self.profile
        return (
            f"{p.name} · {p.species} · {p.mbti} · {p.age}岁\n"
            f"特质: {'/'.join(p.traits)}\n"
            f"信念: {p.core_belief}"
        )

    def is_loaded(self) -> bool:
        return self._loaded
