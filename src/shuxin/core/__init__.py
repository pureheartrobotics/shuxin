"""初心 (ChuXin) 核心框架层

提供 AI 智能体运行所需的基础设施：
- Agent: 智能体主循环
- Config: 配置管理
- LLM: 大语言模型接口抽象
- Memory: 记忆系统
- Plugin: 插件系统
- Soul: 人格系统（SOUL.md 加载）
- Identity: 身份与人格管理
"""

from shuxin.core.config import Config
from shuxin.core.llm import LLMProvider
from shuxin.core.memory import MemoryManager
from shuxin.core.plugin import PluginManager
from shuxin.core.soul import SoulEngine
from shuxin.core.identity import IdentityEngine

__all__ = [
    "Agent",
    "Config",
    "LLMProvider",
    "MemoryManager",
    "PluginManager",
    "SoulEngine",
    "IdentityEngine",
]


def __getattr__(name: str):
    if name == "Agent":
        from shuxin.core.agent import Agent

        return Agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
