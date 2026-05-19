"""舒心智能体主循环

对标 Hermes 的 Agent 核心，整合所有子系统：
人格引擎 → 身份引擎 → 记忆系统 → 插件系统 → LLM 提供者
"""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, AsyncIterator
from dataclasses import dataclass, field

from shuxin.core.config import Config
from shuxin.core.soul import SoulEngine
from shuxin.core.identity import IdentityEngine
from shuxin.core.llm import LLMProvider, LLMMessage, LLMResponse
from shuxin.core.memory import MemoryManager
from shuxin.core.plugin import PluginManager

logger = logging.getLogger("shuxin.agent")


@dataclass
class AgentContext:
    """智能体上下文 — 贯穿整个会话"""
    session_id: str = ""
    user_name: str = "主人"
    turn_count: int = 0
    metadata: Dict = field(default_factory=dict)


class Agent:
    """舒心智能体主类 — 所有功能的核心协调者"""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.load()
        self.context = AgentContext()

        # 子系统初始化
        self.soul = SoulEngine()
        self.identity = IdentityEngine()
        self.llm = LLMProvider()
        self.memory = MemoryManager(
            data_dir=str(Path(self.config.shuxin_home) / "memory")
        )
        self.plugins = PluginManager()

        # 系统提示构建
        self._system_prompt = ""
        self._initialized = False

    def initialize(self) -> None:
        """初始化智能体所有子系统"""
        if self._initialized:
            return

        logger.info("正在初始化舒心智能体...")

        # 1. 加载灵魂
        self.soul.load(self.config.soul.soul_path)
        logger.info(f"灵魂已加载: {self.soul.profile.name}")

        # 2. 设置身份
        self.identity.set_mbti(self.soul.profile.mbti)
        self.identity.profile.name = self.soul.profile.name
        self.identity.profile.species = self.soul.profile.species
        logger.info(f"身份已设置: {self.identity.profile.mbti}")

        # 3. 初始化 LLM
        self.llm.initialize(
            provider_type=self.config.llm.provider,
            api_key=self.config.llm.api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=self.config.llm.base_url or os.environ.get("OPENAI_BASE_URL"),
            model=self.config.llm.model,
        )
        logger.info(f"LLM 已初始化: {self.config.llm.model}")

        # 4. 初始化插件系统
        self.plugins.initialize(self.config.shuxin_home)
        self.plugins.llm_provider = self.llm
        self.plugins.discover_and_load(self.config.enabled_plugins)
        logger.info(f"插件系统已初始化")

        # 5. 构建系统提示
        self._build_system_prompt()

        # 6. 触发会话开始 Hook
        self.plugins.invoke_hook("on_session_start", agent=self)

        self._initialized = True
        logger.info("舒心智能体初始化完成！")

    def _build_system_prompt(self) -> None:
        """构建完整的系统提示"""
        parts = []

        # Slot #1: 灵魂人格
        parts.append(self.soul.get_system_prompt_block())

        # Slot #2: MBTI 身份影响
        parts.append(self.identity.get_system_prompt_block())

        # Slot #3: 记忆上下文
        facts_summary = self.memory.get_facts_summary()
        parts.append(facts_summary)

        # Slot #4: 插件注入（通过 pre_llm_call hook）
        hook_results = self.plugins.invoke_hook("pre_llm_call", agent=self)
        for plugin_name, result in hook_results:
            if result:
                parts.append(f"\n[{plugin_name}]\n{result}")

        self._system_prompt = "\n\n".join(parts)

    def get_system_prompt(self) -> str:
        """获取当前系统提示"""
        return self._system_prompt

    # ---- 对话核心 ----

    def chat(self, user_input: str) -> str:
        """处理用户输入并返回回复"""
        self.context.turn_count += 1

        # 1. 触发用户消息 Hook
        self.plugins.invoke_hook("on_user_message", agent=self, message=user_input)

        # 2. 记录用户消息到记忆
        self.memory.add_message("user", user_input)

        # 3. 构建消息列表
        messages = self.memory.build_context(
            system_prompt=self._system_prompt,
            max_history=self.config.max_history,
        )

        # 4. 调用 LLM
        try:
            response = self.llm.chat(
                messages=[LLMMessage(role=m["role"], content=m["content"]) for m in messages if m["role"] != "system"],
                system_prompt=self._system_prompt,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
            )
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return f"（舒心轻轻叹了口气）抱歉，我现在有点不舒服……能等一下再聊吗？"

        # 5. 输出转换 Hook
        final_content = response.content
        hook_results = self.plugins.invoke_hook(
            "transform_output", agent=self, content=final_content
        )
        for plugin_name, result in hook_results:
            if result is not None:
                final_content = result

        # 6. 记录 AI 回复到记忆
        self.memory.add_message("assistant", final_content)

        # 7. 触发 AI 消息 Hook
        self.plugins.invoke_hook("on_ai_message", agent=self, message=final_content)

        return final_content

    async def chat_async(self, user_input: str) -> str:
        """异步处理用户输入"""
        self.context.turn_count += 1

        self.plugins.invoke_hook("on_user_message", agent=self, message=user_input)
        self.memory.add_message("user", user_input)

        messages = self.memory.build_context(
            system_prompt=self._system_prompt,
            max_history=self.config.max_history,
        )

        try:
            response = await self.llm.chat_async(
                messages=[LLMMessage(role=m["role"], content=m["content"]) for m in messages if m["role"] != "system"],
                system_prompt=self._system_prompt,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
            )
        except Exception as e:
            logger.error(f"LLM 异步调用失败: {e}")
            return "（舒心轻轻叹了口气）抱歉，我现在有点不舒服……能等一下再聊吗？"

        final_content = response.content
        hook_results = self.plugins.invoke_hook(
            "transform_output", agent=self, content=final_content
        )
        for plugin_name, result in hook_results:
            if result is not None:
                final_content = result

        self.memory.add_message("assistant", final_content)
        self.plugins.invoke_hook("on_ai_message", agent=self, message=final_content)

        return final_content

    def chat_stream(self, user_input: str):
        """流式处理用户输入"""
        self.context.turn_count += 1
        self.plugins.invoke_hook("on_user_message", agent=self, message=user_input)
        self.memory.add_message("user", user_input)

        messages = self.memory.build_context(
            system_prompt=self._system_prompt,
            max_history=self.config.max_history,
        )

        try:
            stream = self.llm.chat_stream(
                messages=[LLMMessage(role=m["role"], content=m["content"]) for m in messages if m["role"] != "system"],
                system_prompt=self._system_prompt,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
            )

            full_content = ""
            for chunk in stream():
                full_content += chunk
                yield chunk

            # 输出转换 Hook
            hook_results = self.plugins.invoke_hook(
                "transform_output", agent=self, content=full_content
            )
            for plugin_name, result in hook_results:
                if result is not None:
                    # 如果拦截器替换了内容，重新 yield
                    if result != full_content:
                        yield f"\n[拦截: {result}]"

            self.memory.add_message("assistant", full_content)
            self.plugins.invoke_hook("on_ai_message", agent=self, message=full_content)

        except Exception as e:
            logger.error(f"LLM 流式调用失败: {e}")
            yield "（舒心轻轻叹了口气）抱歉，我现在有点不舒服……能等一下再聊吗？"

    # ---- 命令处理 ----

    def handle_command(self, command_line: str) -> str:
        """处理斜杠命令"""
        parts = command_line.strip().split()
        if not parts:
            return ""

        cmd_name = parts[0].lstrip("/")
        args = " ".join(parts[1:]) if len(parts) > 1 else ""

        # 查找插件命令
        handler = self.plugins.get_command_handler(cmd_name)
        if handler:
            try:
                result = handler(args, agent=self)
                return str(result) if result else ""
            except Exception as e:
                logger.error(f"命令执行失败 /{cmd_name}: {e}")
                return f"命令执行失败: {e}"

        # 内置命令
        if cmd_name == "help":
            return self._get_help_text()
        elif cmd_name == "status":
            return self._get_status_text()
        elif cmd_name == "reset":
            self.memory.clear_short_term()
            return "记忆已清空，我们重新开始吧。"
        elif cmd_name == "mbti":
            if args:
                self.identity.set_mbti(args)
                self._build_system_prompt()
                return f"MBTI 已切换为 {args.upper()}"
            return f"当前 MBTI: {self.identity.profile.mbti}"

        return f"未知命令: /{cmd_name}，输入 /help 查看可用命令"

    def _get_help_text(self) -> str:
        """获取帮助文本"""
        lines = [
            "## 舒心可用命令",
            "",
            "### 内置命令",
            "/help     — 显示此帮助",
            "/status   — 查看舒心当前状态",
            "/reset    — 清空会话记忆",
            "/mbti     — 查看或切换 MBTI 类型",
            "",
            "### 插件命令",
        ]
        for cmd_name, desc in self.plugins.get_all_commands().items():
            lines.append(f"/{cmd_name:<10} — {desc}")

        return "\n".join(lines)

    def _get_status_text(self) -> str:
        """获取状态文本"""
        return (
            f"## 舒心状态\n\n"
            f"**名字**: {self.soul.profile.name}\n"
            f"**物种**: {self.soul.profile.species}\n"
            f"**MBTI**: {self.identity.profile.mbti}\n"
            f"**对话轮次**: {self.context.turn_count}\n"
            f"**记忆条数**: {len(self.memory.short_term)}\n"
            f"**长期记忆**: {len(self.memory.facts)} 条\n"
            f"**已加载插件**: {', '.join(p.manifest.name for p in self.plugins._plugins.values())}"
        )

    # ---- 生命周期 ----

    def shutdown(self) -> None:
        """关闭智能体"""
        logger.info("正在关闭舒心智能体...")
        self.plugins.invoke_hook("on_session_end", agent=self)
        logger.info("舒心智能体已关闭")
