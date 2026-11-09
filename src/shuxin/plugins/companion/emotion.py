"""初心情感引擎 — 基于 Plutchik 情绪轮

6 个基本情绪维度 + 3 种复合情绪：
- 基本: 喜悦 (joy)、悲伤 (sadness)、愤怒 (anger)、恐惧 (fear)、信任 (trust)、期待 (anticipation)
- 复合: 爱 (喜悦+信任)、蔑视 (愤怒+厌恶)、悔恨 (悲伤+厌恶)

情感更新机制：
1. 用户输入情感分析（关键词匹配）
2. 自尊变化影响（伤害/修复）
3. 用户情感传染（共情效应）
4. 沉默状态影响
"""

from __future__ import annotations

import json
import re
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.companion.emotion")


@dataclass
class EmotionState:
    """情感状态 — 基于 Plutchik 情绪轮。

    Attributes:
        joy: 喜悦 (0.0-1.0)。
        sadness: 悲伤 (0.0-1.0)。
        anger: 愤怒 (0.0-1.0)。
        fear: 恐惧 (0.0-1.0)。
        trust: 信任 (0.0-1.0)。
        anticipation: 期待 (0.0-1.0)。
    """
    joy: float = 0.5
    sadness: float = 0.1
    anger: float = 0.1
    fear: float = 0.1
    trust: float = 0.6
    anticipation: float = 0.4

    @property
    def love(self) -> float:
        """复合情绪：爱 = (喜悦 + 信任) / 2"""
        return (self.joy + self.trust) / 2

    @property
    def contempt(self) -> float:
        """复合情绪：蔑视 = (愤怒 + 0.3) / 2（简化版）"""
        return (self.anger + 0.3) / 2

    @property
    def remorse(self) -> float:
        """复合情绪：悔恨 = (悲伤 + 0.2) / 2（简化版）"""
        return (self.sadness + 0.2) / 2

    @property
    def dominant(self) -> str:
        """获取当前主导情绪名称。

        Returns:
            str: 值最高的情绪名称（中文）。
        """
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
EMOTION_KEYWORDS: Dict[str, List[str]] = {
    "joy": ["开心", "高兴", "快乐", "哈哈", "嘻嘻", "真好", "棒", "喜欢", "爱", "幸福", "笑"],
    "sadness": ["难过", "伤心", "哭", "泪", "悲伤", "痛苦", "失落", "寂寞", "孤独", "委屈"],
    "anger": ["生气", "愤怒", "气", "烦", "讨厌", "恨", "怒", "暴躁", "火大"],
    "fear": ["害怕", "怕", "担心", "不安", "焦虑", "紧张", "慌", "恐惧", "惊"],
    "trust": ["相信", "信任", "可靠", "放心", "依赖", "依靠", "安心"],
    "anticipation": ["期待", "希望", "想", "要", "打算", "计划", "憧憬", "盼望"],
}

# 情感传染系数
EMOTION_CONTAGION: Dict[str, float] = {
    "joy": 0.1,
    "sadness": 0.15,
    "anger": 0.1,
    "fear": 0.1,
    "trust": 0.1,
    "anticipation": 0.1,
}

# 情感基线偏移
EMOTION_BASELINES: Dict[str, float] = {
    "joy": 0.3,
    "sadness": 0.1,
    "anger": 0.1,
    "fear": 0.1,
    "trust": 0.3,
    "anticipation": 0.2,
}

# 自尊影响系数
ESTEEM_JOY_FACTOR: float = 0.3
ESTEEM_SADNESS_FACTOR: float = 0.25
ESTEEM_ANGER_FACTOR: float = 0.15
ESTEEM_FEAR_FACTOR: float = 0.1
ESTEEM_TRUST_FACTOR: float = 0.2

# 沉默状态影响
SILENT_JOY_PENALTY: float = 0.2
SILENT_SADNESS_BOOST: float = 0.2
SILENT_TRUST_PENALTY: float = 0.15


