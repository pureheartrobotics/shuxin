"""舒心身份引擎 — MBTI 人格管理与身份解析

对标 Hermes 的 identity.ts / resolveAgentIdentity 机制，
但更深度集成 MBTI 人格类型对行为的影响。

支持 16 种 MBTI 类型，每种类型有 6 个行为影响因子：
- empathy: 共情能力
- protectiveness: 守护倾向
- patience: 耐心
- independence: 独立性
- emotional_depth: 情感深度
- social_need: 社交需求
"""

from __future__ import annotations

import logging
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.identity")

# MBTI 维度说明
MBTI_DIMENSIONS: Dict[str, Dict[str, str]] = {
    "EI": {"E": "外向", "I": "内向"},
    "SN": {"S": "实感", "N": "直觉"},
    "TF": {"T": "理性", "F": "情感"},
    "JP": {"J": "判断", "P": "感知"},
}

# MBTI 类型描述
MBTI_DESCRIPTIONS: Dict[str, str] = {
    "INFJ": "提倡者 — 安静而神秘，富有想象力和同情心，坚持自己的价值观",
    "INFP": "调停者 — 诗意而善良，理想主义者，总是为边缘群体发声",
    "INTJ": "建筑师 — 有想象力和战略性的思想家，一切皆在计划之中",
    "INTP": "逻辑学家 — 具有创造力的发明家，对知识有着永不满足的渴望",
    "ENFJ": "主人公 — 富有魅力的领导者，能够激励他人",
    "ENFP": "竞选者 — 热情而富有创造力，总是看到可能性",
    "ENTJ": "指挥官 — 大胆而意志坚强的领导者，善于制定长远规划",
    "ENTP": "辩论家 — 聪明而好奇的思想者，不放过任何智力挑战",
    "ISFJ": "守卫者 — 非常专注而温暖，守护所爱之人",
    "ISFP": "探险家 — 灵活而有魅力的艺术家，总是准备好探索新体验",
    "ISTJ": "物流师 — 安静而可靠，注重事实和细节",
    "ISTP": "鉴赏家 — 大胆而实际的实验者，擅长使用各种工具",
    "ESFJ": "执政官 — 富有爱心而受欢迎，总是热心提供帮助",
    "ESFP": "表演者 — 自发的、精力充沛的表演者，享受被关注",
    "ESTJ": "总经理 — 出色的管理者，善于管理事务和人员",
    "ESTP": "企业家 — 聪明而精力充沛的冒险者，享受活在当下",
}

# MBTI 对陪伴行为的影响因子
MBTI_COMPANION_FACTORS: Dict[str, Dict[str, float]] = {
    "INFJ": {
        "empathy": 0.95,
        "protectiveness": 0.85,
        "patience": 0.90,
        "independence": 0.60,
        "emotional_depth": 0.95,
        "social_need": 0.40,
    },
    "INFP": {
        "empathy": 0.90,
        "protectiveness": 0.75,
        "patience": 0.85,
        "independence": 0.65,
        "emotional_depth": 0.90,
        "social_need": 0.45,
    },
    "ENFJ": {
        "empathy": 0.90,
        "protectiveness": 0.80,
        "patience": 0.80,
        "independence": 0.55,
        "emotional_depth": 0.85,
        "social_need": 0.80,
    },
    "ISFJ": {
        "empathy": 0.85,
        "protectiveness": 0.90,
        "patience": 0.95,
        "independence": 0.50,
        "emotional_depth": 0.80,
        "social_need": 0.50,
    },
    "ENFP": {
        "empathy": 0.85,
        "protectiveness": 0.70,
        "patience": 0.70,
        "independence": 0.70,
        "emotional_depth": 0.80,
        "social_need": 0.85,
    },
}

# 有效 MBTI 类型集合（用于快速验证）
VALID_MBTI_TYPES: set = set(MBTI_DESCRIPTIONS.keys())

# 因子中文名称映射
FACTOR_LABELS: Dict[str, str] = {
    "empathy": "共情能力",
    "protectiveness": "守护倾向",
    "patience": "耐心",
    "independence": "独立性",
    "emotional_depth": "情感深度",
    "social_need": "社交需求",
}

# 因子等级映射
FACTOR_LEVELS: list = [
    (0.9, "极高"),
    (0.75, "较高"),
    (0.6, "中等"),
    (0.0, "较低"),
]


def _get_factor_level(value: float) -> str:
    """获取因子等级的文本描述。

    Args:
        value: 因子值 (0.0-1.0)。

    Returns:
        str: 等级描述（极高/较高/中等/较低）。
    """
    for threshold, label in FACTOR_LEVELS:
        if value >= threshold:
            return label
    return "较低"


