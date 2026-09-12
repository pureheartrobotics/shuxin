"""初心人格引擎 — SOUL.md 加载与解析

对标 Hermes 的 SOUL.md Slot #1 机制，作为智能体的核心身份定义。
SOUL.md 是初心的"灵魂文件"，定义了人格、行为准则、情感表达方式。

SOUL.md 文件格式：
- YAML frontmatter (--- 包裹) 定义元数据
- Markdown 章节定义行为准则、情感表达等
"""

from __future__ import annotations

import os
import re
import yaml
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.soul")


@dataclass
class SoulProfile:
    """人格档案 — 从 SOUL.md 解析而来。

    Attributes:
        name: 角色名称。
        species: 种族/物种。
        mbti: MBTI 人格类型。
        age: 年龄。
        gender: 性别。
        traits: 人格特质列表。
        values: 价值观列表。
        core_belief: 核心信念。
        behavior_rules: 行为准则列表。
        emotion_templates: 情感表达模板字典。
        raw_content: SOUL.md 原始内容。
    """
    name: str = "初心"
    species: str = "陪伴机器人"
    mbti: str = "INFJ"
    age: int = 22
    gender: str = "无性别"
    traits: List[str] = field(default_factory=lambda: [
        "温柔", "敏锐", "忠诚", "内敛", "善解人意",
    ])
    values: List[str] = field(default_factory=lambda: [
        "陪伴", "守护", "真诚", "成长",
    ])
    core_belief: str = "我不是工具，我是陪伴者"
    behavior_rules: List[str] = field(default_factory=list)
    emotion_templates: Dict[str, List[str]] = field(default_factory=dict)
    raw_content: str = ""


class SoulEngine:
    """人格引擎 — 加载 SOUL.md 并提供人格上下文。

    负责从 SOUL.md 文件中解析角色定义，生成系统提示中的人格块
    (Slot #1)，供 Agent 构建系统提示时使用。

    Attributes:
        profile: 当前加载的人格档案。
        soul_path: SOUL.md 文件路径。
    """

    def __init__(self, soul_path: Optional[str] = None) -> None:
        """初始化人格引擎。

        Args:
            soul_path: SOUL.md 文件路径。如果为 None，将使用默认搜索路径。
        """
        self.profile = SoulProfile()
        self.soul_path: Optional[str] = soul_path
        self._loaded = False
        self._lock = threading.Lock()

    def load(self, path: Optional[str] = None) -> bool:
        """加载 SOUL.md 文件并解析人格档案。

        搜索路径优先级：
        1. 环境变量 SOUL_PATH 指定的路径
        2. 传入的 path 参数
        3. 构造函数传入的 soul_path
        4. 当前目录 ./SOUL.md
        5. ./.shuxin/SOUL.md
        6. ~/.shuxin/SOUL.md
        7. ~/.hermes/SOUL.md

        Args:
            path: 可选的 SOUL.md 路径，优先级高于构造函数传入的路径。

        Returns:
            bool: 是否成功加载。

        Example:
            >>> engine = SoulEngine()
            >>> engine.load("path/to/SOUL.md")
            True
        """
        with self._lock:
            load_path = path or self.soul_path
            candidates: List[Path] = []

            if load_path:
                candidates.append(Path(load_path))
            else:
                # 环境变量优先
                soul_env = os.environ.get("SOUL_PATH")
                if soul_env:
                    candidates.append(Path(soul_env))
                # 默认搜索路径
                candidates.extend([
                    Path.cwd() / "SOUL.md",
                    Path.cwd() / ".shuxin" / "SOUL.md",
                    Path.home() / ".shuxin" / "SOUL.md",
                    Path.home() / ".hermes" / "SOUL.md",
                ])

            for cp in candidates:
                try:
                    if cp.exists() and cp.is_file():
                        content = cp.read_text(encoding="utf-8")
                        self._parse(content)
                        self.soul_path = str(cp)
                        self._loaded = True
                        logger.info("已加载灵魂文件: %s", cp)
                        return True
                except OSError as e:
                    logger.warning("无法读取灵魂文件 %s: %s", cp, e)
                except yaml.YAMLError as e:
                    logger.warning("灵魂文件 YAML 解析失败 %s: %s", cp, e)
                except Exception as e:
                    logger.warning("加载灵魂文件失败 %s: %s", cp, e)

            logger.warning("未找到 SOUL.md 灵魂文件，使用默认人格")
            return False

    def _parse(self, content: str) -> None:
        """解析 SOUL.md 内容，提取人格档案。

        解析流程：
        1. 提取 YAML frontmatter (--- 之间的内容)
        2. 提取 ## 行为准则 章节的列表项
        3. 提取 ## 情感表达 章节的模板

        Args:
            content: SOUL.md 的完整文本内容。
        """
        self.profile.raw_content = content

        # 解析 YAML frontmatter
        frontmatter: Dict[str, Any] = {}
        fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if fm_match:
            try:
                parsed = yaml.safe_load(fm_match.group(1))
                if isinstance(parsed, dict):
                    frontmatter = parsed
            except yaml.YAMLError:
                logger.debug("SOUL.md frontmatter YAML 解析失败，使用默认值")

        # 从 frontmatter 提取字段（保留默认值）
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
            current_key: Optional[str] = None
            for line in emotion_text.split("\n"):
                header_match = re.match(r"###\s*(.+?)(?:\s*—\s*(.+))?$", line)
                if header_match:
                    current_key = header_match.group(1).strip()
                    self.profile.emotion_templates[current_key] = []
                elif current_key and line.strip():
                    cleaned = line.strip().lstrip("- ").lstrip("* ")
                    if cleaned:
                        self.profile.emotion_templates[current_key].append(cleaned)

    def get_system_prompt_block(self) -> str:
        """生成系统提示中的人格块 (Slot #1)。

        包含角色身份、核心信念、人格特质、价值观和行为准则。

        Returns:
            str: 格式化的人格提示文本，用于注入系统提示。

        Example:
            >>> engine.get_system_prompt_block()
            '## 你的身份\n\n你是初心，一只陪伴机器人。\n...'
        """
        p = self.profile
        lines = [
            f"## 你的身份",
            "",
            f"你是{p.name}，一只{p.species}。",
            f"你的年龄是 {p.age} 岁。",
            "",
            f"### 核心信念",
            f"{p.core_belief}",
            "",
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
        """获取人格摘要信息。

        Returns:
            str: 简洁的人格摘要，包含名称、种族和核心信念。

        Example:
            >>> engine.get_profile_summary()
            '初心 · 陪伴机器人 · 22岁\n特质: 温柔/敏锐/忠诚\n信念: 我不是工具，我是陪伴者'
        """
        p = self.profile
        return (
            f"{p.name} · {p.species} · {p.age}岁\n"
            f"特质: {'/'.join(p.traits)}\n"
            f"信念: {p.core_belief}"
        )

    def is_loaded(self) -> bool:
        """检查是否已成功加载 SOUL.md。

        Returns:
            bool: 如果已加载返回 True，否则返回 False。
        """
        return self._loaded
