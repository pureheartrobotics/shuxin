"""
舒心智能体主循环
================

整合所有子系统的核心协调者。负责：

1. 初始化所有子系统（灵魂、身份、LLM、记忆、插件）
2. 构建系统提示（多 Slot 拼接）
3. 处理用户输入（同步/异步/流式）
4. 调度插件 Hook 链
5. 管理会话生命周期

典型用法::

    agent = Agent()
    agent.initialize()
    reply = agent.chat("你好，舒心")
    agent.shutdown()
"""

from __future__ import annotations

import os
import sys
import logging
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Generator, AsyncIterator
from dataclasses import dataclass, field

from shuxin.core.config import Config
from shuxin.core.soul import SoulEngine
from shuxin.core.identity import IdentityEngine
from shuxin.core.llm import LLMProvider, LLMMessage, LLMResponse, PROVIDER_REGISTRY
from shuxin.core.memory import MemoryManager
from shuxin.core.plugin import PluginManager

logger = logging.getLogger("shuxin.agent")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT_SLOTS: List[str] = [
    "soul",       # Slot #1: 灵魂人格
    "identity",   # Slot #2: MBTI 身份
    "memory",     # Slot #3: 长期记忆
    "plugins",    # Slot #4: 插件注入
]

# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class AgentContext:
    """智能体会话上下文 — 贯穿整个对话生命周期的状态容器。

    Attributes:
        session_id: 当前会话唯一标识。
        user_name: 用户称呼，默认为"主人"。
        turn_count: 当前会话的对话轮次计数。
        metadata: 扩展元数据存储。
    """

    session_id: str = ""
    user_name: str = "主人"
    turn_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 智能体主类
# ---------------------------------------------------------------------------