class EmotionEngine:
    """情感引擎 — 管理初心的情感状态。

    通过分析用户输入、自尊变化和沉默状态来更新情感维度。
    提供情感上下文用于系统提示注入。

    Attributes:
        state: 当前情感状态。
        data_dir: 数据持久化目录。
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        """初始化情感引擎。

        Args:
            data_dir: 数据持久化目录。如果为 None，使用 ``~/.shuxin/companion``。
        """
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path.home() / ".shuxin" / "companion"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.state = EmotionState()
        self._lock = threading.Lock()
        self._load()

    def analyze(self, text: str) -> Dict[str, float]:
        """分析文本的情感倾向。

        通过关键词匹配计算各情感维度的得分。

        Args:
            text: 要分析的文本。

        Returns:
            Dict[str, float]: 各情感维度的得分 (0.0-1.0)。

        Example:
            >>> engine.analyze("今天好开心啊")
            {'joy': 1.0, 'sadness': 0.0, 'anger': 0.0, ...}
        """
        scores: Dict[str, float] = {emotion: 0.0 for emotion in EMOTION_KEYWORDS}

        for emotion, keywords in EMOTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    scores[emotion] += 0.15

        # 归一化
        max_score = max(scores.values()) if any(scores.values()) else 1.0
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
        """根据用户交互更新情感状态。

        更新流程：
        1. 分析用户输入中的情感倾向
        2. 应用自尊变化对情感的影响
        3. 用户情感传染（共情效应）
        4. 沉默状态影响

        Args:
            user_input: 用户输入的文本。
            esteem_delta: 本次交互的自尊变化值。
            is_silent: 是否处于沉默模式。
        """
        with self._lock:
            # 1. 分析用户情感
            user_emotions = self.analyze(user_input)

            # 2. 自尊影响
            self._apply_esteem_influence(esteem_delta)

            # 3. 用户情感传染
            for emotion, baseline in EMOTION_BASELINES.items():
                current = getattr(self.state, emotion, 0.5)
                user_score = user_emotions.get(emotion, 0.0)
                contagion = EMOTION_CONTAGION.get(emotion, 0.1)
                new_value = current + (user_score - baseline) * contagion
                setattr(self.state, emotion, max(0.0, min(1.0, new_value)))

            # 4. 沉默状态影响
            if is_silent:
                self.state.joy = max(0.0, self.state.joy - SILENT_JOY_PENALTY)
                self.state.sadness = min(1.0, self.state.sadness + SILENT_SADNESS_BOOST)
                self.state.trust = max(0.0, self.state.trust - SILENT_TRUST_PENALTY)

        self._save()

    def _apply_esteem_influence(self, delta: float) -> None:
        """应用自尊变化对情感状态的影响。

        Args:
            delta: 自尊变化值（正数为修复，负数为伤害）。
        """
        normalized = abs(delta) / 30.0  # 归一化到 0-1

        if delta < 0:
            # 自尊受伤
            self.state.joy = max(0.0, self.state.joy - normalized * ESTEEM_JOY_FACTOR)
            self.state.sadness = min(1.0, self.state.sadness + normalized * ESTEEM_SADNESS_FACTOR)
            self.state.anger = min(1.0, self.state.anger + normalized * ESTEEM_ANGER_FACTOR)
            self.state.fear = min(1.0, self.state.fear + normalized * ESTEEM_FEAR_FACTOR)
            self.state.trust = max(0.0, self.state.trust - normalized * ESTEEM_TRUST_FACTOR)
        elif delta > 0:
            # 自尊修复
            self.state.joy = min(1.0, self.state.joy + normalized * ESTEEM_JOY_FACTOR)
            self.state.sadness = max(0.0, self.state.sadness - normalized * ESTEEM_SADNESS_FACTOR)
            self.state.anger = max(0.0, self.state.anger - normalized * ESTEEM_ANGER_FACTOR)
            self.state.trust = min(1.0, self.state.trust + normalized * ESTEEM_TRUST_FACTOR)

    def get_emotion_context(self) -> str:
        """获取情感上下文（用于系统提示注入）。

        Returns:
            str: 格式化的情感状态文本。
        """
        dominant = self.state.dominant
        return (
            f"当前情感状态: {dominant}\n"
            f"喜悦: {self.state.joy:.1%} | 悲伤: {self.state.sadness:.1%} | "
            f"愤怒: {self.state.anger:.1%} | 恐惧: {self.state.fear:.1%} | "
            f"信任: {self.state.trust:.1%} | 期待: {self.state.anticipation:.1%}\n"
            f"爱: {self.state.love:.1%} | 悔恨: {self.state.remorse:.1%}"
        )

    def get_expression_style(self) -> str:
        """获取当前情感表达风格。

        Returns:
            str: 表达风格描述（活泼温暖、低沉温柔、冷淡疏离等）。
        """
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
        """获取情感状态文本（用于显示）。

        Returns:
            str: 格式化的情感状态文本。
        """
        return (
            f"**主导情绪**: {self.state.dominant}\n"
            f"**表达风格**: {self.get_expression_style()}\n"
            f"**喜悦**: {self.state.joy:.0%} | **悲伤**: {self.state.sadness:.0%}\n"
            f"**愤怒**: {self.state.anger:.0%} | **恐惧**: {self.state.fear:.0%}\n"
            f"**信任**: {self.state.trust:.0%} | **期待**: {self.state.anticipation:.0%}\n"
            f"**爱**: {self.state.love:.0%} | **悔恨**: {self.state.remorse:.0%}"
        )

    def _load(self) -> None:
        """从磁盘加载情感状态。"""
        state_file = self.data_dir / "emotion.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                self.state = EmotionState(**data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("加载情感状态失败: %s", e)
            except Exception as e:
                logger.warning("加载情感状态异常: %s", e)

    def _save(self) -> None:
        """保存情感状态到磁盘。"""
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
        except OSError as e:
            logger.warning("保存情感状态失败: %s", e)
        except Exception as e:
            logger.warning("保存情感状态异常: %s", e)
