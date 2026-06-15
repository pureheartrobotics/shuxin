"""初心身份引擎 — MBTI 人格管理与身份解析

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any

import yaml

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

# MBTI 配置文件（可由数据目录覆盖）
_DEFAULT_MBTI_PROFILES_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "mbti" / "mbti_profiles.yaml"
)

# 运行时加载的 MBTI profiles（顶层 key 为 MBTI 类型）
_MBTI_PROFILES: Dict[str, Dict[str, Any]] = {}
_MBTI_PROFILES_LOADED = False


def load_mbti_profiles(path: str | Path | None = None) -> Dict[str, Dict[str, Any]]:
    """加载 data/mbti/mbti_profiles.yaml 并覆盖 MBTI 数据。

    Returns:
        dict: profiles 映射（key 为 MBTI 类型）。
    """
    global _MBTI_PROFILES, _MBTI_PROFILES_LOADED, VALID_MBTI_TYPES

    if _MBTI_PROFILES_LOADED and path is None:
        return _MBTI_PROFILES

    selected = Path(path) if path is not None else _DEFAULT_MBTI_PROFILES_PATH
    if not selected.exists():
        logger.warning("MBTI profiles 未找到: %s（将回退到硬编码数据）", selected)
        _MBTI_PROFILES = {}
        _MBTI_PROFILES_LOADED = True
        return _MBTI_PROFILES

    try:
        loaded = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("加载 MBTI profiles 失败: %s（将回退到硬编码数据）", e)
        _MBTI_PROFILES = {}
        _MBTI_PROFILES_LOADED = True
        return _MBTI_PROFILES

    if not isinstance(loaded, dict):
        logger.warning("MBTI profiles 格式错误（非对象）：%s", selected)
        _MBTI_PROFILES = {}
        _MBTI_PROFILES_LOADED = True
        return _MBTI_PROFILES

    profiles: Dict[str, Dict[str, Any]] = {}
    for mbti, entry in loaded.items():
        if not isinstance(mbti, str) or not isinstance(entry, dict):
            continue
        profiles[mbti.strip().upper()] = entry

    _MBTI_PROFILES = profiles
    _MBTI_PROFILES_LOADED = True
    if profiles:
        # 原地更新，避免其它模块通过 `from ... import VALID_MBTI_TYPES` 造成引用失效
        VALID_MBTI_TYPES.clear()
        VALID_MBTI_TYPES.update(profiles.keys())
    return _MBTI_PROFILES

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
        tagline: 标签/一句话描述（用于展示）。
        soul_snippet: 完整人格卡（可选，大文本）。
        style_anchor: 运行时风格锚点（短文本，写入 Slot2）。
        micro_anchor: 每轮微型锚点（超短文本，写入 Slot4）。
        reveal_script: 开筱/首次揭晓台词（可选）。
        factors: MBTI 行为影响因子字典。
    """
    mbti: str = "INFJ"
    name: str = "初心"
    species: str = "灵狐"
    age: int = 22
    gender: str = "无性别"
    prefix: str = "初心"
    tagline: str = ""
    soul_snippet: str = ""
    style_anchor: str = ""
    micro_anchor: str = ""
    reveal_script: str = ""
    factors: Dict[str, float] = field(default_factory=dict)


class IdentityEngine:
    """身份引擎 — 管理 MBTI 人格对行为的影响。

    提供 MBTI 类型的动态切换、描述获取、系统提示生成等功能。
    行为影响因子影响初心的共情、守护、耐心等行为倾向。

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
        # 启动时尝试加载 YAML profiles（失败则回退硬编码）
        load_mbti_profiles()
        self._load_profile_from_data()

    def _load_profile_from_data(self) -> None:
        """根据当前 MBTI 类型加载 profiles 中的行为影响因子与锚点。

        如果 profiles 没有该类型，回退到硬编码数据（INFJ 兜底）。
        """
        mbti = self.profile.mbti.upper()
        # 1) 优先使用 YAML profiles
        entry = _MBTI_PROFILES.get(mbti) if _MBTI_PROFILES_LOADED else None
        if entry:
            self.profile.tagline = str(entry.get("tagline") or "").strip() or MBTI_DESCRIPTIONS.get(mbti, "")
            self.profile.soul_snippet = str(entry.get("soul_snippet") or "").strip()
            self.profile.style_anchor = str(entry.get("style_anchor") or "").strip()
            self.profile.micro_anchor = str(entry.get("micro_anchor") or "").strip()
            self.profile.reveal_script = str(entry.get("reveal_script") or "").strip()

            factors = entry.get("companion_factors") or {}
            if isinstance(factors, dict) and factors:
                self.profile.factors = {
                    k: float(v)
                    for k, v in factors.items()
                    if isinstance(k, str) and k in FACTOR_LABELS and isinstance(v, (int, float))
                }
                # 缺字段时使用 INFJ 的对应字段兜底
                if len(self.profile.factors) < len(FACTOR_LABELS):
                    for fk, fv in MBTI_COMPANION_FACTORS.get("INFJ", {}).items():
                        self.profile.factors.setdefault(fk, float(fv))
            else:
                self.profile.factors = dict(MBTI_COMPANION_FACTORS.get(mbti) or MBTI_COMPANION_FACTORS["INFJ"])
            return

        # 2) YAML 不可用或缺失，回退硬编码
        self.profile.tagline = MBTI_DESCRIPTIONS.get(mbti, f"{mbti} — 未知类型")
        self.profile.style_anchor = self.profile.tagline
        self.profile.micro_anchor = f"保持 {mbti}：保持人格稳定，先共情后回应。"
        self.profile.soul_snippet = ""
        self.profile.reveal_script = ""
        self.profile.factors = dict(MBTI_COMPANION_FACTORS.get(mbti) or MBTI_COMPANION_FACTORS["INFJ"])

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
            self._load_profile_from_data()
            logger.info("MBTI 已切换为: %s — %s", mbti_upper, self.get_description())
        return True

    def get_description(self) -> str:
        """获取当前 MBTI 类型的描述文本。

        Returns:
            str: MBTI 类型描述。如果类型未知，返回 "未知类型"。

        Example:
            >>> engine.get_description()
            '提倡者 — 安静而神秘，富有想象力和同情心，坚持自己的价值观'
        """
        return self.profile.tagline or MBTI_DESCRIPTIONS.get(self.profile.mbti, f"{self.profile.mbti} — 未知类型")

    def get_system_prompt_block(self) -> str:
        """生成系统提示中的 MBTI 风格锚点块（Slot2）。

        Slot2 的核心目标是“人格稳定规则”：每轮都注入固定风格锚点，
        让用户对话无法诱导模型改变 MBTI 核心气质。

        Returns:
            str: 格式化的人格影响提示文本。

        Example:
            >>> engine.get_system_prompt_block()
            '### MBTI 人格影响\\n你的 MBTI 类型是 INFJ...'
        """
        lines = [
            "### MBTI 风格锚点",
            f"设备 MBTI：{self.profile.mbti}（{self.get_description()}）",
        ]
        if self.profile.soul_snippet:
            lines += ["", self.profile.soul_snippet]
        lines += ["", self.profile.style_anchor or self.get_description()]
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

    def get_micro_anchor(self) -> str:
        """获取每轮微型锚点（Slot4 追加）。"""
        return self.profile.micro_anchor or ""

    def get_reveal_script(self) -> str:
        """获取开箱/首次连接自我介绍台词。"""
        return self.profile.reveal_script or ""
