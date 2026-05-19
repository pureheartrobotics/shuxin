"""舒心记忆系统

对标 Mem0 的记忆管理，支持短期会话记忆和长期持久化记忆。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("shuxin.memory")


@dataclass
class MemoryEntry:
    """记忆条目"""
    role: str
    content: str
    timestamp: str = ""
    metadata: Dict = field(default_factory=dict)


@dataclass
class FactMemory:
    """事实记忆 — 关于用户的关键信息"""
    key: str
    value: str
    category: str = "general"  # general, preference, habit, event
    confidence: float = 1.0
    created_at: str = ""
    updated_at: str = ""


class MemoryManager:
    """记忆管理器 — 管理短期和长期记忆"""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path.home() / ".shuxin" / "memory"

        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 短期记忆（会话）
        self.short_term: List[MemoryEntry] = []
        self.max_short_term: int = 100

        # 长期记忆（事实）
        self.facts: Dict[str, FactMemory] = {}
        self._load_facts()

    # ---- 短期记忆 ----

    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        """添加消息到短期记忆"""
        entry = MemoryEntry(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            metadata=metadata or {},
        )
        self.short_term.append(entry)
        # 超出限制时裁剪
        if len(self.short_term) > self.max_short_term:
            self.short_term = self.short_term[-self.max_short_term:]

    def get_recent(self, n: int = 10) -> List[MemoryEntry]:
        """获取最近 n 条消息"""
        return self.short_term[-n:]

    def get_history(self) -> List[MemoryEntry]:
        """获取完整会话历史"""
        return list(self.short_term)

    def clear_short_term(self) -> None:
        """清空短期记忆"""
        self.short_term.clear()

    # ---- 长期记忆 ----

    def add_fact(self, key: str, value: str, category: str = "general", confidence: float = 1.0) -> None:
        """添加或更新事实记忆"""
        now = datetime.now().isoformat()
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
        """获取事实记忆的值"""
        fact = self.facts.get(key)
        return fact.value if fact else None

    def get_facts_by_category(self, category: str) -> List[FactMemory]:
        """按分类获取事实记忆"""
        return [f for f in self.facts.values() if f.category == category]

    def get_all_facts(self) -> List[FactMemory]:
        """获取所有事实记忆"""
        return list(self.facts.values())

    def get_facts_summary(self) -> str:
        """获取事实记忆摘要（用于系统提示）"""
        if not self.facts:
            return "暂无关于用户的长期记忆。"

        lines = ["## 关于用户的记忆"]
        for fact in self.facts.values():
            lines.append(f"- {fact.key}: {fact.value}")
        return "\n".join(lines)

    def _load_facts(self) -> None:
        """从磁盘加载事实记忆"""
        facts_file = self.data_dir / "facts.json"
        if facts_file.exists():
            try:
                data = json.loads(facts_file.read_text(encoding="utf-8"))
                for item in data:
                    fact = FactMemory(**item)
                    self.facts[fact.key] = fact
                logger.info(f"已加载 {len(self.facts)} 条事实记忆")
            except Exception as e:
                logger.warning(f"加载事实记忆失败: {e}")

    def _save_facts(self) -> None:
        """保存事实记忆到磁盘"""
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
        except Exception as e:
            logger.warning(f"保存事实记忆失败: {e}")

    # ---- 会话管理 ----

    def build_context(self, system_prompt: str, max_history: int = 20) -> List[Dict[str, str]]:
        """构建 LLM 调用上下文"""
        messages = [{"role": "system", "content": system_prompt}]

        # 添加短期记忆
        for entry in self.short_term[-max_history:]:
            messages.append({"role": entry.role, "content": entry.content})

        return messages
