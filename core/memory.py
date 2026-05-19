"""舒心记忆系统

对标 Mem0 的记忆管理，支持短期会话记忆和长期持久化记忆。

架构：
- 短期记忆 (Short-term): 当前会话的消息历史，上限可配置
- 长期记忆 (Long-term): 持久化的事实记忆，按分类存储

事实记忆分类：
- general: 一般信息
- preference: 用户偏好
- habit: 用户习惯
- event: 重要事件
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("shuxin.memory")


@dataclass
class MemoryEntry:
    """记忆条目 — 单条消息记录。

    Attributes:
        role: 消息角色 (user, assistant, system)。
        content: 消息内容。
        timestamp: ISO 格式时间戳。
        metadata: 附加元数据字典。
    """
    role: str
    content: str
    timestamp: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FactMemory:
    """事实记忆 — 关于用户的关键信息。

    Attributes:
        key: 事实的唯一标识键。
        value: 事实的值。
        category: 事实分类 (general, preference, habit, event)。
        confidence: 置信度 (0.0-1.0)。
        created_at: 创建时间戳。
        updated_at: 最后更新时间戳。
    """
    key: str
    value: str
    category: str = "general"
    confidence: float = 1.0
    created_at: str = ""
    updated_at: str = ""


class MemoryManager:
    """记忆管理器 — 管理短期和长期记忆。

    提供消息记录、事实存储、上下文构建等功能。
    所有修改操作都是线程安全的。

    Attributes:
        data_dir: 数据持久化目录。
        short_term: 短期记忆列表（当前会话消息）。
        facts: 长期事实记忆字典。
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        """初始化记忆管理器。

        Args:
            data_dir: 数据持久化目录。如果为 None，使用 ``~/.shuxin/memory``。
        """
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path.home() / ".shuxin" / "memory"

        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("无法创建记忆目录 %s: %s", self.data_dir, e)

        # 短期记忆（会话）
        self.short_term: List[MemoryEntry] = []
        self.max_short_term: int = 100

        # 长期记忆（事实）
        self.facts: Dict[str, FactMemory] = {}

        # 线程锁
        self._lock = threading.Lock()

        # 加载持久化的事实记忆
        self._load_facts()

    # ---- 短期记忆 ----

    def add_message(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """添加消息到短期记忆。

        当短期记忆超过上限时，自动裁剪最旧的消息。

        Args:
            role: 消息角色 (user, assistant, system)。
            content: 消息内容。
            metadata: 可选的附加元数据。

        Example:
            >>> memory.add_message("user", "你好")
            >>> memory.add_message("assistant", "你好！", {"emotion": "joy"})
        """
        entry = MemoryEntry(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            metadata=metadata or {},
        )
        with self._lock:
            self.short_term.append(entry)
            if len(self.short_term) > self.max_short_term:
                self.short_term = self.short_term[-self.max_short_term:]

    def get_recent(self, n: int = 10) -> List[MemoryEntry]:
        """获取最近 n 条消息。

        Args:
            n: 要获取的消息数量。

        Returns:
            List[MemoryEntry]: 最近 n 条消息的列表。
        """
        with self._lock:
            return self.short_term[-n:]

    def get_history(self) -> List[MemoryEntry]:
        """获取完整会话历史。

        Returns:
            List[MemoryEntry]: 所有短期记忆条目的副本。
        """
        with self._lock:
            return list(self.short_term)

    def clear_short_term(self) -> None:
        """清空短期记忆。"""
        with self._lock:
            self.short_term.clear()

    # ---- 长期记忆 ----

    def add_fact(
        self,
        key: str,
        value: str,
        category: str = "general",
        confidence: float = 1.0,
    ) -> None:
        """添加或更新事实记忆。

        如果 key 已存在，更新其值、置信度和时间戳。
        如果 key 不存在，创建新的事实记录。

        Args:
            key: 事实的唯一标识键。
            value: 事实的值。
            category: 事实分类 (general, preference, habit, event)。
            confidence: 置信度 (0.0-1.0)。
        """
        now = datetime.now().isoformat()
        with self._lock:
            if key in self.facts:
                self.facts[key].value = value
                self.facts[key].confidence = confidence
                self.facts[key].updated_at = now
            else:
                self.facts[key] = FactMemory(
                    key=key,
                    value=value,
                    category=category,
                    confidence=confidence,
                    created_at=now,
                    updated_at=now,
                )
        self._save_facts()

    def get_fact(self, key: str) -> Optional[str]:
        """获取事实记忆的值。

        Args:
            key: 事实的唯一标识键。

        Returns:
            Optional[str]: 事实的值，如果不存在返回 None。
        """
        fact = self.facts.get(key)
        return fact.value if fact else None

    def get_facts_by_category(self, category: str) -> List[FactMemory]:
        """按分类获取事实记忆。

        Args:
            category: 事实分类名称。

        Returns:
            List[FactMemory]: 匹配分类的事实列表。
        """
        return [f for f in self.facts.values() if f.category == category]

    def get_all_facts(self) -> List[FactMemory]:
        """获取所有事实记忆。

        Returns:
            List[FactMemory]: 所有事实的列表。
        """
        return list(self.facts.values())

    def get_facts_summary(self) -> str:
        """获取事实记忆摘要（用于系统提示注入）。

        Returns:
            str: 格式化的事实摘要文本。如果没有事实，返回提示信息。

        Example:
            >>> memory.get_facts_summary()
            '## 关于用户的记忆\\n- 名字: 张三\\n- 喜欢的食物: 火锅'
        """
        if not self.facts:
            return "暂无关于用户的长期记忆。"

        lines = ["## 关于用户的记忆"]
        for fact in self.facts.values():
            lines.append(f"- {fact.key}: {fact.value}")
        return "\n".join(lines)

    def _load_facts(self) -> None:
        """从磁盘加载事实记忆。

        从 ``{data_dir}/facts.json`` 读取持久化的事实数据。
        如果文件不存在或格式错误，静默使用空的事实列表。
        """
        facts_file = self.data_dir / "facts.json"
        if not facts_file.exists():
            return

        try:
            data = json.loads(facts_file.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                logger.warning("事实记忆文件格式错误，期望 JSON 数组")
                return
            for item in data:
                if not isinstance(item, dict):
                    continue
                fact = FactMemory(**item)
                self.facts[fact.key] = fact
            logger.info("已加载 %d 条事实记忆", len(self.facts))
        except json.JSONDecodeError as e:
            logger.warning("事实记忆文件 JSON 解析失败: %s", e)
        except OSError as e:
            logger.warning("无法读取事实记忆文件: %s", e)
        except Exception as e:
            logger.warning("加载事实记忆失败: %s", e)

    def _save_facts(self) -> None:
        """保存事实记忆到磁盘。

        将事实数据序列化为 JSON 写入 ``{data_dir}/facts.json``。
        如果写入失败，仅记录警告，不影响运行。
        """
        facts_file = self.data_dir / "facts.json"
        try:
            data = [
                {
                    "key": f.key,
                    "value": f.value,
                    "category": f.category,
                    "confidence": f.confidence,
                    "created_at": f.created_at,
                    "updated_at": f.updated_at,
                }
                for f in self.facts.values()
            ]
            facts_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("无法写入事实记忆文件: %s", e)
        except Exception as e:
            logger.warning("保存事实记忆失败: %s", e)

    # ---- 会话管理 ----

    def build_context(self, system_prompt: str, max_history: int = 20) -> List[Dict[str, str]]:
        """构建 LLM 调用上下文消息列表。

        将系统提示和短期记忆合并为 OpenAI 格式的消息列表。

        Args:
            system_prompt: 系统提示文本。
            max_history: 包含的最大历史消息数。

        Returns:
            List[Dict[str, str]]: 格式化的消息列表，每条包含 role 和 content。

        Example:
            >>> ctx = memory.build_context("你是舒心", max_history=10)
            >>> ctx[0]
            {'role': 'system', 'content': '你是舒心'}
        """
        messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]

        with self._lock:
            for entry in self.short_term[-max_history:]:
                messages.append({"role": entry.role, "content": entry.content})

        return messages
