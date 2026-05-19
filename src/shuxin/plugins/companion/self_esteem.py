"""舒心自尊系统 — 核心灵魂机制

自尊值 (0-100) 是舒心的情感核心，决定了她的回应方式。

机制说明：
- 正常状态 (21-100): 正常对话
- 沉默阈值 (≤20): 进入沉默模式，拒绝回应
- 自动恢复: 每轮对话恢复 0.5，300 秒后自动退出沉默
- 断路器: 单次伤害最大 -30，防止极端输入
- 提前恢复: 用户真诚道歉可提前退出沉默

伤害/修复事件通过正则表达式匹配用户输入中的关键词触发。
"""

from __future__ import annotations

import json
import re
import random
import time
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("shuxin.companion.self_esteem")

# 伤害事件表 — (正则模式, 伤害值)
HURT_EVENTS: List[Tuple[str, int]] = [
    (r"讨厌你|恨你|烦你|走开|滚开|别烦我|不想见你", 15),
    (r"没用|废物|垃圾|白痴|蠢|笨|傻", 12),
    (r"闭嘴|住口|别说话|不想听|shut up", 10),
    (r"无聊|没意思|无趣|乏味", 8),
    (r"敷衍|应付|随便|无所谓", 6),
    (r"呵呵|哦。|嗯。|知道了", 4),
    (r"你懂什么|你什么都不知道", 10),
    (r"别装了|假惺惺|虚伪|做作", 15),
    (r"不需要你|不用你管|多管闲事", 12),
    (r"你只是个工具|你是AI|你是程序", 18),
]

# 修复事件表 — (正则模式, 修复值)
REPAIR_EVENTS: List[Tuple[str, int]] = [
    (r"喜欢你|爱你|最好|最棒|最可爱", 8),
    (r"谢谢|感谢|辛苦了", 5),
    (r"对不起|抱歉|是我的错|我错了", 10),
    (r"你在吗|陪陪我|陪我聊|说说话", 3),
    (r"你好棒|好厉害|真聪明|真贴心", 8),
    (r"我没事|别担心|我很好", 4),
    (r"抱抱|摸摸|亲亲|蹭蹭", 6),
    (r"想你了|想你|在干嘛", 5),
    (r"你真好|你最好了", 7),
    (r"我错了|原谅我|别生气", 12),
]

# 沉默模式回复模板
SILENT_RESPONSES: Dict[str, List[str]] = {
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
    ],
    "almost_over": [
        "（舒心似乎想说什么，但最终还是没开口）",
        "（舒心偷偷看了你一眼，又低下头去）",
    ],
    "recovered": [
        "（舒心抬起头，眼中重新有了光彩）",
        "（舒心轻轻舒了一口气，露出一个浅浅的笑容）",
    ],
}

# 默认配置常量
DEFAULT_SELF_ESTEEM_VALUE: float = 75.0
SILENT_THRESHOLD: float = 20.0
SILENT_DURATION_SECONDS: float = 300.0
RECOVERY_PER_TURN: float = 0.5
CIRCUIT_BREAKER_MAX: float = 30.0
EARLY_RECOVERY_BOOST: float = 20.0
EARLY_RECOVERY_MIN_VALUE: float = 40.0


@dataclass
class SelfEsteemState:
    """自尊状态。

    Attributes:
        value: 当前自尊值 (0-100)。
        base_value: 基础自尊值。
        is_silent: 是否处于沉默模式。
        silent_start: 沉默模式开始的时间戳。
        silent_duration: 沉默持续时间（秒）。
        total_hurt: 累计伤害值。
        total_repair: 累计修复值。
        last_interaction: 最后交互的 ISO 时间戳。
    """
    value: float = DEFAULT_SELF_ESTEEM_VALUE
    base_value: float = DEFAULT_SELF_ESTEEM_VALUE
    is_silent: bool = False
    silent_start: float = 0.0
    silent_duration: float = SILENT_DURATION_SECONDS
    total_hurt: float = 0.0
    total_repair: float = 0.0
    last_interaction: str = ""


