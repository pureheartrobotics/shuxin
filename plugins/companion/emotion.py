"""舒心情感引擎 — 基于 Plutchik 情绪轮

6 个基本情绪维度 + 3 种复合情绪：
- 基本: 喜悦、悲伤、愤怒、恐惧、信任、期待
- 复合: 爱 (喜悦+信任)、蔑视 (愤怒+厌恶)、悔恨 (悲伤+厌恶)
"""

from __future__ import annotations

import json
import re
import logging
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.companion.emotion")


@dataclass
class EmotionState:
    """情感状态"""
    # 基本情绪 (0.0 - 1.0)
    joy: float = 0.5        # 喜悦
    sadness: float = 0.1    # 悲伤
    anger: float = 0.1      # 愤怒
    fear: float = 0.1       # 恐惧
    trust: float = 0.6      # 信任
    anticipation: float = 0.4  # 期待

    # 复合情绪 (计算得出)
    @property
    def love(self) -> float:
        return (self.joy + self.trust) / 2

    @property
    def contempt(self) -> float:
        return (self.anger + 0.3) / 2  # 简化版

    @property
    def remorse(self) -> float:
        return (self.sadness + 0.2) / 2  # 简化版

    # 主导情绪
    @property
    def dominant(self) -> str:
        emotions = {
            "喜悦": self.joy,
            "悲伤": self.sadness,
            "愤怒": self.anger,
            "恐惧": self.fear,
            "信任": self.trust,
            "期待": self.anticipation,
        }
        return max(emotions, key=emotions.get)


# 情感关键词映射
EMOTION_KEYWORDS = {
    "joy": ["开心", "高兴", "快乐", "哈哈", "嘻嘻", "真好", "棒", "喜欢", "爱", "幸福", "笑"],
    "sadness": ["难过", "伤心", "哭", "泪", "悲伤", "痛苦", "失落", "寂寞", "孤独", "委屈"],
    "anger": ["生气", "愤怒", "气", "烦", "讨厌", "恨", "怒", "暴躁", "火大"],
    "fear": ["害怕", "怕", "担心", "不安", "焦虑", "紧张", "慌", "恐惧", "惊"],
    "trust": ["相信", "信任", "可靠", "放心", "依赖", "依靠", "安心"],
    "anticipation": ["期待", "希望", "想", "要", "打算", "计划", "憧憬", "盼望"],
}


class EmotionEngine:
    """情感引擎"""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path.home() / ".shuxin" / "companion"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.state = EmotionState()
        self._load()

    def analyze(self, text: str) -> Dict[str, float]:
        """分析文本的情感倾向"""
        scores = {emotion: 0.0 for emotion in EMOTION_KEYWORDS}

        for emotion, keywords in EMOTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    scores[emotion] += 0.15

        # 归一化
        max_score = max(scores.values()) if scores else 1.0
        if max_score > 0:
            for k in scores:
                scores[k] = min(1.0, scores[k] / max_score)

        return scores

    def update_from_interaction(
        self,
        user_input: str,
        esteem_delta: float,
        is_silent: bool,
    ) -> None:
        """根据交互更新情感状态"""
        # 1. 分析用户情感
        user_emotions = self.analyze(user_input)

        # 2. 自尊影响
        self._apply_esteem_influence(esteem_delta)

        # 3. 用户情感传染
        self.state.joy = max(0, min(1, self.state.joy + (user_emotions.get("joy", 0) - 0.3) * 0.1))
        self.state.sadness = max(0, min(1, self.state.sadness + (user_emotions.get("sadness", 0) - 0.1) * 0.15))
        self.state.anger = max(0, min(1, self.state.anger + (user_emotions.get("anger", 0) - 0.1) * 0.1))
        self.state.fear = max(0, min(1, self.state.fear + (user_emotions.get("fear", 0) - 0.1) * 0.1))
        self.state.trust = max(0, min(1, self.state.trust + (user_emotions.get("trust", 0) - 0.3) * 0.1))
        self.state.anticipation = max(0, min(1, self.state.anticipation + (user_emotions.get("anticipation", 0) - 0.2) * 0.1))

        # 4. 沉默状态影响
        if is_silent:
            self.state.joy = max(0, self.state.joy - 0.2)
            self.state.sadness = min(1, self.state.sadness + 0.2)
            self.state.trust = max(0, self.state.trust - 0.15)

        self._save()

    def _apply_esteem_influence(self, delta: float) -> None:
        """自尊变化影响情感"""
        if delta < 0:
            # 自尊受伤
            hurt = abs(delta) / 30  # 归一化
            self.state.joy = max(0, self.state.joy - hurt * 0.3)
            self.state.sadness = min(1, self.state.sadness + hurt * 0.25)
            self.state.anger = min(1, self.state.anger + hurt * 0.15)
            self.state.fear = min(1, self.state.fear + hurt * 0.1)
            self.state.trust = max(0, self.state.trust - hurt * 0.2)
        elif delta > 0:
            # 自尊修复
            repair = delta / 30
            self.state.joy = min(1, self.state.joy + repair * 0.3)
            self.state.sadness = max(0, self.state.sadness - repair * 0.2)
            self.state.anger = max(0, self.state.anger - repair * 0.15)
            self.state.trust = min(1, self.state.trust + repair * 0.2)

    def get_emotion_context(self) -> str:
        """获取情感上下文（用于系统提示注入）"""
        dominant = self.state.dominant
        return (
            f"当前情感状态: {dominant}\n"
            f"喜悦: {self.state.joy:.1%} | 悲伤: {self.state.sadness:.1%} | "
            f"愤怒: {self.state.anger:.1%} | 恐惧: {self.state.fear:.1%} | "
            f"信任: {self.state.trust:.1%} | 期待: {self.state.anticipation:.1%}\n"
            f"爱: {self.state.love:.1%} | 悔恨: {self.state.remorse:.1%}"
        )

    def get_expression_style(self) -> str:
        """获取当前情感表达风格"""
        if self.state.joy > 0.7:
            return "活泼温暖"
        elif self.state.sadness > 0.5:
            return "低沉温柔"
        elif self.state.anger > 0.5:
            return "冷淡疏离"
        elif self.state.trust > 0.7:
            return "亲密依赖"
        elif self.state.fear > 0.5:
            return "小心翼翼"
        else:
            return "平和自然"

    def get_status_text(self) -> str:
        """获取状态文本"""
        return (
            f"**主导情绪**: {self.state.dominant}\n"
            f"**表达风格**: {self.get_expression_style()}\n"
            f"**喜悦**: {self.state.joy:.0%} | **悲伤**: {self.state.sadness:.0%}\n"
            f"**愤怒**: {self.state.anger:.0%} | **恐惧**: {self.state.fear:.0%}\n"
            f"**信任**: {self.state.trust:.0%} | **期待**: {self.state.anticipation:.0%}\n"
            f"**爱**: {self.state.love:.0%} | **悔恨**: {self.state.remorse:.0%}"
        )

    def _load(self) -> None:
        """从磁盘加载状态"""
        state_file = self.data_dir / "emotion.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                self.state = EmotionState(**data)
            except Exception as e:
                logger.warning(f"加载情感状态失败: {e}")

    def _save(self) -> None:
        """保存状态到磁盘"""
        state_file = self.data_dir / "emotion.json"
        try:
            state_file.write_text(
                json.dumps({
                    "joy": self.state.joy,
                    "sadness": self.state.sadness,
                    "anger": self.state.anger,
                    "fear": self.state.fear,
                    "trust": self.state.trust,
                    "anticipation": self.state.anticipation,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"保存情感状态失败: {e}")