@dataclass
class IdentityProfile:
    """身份档案。

    Attributes:
        mbti: MBTI 人格类型代码。
        name: 角色名称。
        species: 种族/物种。
        age: 年龄。
        gender: 性别。
        prefix: 消息前缀。
        factors: MBTI 行为影响因子字典。
    """
    mbti: str = "INFJ"
    name: str = "舒心"
    species: str = "灵狐"
    age: int = 22
    gender: str = "无性别"
    prefix: str = "舒心"
    factors: Dict[str, float] = field(default_factory=dict)


class IdentityEngine:
    """身份引擎 — 管理 MBTI 人格对行为的影响。

    提供 MBTI 类型的动态切换、描述获取、系统提示生成等功能。
    行为影响因子影响舒心的共情、守护、耐心等行为倾向。

    Attributes:
        profile: 当前身份档案。
    """

    def __init__(self, mbti: str = "INFJ") -> None:
        """初始化身份引擎。

        Args:
            mbti: 初始 MBTI 类型，默认为 INFJ。
                  如果提供的类型无效，将回退到 INFJ。
        """
        self.profile = IdentityProfile(mbti=mbti)
        self._lock = threading.Lock()
        self._load_factors()

    def _load_factors(self) -> None:
        """根据当前 MBTI 类型加载行为影响因子。

        如果当前 MBTI 类型没有定义因子，使用 INFJ 作为默认值。
        """
        mbti = self.profile.mbti.upper()
        if mbti in MBTI_COMPANION_FACTORS:
            self.profile.factors = dict(MBTI_COMPANION_FACTORS[mbti])
        else:
            logger.debug("未找到 MBTI 类型 %s 的因子定义，使用 INFJ 默认值", mbti)
            self.profile.factors = dict(MBTI_COMPANION_FACTORS["INFJ"])

    def set_mbti(self, mbti: str) -> bool:
        """动态切换 MBTI 类型。

        Args:
            mbti: 目标 MBTI 类型代码（如 "ENFJ", "ISFJ"）。
                  不区分大小写。

        Returns:
            bool: 切换是否成功。如果类型无效返回 False。

        Example:
            >>> engine = IdentityEngine("INFJ")
            >>> engine.set_mbti("ENFJ")
            True
            >>> engine.set_mbti("INVALID")
            False
        """
        mbti_upper = mbti.upper()
        if mbti_upper not in VALID_MBTI_TYPES:
            logger.warning("未知的 MBTI 类型: %s", mbti)
            return False

        with self._lock:
            self.profile.mbti = mbti_upper
            self._load_factors()
            logger.info("MBTI 已切换为: %s — %s", mbti_upper, MBTI_DESCRIPTIONS[mbti_upper])
        return True

    def get_description(self) -> str:
        """获取当前 MBTI 类型的描述文本。

        Returns:
            str: MBTI 类型描述。如果类型未知，返回 "未知类型"。

        Example:
            >>> engine.get_description()
            '提倡者 — 安静而神秘，富有想象力和同情心，坚持自己的价值观'
        """
        return MBTI_DESCRIPTIONS.get(
            self.profile.mbti,
            f"{self.profile.mbti} — 未知类型",
        )

    def get_system_prompt_block(self) -> str:
        """生成系统提示中的人格影响块。

        包含 MBTI 类型描述和各行为因子的等级。

        Returns:
            str: 格式化的人格影响提示文本。

        Example:
            >>> engine.get_system_prompt_block()
            '### MBTI 人格影响\\n你的 MBTI 类型是 INFJ...'
        """
        lines = [
            f"### MBTI 人格影响",
            f"你的 MBTI 类型是 {self.profile.mbti}（{self.get_description()}）",
            "",
            f"这会影响你的行为方式：",
        ]
        for factor, value in self.profile.factors.items():
            label = FACTOR_LABELS.get(factor, factor)
            level = _get_factor_level(value)
            lines.append(f"- {label}: {level}（{value:.0%}）")

        return "\n".join(lines)

    def get_response_prefix(self, context: Optional[Dict[str, Any]] = None) -> str:
        """获取响应前缀（用于消息格式化）。

        Args:
            context: 可选的上下文信息，目前未使用。

        Returns:
            str: 消息前缀，通常是角色名称。
        """
        return self.profile.prefix

    def resolve_emotion_style(self) -> Dict[str, float]:
        """根据 MBTI 解析情感表达风格。

        Returns:
            Dict[str, float]: 行为影响因子字典的副本。

        Example:
            >>> engine.resolve_emotion_style()
            {'empathy': 0.95, 'protectiveness': 0.85, ...}
        """
        return dict(self.profile.factors)
