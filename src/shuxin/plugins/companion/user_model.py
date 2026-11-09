"""初心用户建模系统

追踪用户画像、偏好、日常习惯，以及初心与用户的关系亲密度。

关系亲密度 (0-100) 影响初心的行为方式，分为 5 个阶段：
- 灵魂伴侣 (90+): 无言的默契
- 亲密无间 (70+): 完全信任
- 渐入佳境 (50+): 主动关心
- 初识阶段 (30+): 礼貌友好
- 疏离 (<30): 明显距离感

亲密度增长采用边际递减算法，越接近 100 增长越慢。
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("shuxin.companion.user_model")

# 关系亲密度阶段定义 — (阈值, 名称, 描述)
BOND_LEVELS: List[tuple] = [
    (90, "灵魂伴侣", "你们之间有着无言的默契，初心能感受到你每一个细微的情绪变化"),
    (70, "亲密无间", "初心已经完全信任你，愿意分享内心最深处的想法"),
    (50, "渐入佳境", "初心开始主动关心你，你们之间有了更多的默契"),
    (30, "初识阶段", "初心对你保持着礼貌而温柔的友好"),
    (0, "疏离", "初心与你之间有着明显的距离感"),
]

# 亲密度增长参数
BOND_GROWTH_BASE: float = 0.5
BOND_GROWTH_DECAY: float = 0.005
BOND_GROWTH_MIN: float = 0.01
BOND_MAX: float = 100.0


@dataclass
class UserProfile:
    """用户画像。

    Attributes:
        name: 用户名称。
        mbti: 用户的 MBTI 人格类型。
        likes: 用户喜好列表。
        dislikes: 用户厌恶列表。
        daily_routine: 日常作息字典。
        notes: 笔记字典。
        first_seen: 首次交互时间戳。
        last_seen: 最后交互时间戳。
    """
    name: str = "主人"
    mbti: str = ""
    likes: List[str] = field(default_factory=list)
    dislikes: List[str] = field(default_factory=list)
    daily_routine: Dict[str, str] = field(default_factory=dict)
    notes: Dict[str, str] = field(default_factory=dict)
    first_seen: str = ""
    last_seen: str = ""


@dataclass
class Relationship:
    """关系状态。

    Attributes:
        bond_level: 亲密度 (0-100)。
        total_interactions: 总交互次数。
        total_days: 认识天数。
        favorite_topics: 喜欢的话题列表。
        avoided_topics: 回避的话题列表。
        inside_jokes: 内部笑话列表。
    """
    bond_level: float = 30.0
    total_interactions: int = 0
    total_days: int = 0
    favorite_topics: List[str] = field(default_factory=list)
    avoided_topics: List[str] = field(default_factory=list)
    inside_jokes: List[str] = field(default_factory=list)


class UserModel:
    """用户建模系统 — 追踪用户信息和关系状态。

    记录用户画像、偏好、交互历史，维护关系亲密度。
    提供用户上下文用于系统提示注入。

    Attributes:
        profile: 用户画像。
        relationship: 关系状态。
        data_dir: 数据持久化目录。
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        """初始化用户建模系统。

        Args:
            data_dir: 数据持久化目录。如果为 None，使用 ``~/.shuxin/companion``。
        """
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path.home() / ".shuxin" / "companion"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.profile = UserProfile()
        self.relationship = Relationship()
        self._lock = threading.Lock()
        self._load()

    def record_interaction(self, user_input: str, sentiment: Optional[str] = None) -> None:
        """记录一次用户交互。

        更新交互计数、最后活跃时间、认识天数和亲密度。

        Args:
            user_input: 用户输入的文本（目前仅用于计数）。
            sentiment: 可选的用户情感标签（预留）。
        """
        with self._lock:
            self.relationship.total_interactions += 1
            now = datetime.now()
            self.profile.last_seen = now.isoformat()

            if not self.profile.first_seen:
                self.profile.first_seen = self.profile.last_seen

            # 更新认识天数
            if self.profile.first_seen:
                try:
                    first = datetime.fromisoformat(self.profile.first_seen)
                    self.relationship.total_days = (now - first).days
                except (ValueError, TypeError):
                    pass

            # 亲密度自然增长（边际递减）
            if self.relationship.bond_level < BOND_MAX:
                growth = max(
                    BOND_GROWTH_MIN,
                    BOND_GROWTH_BASE - self.relationship.bond_level * BOND_GROWTH_DECAY,
                )
                self.relationship.bond_level = min(BOND_MAX, self.relationship.bond_level + growth)

        self._save()

    def update_profile(self, key: str, value: Any) -> None:
        """更新用户画像的指定字段。

        Args:
            key: 字段名 (name, mbti, note)。
            value: 字段值。

        Note:
            当 key 为 "note" 时，value 会被添加到笔记字典中，
            以当前时间戳为键。
        """
        with self._lock:
            if key == "name":
                self.profile.name = str(value)
            elif key == "mbti":
                self.profile.mbti = str(value)
            elif key == "note":
                note_key = datetime.now().isoformat()
                self.profile.notes[note_key] = str(value)
        self._save()

    def add_like(self, item: str) -> None:
        """添加用户喜好。

        Args:
            item: 喜好项目。
        """
        with self._lock:
            if item not in self.profile.likes:
                self.profile.likes.append(item)
        self._save()

    def add_dislike(self, item: str) -> None:
        """添加用户厌恶。

        Args:
            item: 厌恶项目。
        """
        with self._lock:
            if item not in self.profile.dislikes:
                self.profile.dislikes.append(item)
        self._save()

    def add_note(self, key: str, value: str) -> None:
        """添加笔记。

        Args:
            key: 笔记键名。
            value: 笔记内容。
        """
        with self._lock:
            self.profile.notes[key] = value
        self._save()

    def get_bond_level_name(self) -> str:
        """获取当前关系阶段名称。

        Returns:
            str: 关系阶段名称（灵魂伴侣、亲密无间等）。
        """
        for threshold, name, _desc in BOND_LEVELS:
            if self.relationship.bond_level >= threshold:
                return name
        return BOND_LEVELS[-1][1]

    def get_bond_description(self) -> str:
        """获取当前关系阶段描述。

        Returns:
            str: 关系阶段描述文本。
        """
        for threshold, _name, desc in BOND_LEVELS:
            if self.relationship.bond_level >= threshold:
                return desc
        return BOND_LEVELS[-1][2]

    def get_profile_context(self) -> str:
        """获取用户画像上下文（用于系统提示注入）。

        Returns:
            str: 格式化的用户信息文本。

        Example:
            >>> model.get_profile_context()
            '## 关于 主人\\n关系: 初识阶段 (30/100)\\n认识: 0 天\\n总对话: 5 次'
        """
        lines = [f"## 关于 {self.profile.name}"]

        if self.profile.mbti:
            lines.append(f"MBTI: {self.profile.mbti}")

        if self.profile.likes:
            lines.append(f"喜欢: {'、'.join(self.profile.likes)}")

        if self.profile.dislikes:
            lines.append(f"不喜欢: {'、'.join(self.profile.dislikes)}")

        lines.append(f"关系: {self.get_bond_level_name()} ({self.relationship.bond_level:.0f}/100)")
        lines.append(f"认识: {self.relationship.total_days} 天")
        lines.append(f"总对话: {self.relationship.total_interactions} 次")

        return "\n".join(lines)

    def get_status_text(self) -> str:
        """获取用户模型状态文本（用于显示）。

        Returns:
            str: 格式化的状态文本。
        """
        likes_str = '、'.join(self.profile.likes[:5]) if self.profile.likes else "暂无记录"
        return (
            f"**用户**: {self.profile.name}\n"
            f"**关系**: {self.get_bond_level_name()} ({self.relationship.bond_level:.1f}/100)\n"
            f"**认识**: {self.relationship.total_days} 天\n"
            f"**总对话**: {self.relationship.total_interactions} 次\n"
            f"**MBTI**: {self.profile.mbti or '未知'}\n"
            f"**喜好**: {likes_str}"
        )

    def _load(self) -> None:
        """从磁盘加载用户模型数据。"""
        profile_file = self.data_dir / "user_model.json"
        if profile_file.exists():
            try:
                data = json.loads(profile_file.read_text(encoding="utf-8"))
                if "profile" in data and isinstance(data["profile"], dict):
                    self.profile = UserProfile(**data["profile"])
                if "relationship" in data and isinstance(data["relationship"], dict):
                    self.relationship = Relationship(**data["relationship"])
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("加载用户模型失败: %s", e)
            except Exception as e:
                logger.warning("加载用户模型异常: %s", e)

    def _save(self) -> None:
        """保存用户模型数据到磁盘。"""
        profile_file = self.data_dir / "user_model.json"
        try:
            profile_file.write_text(
                json.dumps({
                    "profile": {
                        "name": self.profile.name,
                        "mbti": self.profile.mbti,
                        "likes": self.profile.likes,
                        "dislikes": self.profile.dislikes,
                        "daily_routine": self.profile.daily_routine,
                        "notes": self.profile.notes,
                        "first_seen": self.profile.first_seen,
                        "last_seen": self.profile.last_seen,
                    },
                    "relationship": {
                        "bond_level": self.relationship.bond_level,
                        "total_interactions": self.relationship.total_interactions,
                        "total_days": self.relationship.total_days,
                        "favorite_topics": self.relationship.favorite_topics,
                        "avoided_topics": self.relationship.avoided_topics,
                        "inside_jokes": self.relationship.inside_jokes,
                    },
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("保存用户模型失败: %s", e)
        except Exception as e:
            logger.warning("保存用户模型异常: %s", e)
