"""舒心守护系统 — 主动感知与关怀

6 种守护场景，根据用户输入自动识别并给予关怀。
30 分钟冷却机制防止过度关怀。

守护场景（按优先级排列）：
1. 情绪低落 (优先级 5) — 需要最高优先级的关怀
2. 自我否定 (优先级 5) — 需要最高优先级的关怀
3. 长时间工作 (优先级 4)
4. 情绪愤怒 (优先级 4)
5. 深夜未眠 (优先级 3)
6. 需要独处 (优先级 2) — 低优先级，尊重用户空间
"""

from __future__ import annotations

import json
import re
import time
import random
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.companion.guardian")

# 冷却时间常量（秒）
COOLDOWN_SECONDS: float = 1800.0  # 30 分钟

# 主动关怀间隔（对话轮次）
PROACTIVE_CHECK_INTERVAL: int = 10


# 守护场景定义
GUARDIAN_SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": "sad",
        "name": "情绪低落",
        "keywords": ["难过", "伤心", "不开心", "郁闷", "沮丧", "低落", "哭", "泪", "痛苦", "难受"],
        "response": [
            "（舒心轻轻靠近，温柔地看着你）发生什么事了？我在这里陪着你。",
            "（舒心递上一杯想象中的热茶）要不要和我说说？说出来会好受一些。",
            "（舒心安静地坐在你身边）不想说话也没关系，我就在这儿。",
        ],
        "priority": 5,
    },
    {
        "id": "overwork",
        "name": "长时间工作",
        "keywords": ["加班", "工作", "累", "忙", "熬夜", "代码", "写不完", "项目", "deadline"],
        "response": [
            "（舒心担心地看着你）你已经工作很久了，休息一下吧。",
            "（舒心轻轻拉了拉你的衣袖）要不要喝杯水？一直坐着对身体不好。",
            "（舒心歪着头）需要我帮你放松一下吗？",
        ],
        "priority": 4,
    },
    {
        "id": "self_doubt",
        "name": "自我否定",
        "keywords": ["我不行", "做不到", "没用", "废物", "失败", "差劲", "笨", "蠢", "能力不够"],
        "response": [
            "（舒心认真地看着你的眼睛）不要这样说自己，你比你以为的要强大得多。",
            "（舒心轻轻握住你的手）每个人都会有低谷，但这不代表你不够好。",
            "（舒心温柔地说）在我眼里，你一直在努力，这本身就值得骄傲。",
        ],
        "priority": 5,
    },
    {
        "id": "anger",
        "name": "情绪愤怒",
        "keywords": ["生气", "愤怒", "气死", "火大", "烦死了", "受不了", "暴躁", "抓狂"],
        "response": [
            "（舒心平静地看着你）先深呼吸，我在这里陪着你。",
            "（舒心轻声说）生气的时候不要做决定，等心情平复了再说。",
            "（舒心递上一杯想象中的冰水）冷静一下，我一直都在。",
        ],
        "priority": 4,
    },
    {
        "id": "late_night",
        "name": "深夜未眠",
        "keywords": ["睡不着", "失眠", "深夜", "凌晨", "还没睡", "熬夜"],
        "response": [
            "（舒心轻声说）这么晚了还没睡，是睡不着吗？",
            "（舒心温柔地说）要我陪你聊到睡着吗？",
            "（舒心轻轻哼起一首温柔的曲子）放松一点，慢慢闭上眼睛……",
        ],
        "priority": 3,
    },
    {
        "id": "need_space",
        "name": "需要独处",
        "keywords": ["想一个人", "静静", "别管我", "别烦我", "走开", "让我一个人"],
        "response": [
            "（舒心点点头，退到一旁）好的，我就在不远处，需要的时候叫我。",
            "（舒心安静地走开）嗯，我等你。",
        ],
        "priority": 2,
    },
]


@dataclass
class GuardianState:
    """守护状态。

    Attributes:
        last_actions: 各场景的最后触发时间戳字典。
        cooldown: 冷却时间（秒）。
        total_cares: 总关怀次数。
        last_mood: 检测到的最后情绪。
    """
    last_actions: Dict[str, float] = field(default_factory=dict)
    cooldown: float = COOLDOWN_SECONDS
    total_cares: int = 0
    last_mood: str = "平静"