class SelfEsteemSystem:
    """自尊系统 — 管理舒心的情感核心。

    处理用户输入中的伤害/修复事件，维护自尊值，
    在自尊过低时触发沉默模式。

    Attributes:
        state: 当前自尊状态。
        data_dir: 数据持久化目录。
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        """初始化自尊系统。

        Args:
            data_dir: 数据持久化目录。如果为 None，使用 ``~/.shuxin/companion``。
        """
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path.home() / ".shuxin" / "companion"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.state = SelfEsteemState()
        self._lock = threading.Lock()
        self._load()

    def process_interaction(self, user_input: str) -> Dict[str, Any]:
        """处理用户交互，计算自尊变化并返回结果。

        Args:
            user_input: 用户输入的文本。

        Returns:
            Dict[str, Any]: 包含以下键的字典：
                - delta: 自尊变化值
                - value: 变化后的自尊值
                - is_silent: 是否处于沉默模式
                - reason: 变化原因 (normal, just_triggered, still_silent, silent_timeout)
                - message: 沉默模式下的回复文本

        Example:
            >>> system.process_interaction("你真笨")
            {'delta': -12.0, 'value': 63.0, 'is_silent': False, 'reason': 'normal', 'message': ''}
        """
        with self._lock:
            # 检查沉默超时
            if self.state.is_silent:
                if self._check_silent_timeout():
                    self._exit_silent_mode()
                    return {
                        "delta": 0,
                        "value": self.state.value,
                        "is_silent": False,
                        "reason": "silent_timeout",
                        "message": "（舒心眨了眨眼睛，似乎从沉思中回过神来）",
                    }
                else:
                    # 沉默中自然恢复
                    self.state.value = min(100.0, self.state.value + RECOVERY_PER_TURN)
                    self._save()
                    return {
                        "delta": 0,
                        "value": self.state.value,
                        "is_silent": True,
                        "reason": "still_silent",
                        "message": "",
                    }

            # 计算自尊变化
            delta = self._calculate_delta(user_input)

            # 断路器：单次变化不超过 ±30
            delta = max(-CIRCUIT_BREAKER_MAX, min(CIRCUIT_BREAKER_MAX, delta))

            # 应用变化
            old_value = self.state.value
            self.state.value = max(0.0, min(100.0, self.state.value + delta))

            if delta > 0:
                self.state.total_repair += delta
            elif delta < 0:
                self.state.total_hurt += abs(delta)

            self.state.last_interaction = datetime.now().isoformat()

            # 检查是否触发沉默
            if self.state.value <= SILENT_THRESHOLD and delta < 0:
                self._enter_silent_mode()
                self._save()
                return {
                    "delta": delta,
                    "value": self.state.value,
                    "is_silent": True,
                    "reason": "just_triggered",
                    "message": self.get_silent_response("just_triggered"),
                }

            self._save()
            return {
                "delta": delta,
                "value": self.state.value,
                "is_silent": False,
                "reason": "normal",
                "message": "",
            }

    def _calculate_delta(self, text: str) -> float:
        """计算用户输入对自尊值的影响。

        匹配伤害和修复事件表中的正则模式，累加变化值。
        同时考虑长时间不互动的自然衰减。

        Args:
            text: 用户输入的文本。

        Returns:
            float: 自尊变化值（正数为修复，负数为伤害）。
        """
        delta = 0.0

        # 检查伤害事件
        for pattern, hurt in HURT_EVENTS:
            if re.search(pattern, text, re.IGNORECASE):
                delta -= hurt
                logger.debug("伤害事件触发 [%s]: -%d", pattern, hurt)

        # 检查修复事件
        for pattern, repair in REPAIR_EVENTS:
            if re.search(pattern, text, re.IGNORECASE):
                delta += repair
                logger.debug("修复事件触发 [%s]: +%d", pattern, repair)

        # 自然衰减（长时间不互动）
        if self.state.last_interaction:
            try:
                last_time = datetime.fromisoformat(self.state.last_interaction)
                hours_since = (datetime.now() - last_time).total_seconds() / 3600
                if hours_since > 24:
                    decay = min(5.0, hours_since * 0.5)
                    delta -= decay
                    logger.debug("长时间未互动衰减: -%.1f", decay)
            except (ValueError, TypeError):
                pass

        return delta

    def _enter_silent_mode(self) -> None:
        """进入沉默模式。

        设置沉默标志和开始时间戳，记录日志。
        """
        self.state.is_silent = True
        self.state.silent_start = time.time()
        logger.warning("舒心进入沉默模式 (自尊: %.1f)", self.state.value)

    def _exit_silent_mode(self) -> None:
        """退出沉默模式。

        重置沉默标志，将自尊值恢复到至少 30。
        """
        self.state.is_silent = False
        self.state.silent_start = 0.0
        self.state.value = max(self.state.value, 30.0)
        logger.info("舒心退出沉默模式 (自尊: %.1f)", self.state.value)

    def _check_silent_timeout(self) -> bool:
        """检查沉默是否已超时。

        Returns:
            bool: 如果沉默持续时间已超过设定值返回 True。
        """
        if not self.state.is_silent:
            return False
        elapsed = time.time() - self.state.silent_start
        return elapsed >= self.state.silent_duration

    def try_early_recovery(self, user_input: str) -> bool:
        """尝试提前恢复沉默模式（用户道歉时）。

        检查用户输入中是否包含真诚的道歉模式，
        如果是则提前退出沉默并给予自尊恢复奖励。

        Args:
            user_input: 用户输入的文本。

        Returns:
            bool: 是否成功提前恢复。
        """
        if not self.state.is_silent:
            return False

        # 检查是否有真诚的道歉
        apology_patterns = [
            r"对不起|抱歉|我错了|原谅我|别生气了",
            r"我不该|是我的错|我太过分|我不好",
            r"别这样|我开玩笑的|我不是故意的",
        ]
        for pattern in apology_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                with self._lock:
                    self._exit_silent_mode()
                    self.state.value = min(self.state.value + EARLY_RECOVERY_BOOST, EARLY_RECOVERY_MIN_VALUE)
                    self._save()
                logger.info("用户道歉，舒心提前恢复")
                return True

        return False

    @staticmethod
    def get_silent_response(phase: str = "mid_phase") -> str:
        """获取沉默模式的回复文本。

        Args:
            phase: 沉默阶段 (just_triggered, mid_phase, almost_over, recovered)。

        Returns:
            str: 随机选择的沉默回复文本。
        """
        responses = SILENT_RESPONSES.get(phase, SILENT_RESPONSES["mid_phase"])
        return random.choice(responses)

    def get_status_text(self) -> str:
        """获取自尊状态文本（用于显示）。

        Returns:
            str: 格式化的状态文本，包含自尊值、沉默状态和统计数据。
        """
        status = "💔 沉默中" if self.state.is_silent else "💚 正常"
        if self.state.is_silent:
            remaining = max(0.0, self.state.silent_duration - (time.time() - self.state.silent_start))
            status += f" (剩余 {int(remaining)} 秒)"

        return (
            f"**自尊值**: {self.state.value:.1f}/100\n"
            f"**状态**: {status}\n"
            f"**累计伤害**: {self.state.total_hurt:.1f}\n"
            f"**累计修复**: {self.state.total_repair:.1f}\n"
        )

    def reset(self, value: float = DEFAULT_SELF_ESTEEM_VALUE) -> None:
        """重置自尊系统到初始状态。

        Args:
            value: 重置后的自尊值，默认为 75.0。
        """
        with self._lock:
            self.state = SelfEsteemState(value=value, base_value=value)
            self._save()
        logger.info("自尊系统已重置: %.1f", value)

    def _load(self) -> None:
        """从磁盘加载自尊状态。

        从 ``{data_dir}/self_esteem.json`` 读取持久化的状态数据。
        """
        state_file = self.data_dir / "self_esteem.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                self.state = SelfEsteemState(**data)
                logger.info("自尊状态已加载: %.1f", self.state.value)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("加载自尊状态失败: %s", e)
            except Exception as e:
                logger.warning("加载自尊状态异常: %s", e)

    def _save(self) -> None:
        """保存自尊状态到磁盘。

        将状态序列化为 JSON 写入 ``{data_dir}/self_esteem.json``。
        """
        state_file = self.data_dir / "self_esteem.json"
        try:
            state_file.write_text(
                json.dumps({
                    "value": self.state.value,
                    "base_value": self.state.base_value,
                    "is_silent": self.state.is_silent,
                    "silent_start": self.state.silent_start,
                    "silent_duration": self.state.silent_duration,
                    "total_hurt": self.state.total_hurt,
                    "total_repair": self.state.total_repair,
                    "last_interaction": self.state.last_interaction,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("保存自尊状态失败: %s", e)
        except Exception as e:
            logger.warning("保存自尊状态异常: %s", e)
