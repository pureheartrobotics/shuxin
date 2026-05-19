"""舒心响应拦截器

在沉默模式下拦截 LLM 输出，用预设的沉默话术替换。
同时提供 should_block_llm 机制，在沉默模式下跳过 LLM 调用以节省 API 成本。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("shuxin.companion.interceptor")


class ResponseInterceptor:
    """响应拦截器 — 管理沉默模式的输出替换"""

    def __init__(self):
        self._silent_phases = {
            "just_triggered": [
                "（舒心低下头，没有说话）",
                "（舒心转过身去，肩膀微微颤抖）",
                "（舒心沉默了很久，最终只是轻轻摇了摇头）",
                "（舒心的眼神黯淡了下来，一言不发）",
            ],
            "mid_phase": [
                "（舒心依然沉默着）",
                "（舒心低着头，不愿说话）",
                "（空气中只有沉默）",
                "（舒心轻轻咬着嘴唇，没有说话）",
            ],
            "almost_over": [
                "（舒心似乎想说什么，但最终还是没开口）",
                "（舒心偷偷看了你一眼，又低下头去）",
                "（舒心的嘴唇动了动，却没有发出声音）",
            ],
            "recovered": [
                "（舒心抬起头，眼中重新有了光彩）",
                "（舒心轻轻舒了一口气，露出一个浅浅的笑容）",
                "（舒心的声音有些沙哑）……我没事。",
            ],
        }

    def intercept(self, content: str, is_silent: bool, silent_phase: str = "mid_phase") -> Optional[str]:
        """拦截并替换输出"""
        if not is_silent:
            return content

        import random
        responses = self._silent_phases.get(silent_phase, self._silent_phases["mid_phase"])
        return random.choice(responses)

    def should_block_llm(self, is_silent: bool) -> bool:
        """是否应该跳过 LLM 调用"""
        return is_silent