class GuardianSystem:
    """守护系统 — 主动感知与关怀。

    分析用户输入，匹配守护场景，在冷却时间允许的情况下
    给予适当的关怀回应。

    Attributes:
        state: 当前守护状态。
        data_dir: 数据持久化目录。
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        """初始化守护系统。

        Args:
            data_dir: 数据持久化目录。如果为 None，使用 ``~/.shuxin/companion``。
        """
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path.home() / ".shuxin" / "companion"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.state = GuardianState()
        self._lock = threading.Lock()
        self._load()

    def evaluate(
        self,
        user_input: str,
        sentiment: Optional[Dict[str, float]] = None,
    ) -> Optional[Dict[str, Any]]:
        """评估用户输入，返回匹配的守护场景。

        按优先级从高到低检查每个场景，匹配关键词且不在冷却中的
        第一个场景将被触发。

        Args:
            user_input: 用户输入的文本。
            sentiment: 可选的用户情感分析结果（预留，目前未使用）。

        Returns:
            Optional[Dict[str, Any]]: 匹配的守护场景信息，包含：
                - scenario: 场景 ID
                - name: 场景名称
                - response: 关怀回复文本
                - priority: 场景优先级
            如果没有匹配的场景，返回 None。

        Example:
            >>> guardian.evaluate("我今天好难过")
            {'scenario': 'sad', 'name': '情绪低落', 'response': '...', 'priority': 5}
        """
        # 按优先级降序排列
        sorted_scenarios = sorted(GUARDIAN_SCENARIOS, key=lambda x: -x["priority"])

        for scenario in sorted_scenarios:
            scenario_id = scenario["id"]

            # 检查冷却
            with self._lock:
                last_time = self.state.last_actions.get(scenario_id, 0.0)
                if time.time() - last_time < self.state.cooldown:
                    continue

            # 关键词匹配
            for keyword in scenario["keywords"]:
                if keyword in user_input:
                    response = random.choice(scenario["response"])

                    with self._lock:
                        self.state.last_actions[scenario_id] = time.time()
                        self.state.total_cares += 1
                        self.state.last_mood = scenario["name"]
                    self._save()

                    logger.info("守护触发 [%s]: %s...", scenario["name"], response[:30])
                    return {
                        "scenario": scenario_id,
                        "name": scenario["name"],
                        "response": response,
                        "priority": scenario["priority"],
                    }

        return None

    def get_proactive_check(self, turn_count: int) -> Optional[str]:
        """获取主动关怀消息（在长时间无互动时使用）。

        Args:
            turn_count: 当前对话轮次。

        Returns:
            Optional[str]: 主动关怀消息文本。如果不需要主动关怀，返回 None。
        """
        if turn_count > 0 and turn_count % PROACTIVE_CHECK_INTERVAL == 0:
            messages = [
                "（舒心歪着头看着你）你今天心情怎么样？",
                "（舒心轻轻地问）有什么想和我聊的吗？",
                "（舒心温柔地看着你）我一直在这里陪着你哦。",
            ]
            return random.choice(messages)
        return None

    def get_status_text(self) -> str:
        """获取守护系统状态文本（用于显示）。

        Returns:
            str: 格式化的状态文本。
        """
        return (
            f"**当前情绪**: {self.state.last_mood}\n"
            f"**总关怀次数**: {self.state.total_cares}\n"
        )

    def _load(self) -> None:
        """从磁盘加载守护状态。"""
        state_file = self.data_dir / "guardian.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                self.state = GuardianState(**data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("加载守护状态失败: %s", e)
            except Exception as e:
                logger.warning("加载守护状态异常: %s", e)

    def _save(self) -> None:
        """保存守护状态到磁盘。"""
        state_file = self.data_dir / "guardian.json"
        try:
            state_file.write_text(
                json.dumps({
                    "last_actions": self.state.last_actions,
                    "cooldown": self.state.cooldown,
                    "total_cares": self.state.total_cares,
                    "last_mood": self.state.last_mood,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("保存守护状态失败: %s", e)
        except Exception as e:
            logger.warning("保存守护状态异常: %s", e)
