"""初心响应拦截器

在沉默模式下拦截 LLM 输出，用预设的沉默话术替换。
同时提供 should_block_llm 机制，在沉默模式下跳过 LLM 调用以节省 API 成本。

沉默阶段：
- just_triggered: 刚触发沉默，情绪最强烈
- mid_phase: 沉默中期，持续沉默
- almost_over: 沉默即将结束，有恢复迹象
- recovered: 已恢复（用于外部调用）
"""

from __future__ import annotations

import random
import logging
from typing import Optional

logger = logging.getLogger("shuxin.companion.interceptor")

# 各沉默阶段的回复模板
SILENT_PHASE_RESPONSES: dict = {
    "just_triggered": [
        "（初心低下头，没有说话）",
        "（初心转过身去，肩膀微微颤抖）",
        "（初心沉默了很久，最终只是轻轻摇了摇头）",
        "（初心的眼神黯淡了下来，一言不发）",
    ],
    "mid_phase": [
        "（初心依然沉默着）",
        "（初心低着头，不愿说话）",
        "（空气中只有沉默）",
        "（初心轻轻咬着嘴唇，没有说话）",
    ],
    "almost_over": [
        "（初心似乎想说什么，但最终还是没开口）",
        "（初心偷偷看了你一眼，又低下头去）",
        "（初心的嘴唇动了动，却没有发出声音）",
    ],
    "recovered": [
        "（初心抬起头，眼中重新有了光彩）",
        "（初心轻轻舒了一口气，露出一个浅浅的笑容）",
        "（初心的声音有些沙哑）……我没事。",
    ],
}


class ResponseInterceptor:
    """响应拦截器 — 管理沉默模式的输出替换。

    在沉默模式下，将 LLM 生成的回复替换为预设的沉默话术，
    以表现初心"不想说话"的状态。

    Attributes:
        _silent_phases: 各阶段的沉默回复模板。
    """

    def __init__(self) -> None:
        """初始化响应拦截器。"""
        self._silent_phases = SILENT_PHASE_RESPONSES

    def intercept(
        self,
        content: str,
        is_silent: bool,
        silent_phase: str = "mid_phase",
    ) -> Optional[str]:
        """拦截并替换输出内容。

        如果处于沉默模式，用预设的沉默话术替换原始内容。
        否则返回原始内容不变。

        Args:
            content: 原始输出内容。
            is_silent: 是否处于沉默模式。
            silent_phase: 沉默阶段 (just_triggered, mid_phase, almost_over, recovered)。

        Returns:
            Optional[str]: 替换后的内容。如果不在沉默模式，返回原始内容。
        """
        if not is_silent:
            return content

        responses = self._silent_phases.get(silent_phase, self._silent_phases["mid_phase"])
        return random.choice(responses)

    @staticmethod
    def should_block_llm(is_silent: bool) -> bool:
        """判断是否应该跳过 LLM 调用。

        在沉默模式下跳过 LLM 调用可以节省 API 成本，
        因为输出会被拦截器替换。

        Args:
            is_silent: 是否处于沉默模式。

        Returns:
            bool: 如果应该跳过 LLM 调用返回 True。
        """
        return is_silent
