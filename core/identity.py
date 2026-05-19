"""舒心身份引擎 — MBTI 人格管理与身份解析

对标 Hermes 的 identity.ts / resolveAgentIdentity 机制，
但更深度集成 MBTI 人格类型对行为的影响。
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.identity")


# MBTI 维度说明
MBTI_DIMENSIONS = {
    "EI": {"E": "外向", "I": "内向"},
    "SN": {"S": "实感", "N": "直觉"},
    "TF": {"T": "理性", "F": "情感"},
    "JP": {"J": "判断", "P": "感知"},
}

# MBTI 类型描述
MBTI_DESCRIPTIONS = {
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
MBTI_COMPANION_FACTORS = {
    "INFJ": {
        "empathy": 0.95,       # 共情能力
        "protectiveness": 0.85, # 守护倾向
        "patience": 0.90,      # 耐心
        "independence": 0.60,  # 独立性
        "emotional_depth": 0.95, # 情感深度
        "social_need": 0.40,   # 社交需求
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


@dataclass
class IdentityProfile:
    """身份档案"""
    mbti: str = "INFJ"
    name: str = "舒心"
    species: str = "灵狐"
    age: int = 22
    gender: str = "无性别"
    prefix: str = "舒心"       # 消息前缀
    factors: dict = field(default_factory=dict)


class IdentityEngine:
    """身份引擎 — 管理 MBTI 人格对行为的影响"""

    def __init__(self, mbti: str = "INFJ"):
        self.profile = IdentityProfile(mbti=mbti)
        self._load_factors()

    def _load_factors(self) -> None:
        """根据 MBTI 加载行为影响因子"""
        mbti = self.profile.mbti.upper()
        if mbti in MBTI_COMPANION_FACTORS:
            self.profile.factors = dict(MBTI_COMPANION_FACTORS[mbti])
        else:
            # 默认使用 INFJ 因子
            self.profile.factors = dict(MBTI_COMPANION_FACTORS["INFJ"])

    def set_mbti(self, mbti: str) -> None:
        """动态切换 MBTI 类型"""
        mbti = mbti.upper()
        if mbti in MBTI_DESCRIPTIONS:
            self.profile.mbti = mbti
            self._load_factors()
            logger.info(f"MBTI 已切换为: {mbti} — {MBTI_DESCRIPTIONS[mbti]}")
        else:
            logger.warning(f"未知的 MBTI 类型: {mbti}")

    def get_description(self) -> str:
        """获取 MBTI 描述"""
        return MBTI_DESCRIPTIONS.get(
            self.profile.mbti, f"{self.profile.mbti} — 未知类型"
        )

    def get_system_prompt_block(self) -> str:
        """生成系统提示中的人格影响块"""
        lines = [
            f"### MBTI 人格影响",
            f"你的 MBTI 类型是 {self.profile.mbti}（{self.get_description()}）",
            f"",
            f"这会影响你的行为方式：",
        ]
        for factor, value in self.profile.factors.items():
            level = "极高" if value >= 0.9 else "较高" if value >= 0.75 else "中等" if value >= 0.6 else "较低"
            lines.append(f"- {factor}: {level}（{value:.0%}）")

        return "\n".join(lines)

    def get_response_prefix(self, context: Optional[Dict] = None) -> str:
        """获取响应前缀（用于消息格式化）"""
        return self.profile.prefix

    def resolve_emotion_style(self) -> Dict[str, float]:
        """根据 MBTI 解析情感表达风格"""
        return dict(self.profile.factors)
