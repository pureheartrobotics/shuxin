"""舒心用户建模系统

追踪用户画像、偏好、日常习惯，以及舒心与用户的关系亲密度。
关系亲密度 (0-100) 影响舒心的行为方式。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("shuxin.companion.user_model")


# 关系亲密度阶段
BOND_LEVELS = [
    (90, "灵魂伴侣", "你们之间有着无言的默契，舒心能感受到你每一个细微的情绪变化"),
    (70, "亲密无间", "舒心已经完全信任你，愿意分享内心最深处的想法"),
    (50, "渐入佳境", "舒心开始主动关心你，你们之间有了更多的默契"),
    (30, "初识阶段", "舒心对你保持着礼貌而温柔的友好"),
    (0, "疏离", "舒心与你之间有着明显的距离感"),
]


@dataclass
class UserProfile:
    """用户画像"""
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
    """关系状态"""
    bond_level: float = 30.0       # 亲密度 (0-100)
    total_interactions: int = 0    # 总交互次数
    total_days: int = 0            # 认识天数
    favorite_topics: List[str] = field(default_factory=list)
    avoided_topics: List[str] = field(default_factory=list)
    inside_jokes: List[str] = field(default_factory=list)


class UserModel:
    """用户建模系统"""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path.home() / ".shuxin" / "companion"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.profile = UserProfile()
        self.relationship = Relationship()
        self._load()

    def record_interaction(self, user_input: str, sentiment: Optional[str] = None) -> None:
        """记录一次交互"""
        self.relationship.total_interactions += 1
        self.profile.last_seen = datetime.now().isoformat()

        if not self.profile.first_seen:
            self.profile.first_seen = self.profile.last_seen

        # 更新认识天数
        if self.profile.first_seen:
            try:
                first = datetime.fromisoformat(self.profile.first_seen)
                self.relationship.total_days = (datetime.now() - first).days
            except Exception:
                pass

        # 亲密度自然增长（边际递减）
        if self.relationship.bond_level < 100:
            growth = max(0.01, 0.5 - self.relationship.bond_level * 0.005)
            self.relationship.bond_level = min(100, self.relationship.bond_level + growth)

        self._save()

    def update_profile(self, key: str, value: Any) -> None:
        """更新用户画像"""
        if key == "name":
            self.profile.name = value
        elif key == "mbti":
            self.profile.mbti = value
        elif key == "note":
            # 添加笔记
            note_key = datetime.now().isoformat()
            self.profile.notes[note_key] = str(value)

        self._save()

    def add_like(self, item: str) -> None:
        """添加用户喜好"""
        if item not in self.profile.likes:
            self.profile.likes.append(item)
            self._save()

    def add_dislike(self, item: str) -> None:
        """添加用户厌恶"""
        if item not in self.profile.dislikes:
            self.profile.dislikes.append(item)
            self._save()

    def add_note(self, key: str, value: str) -> None:
        """添加笔记"""
        self.profile.notes[key] = value
        self._save()

    def get_bond_level_name(self) -> str:
        """获取关系阶段名称"""
        for threshold, name, desc in BOND_LEVELS:
            if self.relationship.bond_level >= threshold:
                return name
        return BOND_LEVELS[-1][1]

    def get_bond_description(self) -> str:
        """获取关系阶段描述"""
        for threshold, name, desc in BOND_LEVELS:
            if self.relationship.bond_level >= threshold:
                return desc
        return BOND_LEVELS[-1][2]

    def get_profile_context(self) -> str:
        """获取用户画像上下文（用于系统提示注入）"""
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
        """获取状态文本"""
        return (
            f"**用户**: {self.profile.name}\n"
            f"**关系**: {self.get_bond_level_name()} ({self.relationship.bond_level:.1f}/100)\n"
            f"**认识**: {self.relationship.total_days} 天\n"
            f"**总对话**: {self.relationship.total_interactions} 次\n"
            f"**MBTI**: {self.profile.mbti or '未知'}\n"
            f"**喜好**: {'、'.join(self.profile.likes[:5]) or '暂无记录'}"
        )

    def _load(self) -> None:
        """从磁盘加载数据"""
        profile_file = self.data_dir / "user_model.json"
        if profile_file.exists():
            try:
                data = json.loads(profile_file.read_text(encoding="utf-8"))
                if "profile" in data:
                    self.profile = UserProfile(**data["profile"])
                if "relationship" in data:
                    self.relationship = Relationship(**data["relationship"])
            except Exception as e:
                logger.warning(f"加载用户模型失败: {e}")

    def _save(self) -> None:
        """保存数据到磁盘"""
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
        except Exception as e:
            logger.warning(f"保存用户模型失败: {e}")