class Agent:
    """舒心智能体 — 所有功能的核心协调者。

    Args:
        config: 配置对象。为 ``None`` 时自动从默认路径加载。
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config.load()
        self.context = AgentContext()

        # 子系统（延迟初始化）
        self.soul = SoulEngine()
        self.identity = IdentityEngine()
        self.llm = LLMProvider()
        self.memory = MemoryManager(
            data_dir=str(Path(self.config.shuxin_home) / "memory")
        )
        self.plugins = PluginManager()

        # 内部状态
        self._system_prompt: str = ""
        self._initialized: bool = False
        self._lock = threading.Lock()

    # -- 初始化 ------------------------------------------------------------

    def initialize(self) -> None:
        """初始化智能体所有子系统。

        初始化顺序:
        1. 灵魂引擎（加载 SOUL.md）
        2. 身份引擎（设置 MBTI）
        3. LLM 提供者
        4. 插件系统
        5. 构建系统提示
        6. 触发 ``on_session_start`` Hook

        Raises:
            RuntimeError: 如果 LLM 提供者初始化失败（如 API 密钥缺失）。
        """
        if self._initialized:
            logger.debug("智能体已初始化，跳过重复初始化")
            return

        logger.info("正在初始化舒心智能体...")

        try:
            # 1. 加载灵魂
            self.soul.load(self.config.soul.soul_path)
            logger.info("灵魂已加载: %s (%s)", self.soul.profile.name, self.soul.profile.mbti)

            # 2. 设置身份
            self.identity.set_mbti(self.soul.profile.mbti)
            self.identity.profile.name = self.soul.profile.name
            self.identity.profile.species = self.soul.profile.species

            # 3. 初始化 LLM（支持多提供者）
            provider_type = self.config.llm.provider
            provider_info = PROVIDER_REGISTRY.get(provider_type, {})
            env_api_key = provider_info.get("env_api_key", "OPENAI_API_KEY")
            env_base_url = provider_info.get("env_base_url", "OPENAI_BASE_URL")

            api_key = self.config.llm.api_key or os.environ.get(env_api_key)
            if not api_key:
                raise RuntimeError(
                    f"未找到 API 密钥。请设置 {env_api_key} 环境变量 "
                    "或在配置文件中指定 llm.api_key"
                )

            self.llm.initialize(
                provider_type=provider_type,
                api_key=api_key,
                base_url=self.config.llm.base_url or os.environ.get(env_base_url),
                model=self.config.llm.model,
            )
            logger.info("LLM 已初始化: %s (%s)", self.config.llm.model, provider_type)

            # 4. 初始化插件系统
            self.plugins.initialize(self.config.shuxin_home)
            self.plugins.llm_provider = self.llm
            self.plugins.discover_and_load(self.config.enabled_plugins)

            # 5. 构建系统提示
            self._build_system_prompt()

            # 6. 触发会话开始 Hook
            self.plugins.invoke_hook("on_session_start", agent=self)

            self._initialized = True
            logger.info("舒心智能体初始化完成！")

        except Exception as e:
            logger.critical("智能体初始化失败: %s", e, exc_info=True)
            raise

    # -- 系统提示构建 ------------------------------------------------------

    def _build_system_prompt(self) -> None:
        """构建多 Slot 系统提示。

        Slot 顺序:
        1. 灵魂人格（SOUL.md）
        2. MBTI 身份影响
        3. 长期记忆上下文
        4. 插件注入（通过 ``pre_llm_call`` Hook）
        """
        parts: List[str] = []

        # Slot #1: 灵魂人格
        parts.append(self.soul.get_system_prompt_block())

        # Slot #2: MBTI 身份影响
        parts.append(self.identity.get_system_prompt_block())

        # Slot #3: 记忆上下文
        facts_summary = self.memory.get_facts_summary()
        parts.append(facts_summary)

        # Slot #4: 插件注入
        hook_results = self.plugins.invoke_hook("pre_llm_call", agent=self)
        for plugin_name, result in hook_results:
            if result is not None:
                parts.append(f"\n--- [{plugin_name}] ---\n{result}")

        self._system_prompt = "\n\n".join(parts)

    def get_system_prompt(self) -> str:
        """获取当前系统提示全文。

        Returns:
            完整的系统提示字符串。
        """
        return self._system_prompt

    # -- 对话核心 ----------------------------------------------------------

    def chat(self, user_input: str) -> str:
        """同步处理用户输入并返回回复。

        处理流程:
        1. 触发 ``on_user_message`` Hook
        2. 记录用户消息到短期记忆
        3. 构建 LLM 调用上下文
        4. 调用 LLM 生成回复
        5. 触发 ``transform_output`` Hook（拦截器在此生效）
        6. 记录 AI 回复到短期记忆
        7. 触发 ``on_ai_message`` Hook

        Args:
            user_input: 用户输入的文本。

        Returns:
            AI 回复文本。沉默模式下返回拦截器的预设话术。
        """
        with self._lock:
            self.context.turn_count += 1

        # 1. 触发用户消息 Hook
        self.plugins.invoke_hook("on_user_message", agent=self, message=user_input)

        # 2. 记录用户消息
        self.memory.add_message("user", user_input)

        # 动态层（长期记忆、陪伴状态、用户画像）每轮都可能变化。
        self._build_system_prompt()

        # 3. 构建上下文
        messages = self.memory.build_context(
            system_prompt=self._system_prompt,
            max_history=self.config.max_history,
        )

        # 4. 调用 LLM
        try:
            response = self.llm.chat(
                messages=[
                    LLMMessage(role=m["role"], content=m["content"])
                    for m in messages
                    if m["role"] != "system"
                ],
                system_prompt=self._system_prompt,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
            )
            final_content = response.content
        except Exception as e:
            logger.error("LLM 调用失败: %s", e, exc_info=True)
            error_msg = str(e)
            # 401 等认证错误直接抛出，让上层处理
            if "401" in error_msg or "Incorrect API key" in error_msg or "invalid_api_key" in error_msg:
                provider_type = self.config.llm.provider
                provider_info = PROVIDER_REGISTRY.get(provider_type, {})
                env_api_key = provider_info.get("env_api_key", "OPENAI_API_KEY")
                raise RuntimeError(
                    f"API 密钥无效，请检查后重试。\n"
                    f"  提供者: {provider_info.get('label', provider_type)}\n"
                    f"  环境变量: {env_api_key}\n"
                    f"  详情: {error_msg[:200]}"
                ) from e
            # 其他错误使用降级回复
            final_content = self._get_fallback_response()

        # 5. 输出转换 Hook
        hook_results = self.plugins.invoke_hook(
            "transform_output", agent=self, content=final_content
        )
        for _plugin_name, result in hook_results:
            if result is not None:
                final_content = result

        # 6. 记录 AI 回复
        self.memory.add_message("assistant", final_content)

        # 7. 触发 AI 消息 Hook
        self.plugins.invoke_hook("on_ai_message", agent=self, message=final_content)

        return final_content

    async def chat_async(self, user_input: str) -> str:
        """异步处理用户输入。

        与 ``chat()`` 流程相同，但使用异步 LLM 调用。

        Args:
            user_input: 用户输入的文本。

        Returns:
            AI 回复文本。
        """
        self.context.turn_count += 1
        self.plugins.invoke_hook("on_user_message", agent=self, message=user_input)
        self.memory.add_message("user", user_input)
        self._build_system_prompt()

        messages = self.memory.build_context(
            system_prompt=self._system_prompt,
            max_history=self.config.max_history,
        )

        try:
            response = await self.llm.chat_async(
                messages=[
                    LLMMessage(role=m["role"], content=m["content"])
                    for m in messages
                    if m["role"] != "system"
                ],
                system_prompt=self._system_prompt,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
            )
            final_content = response.content
        except Exception as e:
            logger.error("LLM 异步调用失败: %s", e)
            final_content = self._get_fallback_response()

        hook_results = self.plugins.invoke_hook(
            "transform_output", agent=self, content=final_content
        )
        for _plugin_name, result in hook_results:
            if result is not None:
                final_content = result

        self.memory.add_message("assistant", final_content)
        self.plugins.invoke_hook("on_ai_message", agent=self, message=final_content)

        return final_content

    def chat_stream(self, user_input: str) -> Generator[str, None, None]:
        """流式处理用户输入，逐 chunk 产出回复。

        适用于实时显示场景。注意：流式模式下 ``transform_output``
        Hook 仅在完整内容生成后触发一次。

        Args:
            user_input: 用户输入的文本。

        Yields:
            回复文本的连续片段。
        """
        self.context.turn_count += 1
        self.plugins.invoke_hook("on_user_message", agent=self, message=user_input)
        self.memory.add_message("user", user_input)
        self._build_system_prompt()

        messages = self.memory.build_context(
            system_prompt=self._system_prompt,
            max_history=self.config.max_history,
        )

        try:
            stream = self.llm.chat_stream(
                messages=[
                    LLMMessage(role=m["role"], content=m["content"])
                    for m in messages
                    if m["role"] != "system"
                ],
                system_prompt=self._system_prompt,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
            )

            full_content: str = ""
            for chunk in stream():
                full_content += chunk
                yield chunk

            # 输出转换 Hook（流式模式下在完成后统一处理）
            hook_results = self.plugins.invoke_hook(
                "transform_output", agent=self, content=full_content
            )
            for _plugin_name, result in hook_results:
                if result is not None and result != full_content:
                    yield f"\n\n*（舒心的情绪似乎有些变化）*"

            self.memory.add_message("assistant", full_content)
            self.plugins.invoke_hook("on_ai_message", agent=self, message=full_content)

        except Exception as e:
            logger.error("LLM 流式调用失败: %s", e)
            yield self._get_fallback_response()

    @staticmethod
    def _get_fallback_response() -> str:
        """LLM 调用失败时的降级回复。

        Returns:
            温和的降级回复文本。
        """
        return "（舒心轻轻叹了口气）抱歉，我现在有点不舒服……能等一下再聊吗？"

    # -- 命令处理 ----------------------------------------------------------

    def handle_command(self, command_line: str) -> str:
        """处理斜杠命令。

        优先查找插件注册的命令，其次处理内置命令。

        Args:
            command_line: 完整的命令字符串，如 ``"/shuxin status"``。

        Returns:
            命令执行结果文本。空字符串表示无输出。
        """
        parts = command_line.strip().split()
        if not parts:
            return ""

        cmd_name = parts[0].lstrip("/")
        args = " ".join(parts[1:]) if len(parts) > 1 else ""

        # 1. 查找插件命令
        handler = self.plugins.get_command_handler(cmd_name)
        if handler is not None:
            try:
                result = handler(args, agent=self)
                return str(result) if result is not None else ""
            except Exception as e:
                logger.error("命令执行失败 /%s: %s", cmd_name, e)
                return f"命令执行失败: {e}"

        # 2. 内置命令
        cmd_map: Dict[str, str] = {
            "help": self._get_help_text(),
            "status": self._get_status_text(),
        }

        if cmd_name == "reset":
            self.memory.clear_short_term()
            return "记忆已清空，我们重新开始吧。"

        if cmd_name == "mbti":
            if args.strip():
                self.identity.set_mbti(args.strip())
                self._build_system_prompt()
                return f"MBTI 已切换为 {args.strip().upper()}"
            return f"当前 MBTI: {self.identity.profile.mbti}"

        if cmd_name in cmd_map:
            return cmd_map[cmd_name]

        return f"未知命令: /{cmd_name}，输入 /help 查看可用命令"

    def _get_help_text(self) -> str:
        """生成帮助文本。

        Returns:
            格式化的帮助文本。
        """
        lines = [
            "## 舒心可用命令",
            "",
            "### 内置命令",
            "/help          — 显示此帮助",
            "/status        — 查看舒心当前状态",
            "/reset         — 清空会话记忆",
            "/mbti          — 查看或切换 MBTI 类型（如 /mbti ENFP）",
            "/reset-key     — 重新设置 API 密钥",
            "/switch-model  — 切换 LLM 提供者和模型",
            "",
            "### 插件命令",
        ]

        for cmd_name, desc in self.plugins.get_all_commands().items():
            lines.append(f"/{cmd_name:<10} — {desc}")

        return "\n".join(lines)

    def _get_status_text(self) -> str:
        """生成状态文本。

        Returns:
            格式化的状态信息。
        """
        plugin_names = ", ".join(
            p.manifest.name for p in self.plugins._plugins.values()
        )
        from shuxin.core.config import PROVIDER_MODELS
        provider_label = PROVIDER_MODELS.get(
            self.config.llm.provider, {}
        ).get("label", self.config.llm.provider)
        return (
            f"## 舒心状态\n\n"
            f"**名字**: {self.soul.profile.name}\n"
            f"**物种**: {self.soul.profile.species}\n"
            f"**MBTI**: {self.identity.profile.mbti}\n"
            f"**提供者**: {provider_label}\n"
            f"**模型**: {self.config.llm.model}\n"
            f"**对话轮次**: {self.context.turn_count}\n"
            f"**短期记忆**: {len(self.memory.short_term)} 条\n"
            f"**长期记忆**: {len(self.memory.facts)} 条\n"
            f"**已加载插件**: {plugin_names or '无'}"
        )

    # -- 生命周期 ----------------------------------------------------------

    def shutdown(self) -> None:
        """关闭智能体，释放资源。

        触发 ``on_session_end`` Hook 后清理内部状态。
        此方法可安全多次调用。
        """
        if not self._initialized:
            return

        logger.info("正在关闭舒心智能体...")
        try:
            self.plugins.invoke_hook("on_session_end", agent=self)
        except Exception as e:
            logger.warning("关闭时 Hook 执行异常: %s", e)

        self._initialized = False
        logger.info("舒心智能体已关闭")
