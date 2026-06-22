"""
初心智能体主循环
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
    reply = agent.chat("你好，初心")
    agent.shutdown()
"""

from __future__ import annotations

import os
import sys
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any, Generator, AsyncIterator, Callable
from dataclasses import dataclass, field

from shuxin.core.config import Config
from shuxin.core.soul import SoulEngine
from shuxin.core.identity import IdentityEngine
from shuxin.core.llm import LLMProvider, LLMMessage, LLMResponse, LLMToolCall, PROVIDER_REGISTRY
from shuxin.core.memory import MemoryManager
from shuxin.core.plugin import PluginManager
from shuxin.integrations.location import get_location_provider, should_attach_location_tools
from shuxin.integrations.location.dsml import extract_dsml_tool_calls, strip_dsml_blocks
from shuxin.integrations.location.fallback import (
    infer_poi_query,
    infer_search_region,
    infer_weather_region,
    is_tool_result_usable,
    should_direct_poi_search,
    should_direct_weather_call,
)
from shuxin.integrations.location.provider import LocationContext, LocationToolProvider
from shuxin.integrations.location.tool_args import (
    normalize_map_search_places_args,
    normalize_map_weather_args,
)

logger = logging.getLogger("shuxin.agent")

# ---------------------------------------------------------------------------
# LLM 错误分类
# ---------------------------------------------------------------------------


def classify_llm_error(exc: BaseException) -> str:
    """Map provider exceptions to stable voice-facing error kinds."""
    name = type(exc).__name__.lower()
    message = str(exc).lower()

    if "timeout" in name or "timeout" in message or "timed out" in message:
        if "connect" in message:
            return "connect_timeout"
        return "read_timeout"
    if "authentication" in name or "permission" in name:
        return "auth_error"
    if any(token in message for token in ("401", "403", "invalid api key", "authentication")):
        return "auth_error"
    if "connect" in name or "connection" in message or "network" in message:
        return "connect_error"
    return "llm_error"

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


@dataclass
class ToolLoopCallbacks:
    """地图等 tool loop 生命周期回调（供 Voice 发 thinking 等事件）。"""

    on_tool_round_start: Optional[Callable[[str], None]] = None
    on_tool_round_end: Optional[Callable[[], None]] = None


# ---------------------------------------------------------------------------
# 智能体主类
# ---------------------------------------------------------------------------


class Agent:
    """初心智能体 — 所有功能的核心协调者。

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
        self.tool_loop_callbacks: Optional[ToolLoopCallbacks] = None
        self._location_provider: Optional[LocationToolProvider] = None

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

        logger.info("正在初始化初心智能体...")

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

            # 5b. 地图 provider（无 AK 时 is_available() 为 False）
            self._location_provider = get_location_provider(self.config.map)

            # 6. 触发会话开始 Hook
            self.plugins.invoke_hook("on_session_start", agent=self)

            self._initialized = True
            logger.info("初心智能体初始化完成！")

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

    def _location_tools_enabled(self, user_input: str) -> bool:
        provider = self._location_provider or get_location_provider(self.config.map)
        if not provider.is_available():
            return False
        return should_attach_location_tools(user_input, self.config.map)

    def _build_llm_messages(self) -> List[LLMMessage]:
        messages = self.memory.build_context(
            system_prompt=self._system_prompt,
            max_history=self.config.max_history,
        )
        return [
            LLMMessage(role=m["role"], content=m["content"])
            for m in messages
            if m["role"] != "system"
        ]

    def _tool_calls_to_openai(self, tool_calls: List[Any]) -> List[Dict[str, Any]]:
        payload: List[Dict[str, Any]] = []
        for call in tool_calls:
            payload.append(
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments,
                    },
                }
            )
        return payload

    def _invoke_tool_callbacks(self, start: bool, reason: str = "map_lookup") -> None:
        if self.tool_loop_callbacks is None:
            return
        if start and self.tool_loop_callbacks.on_tool_round_start:
            self.tool_loop_callbacks.on_tool_round_start(reason)
        if not start and self.tool_loop_callbacks.on_tool_round_end:
            self.tool_loop_callbacks.on_tool_round_end()

    def _get_location_context_struct(self) -> Optional[LocationContext]:
        raw = self.context.metadata.get("location_ctx")
        if isinstance(raw, dict):
            return LocationContext.from_metadata_dict(raw)
        text = str(self.context.metadata.get("location_context") or "").strip()
        if text:
            return LocationContext(label=text, source="text", confidence="low")
        return None

    def _normalize_map_tool_call(
        self,
        name: str,
        args: Dict[str, Any],
        *,
        user_input: str = "",
    ) -> Optional[Dict[str, Any]]:
        """将 LLM/DSML 传入的 map 工具参数归一化为百度 MCP 可接受的 schema。"""
        ctx = self._get_location_context_struct()
        if name == "map_weather":
            normalized = normalize_map_weather_args(args, ctx)
            if normalized:
                return normalized
            region = infer_weather_region(user_input, ctx)
            if region:
                return normalize_map_weather_args({"region": region}, ctx)
            return None
        if name == "map_search_places":
            query = str(args.get("query") or infer_poi_query(user_input) or "美食")
            merged = dict(args)
            merged.setdefault("query", query)
            return normalize_map_search_places_args(merged, ctx, default_query=query)
        return args if isinstance(args, dict) else {}

    def _execute_map_tool(
        self,
        provider: LocationToolProvider,
        name: str,
        args: Dict[str, Any],
        *,
        user_input: str = "",
    ) -> Optional[str]:
        normalized = self._normalize_map_tool_call(name, args, user_input=user_input)
        if not normalized:
            logger.warning("地图工具参数无法归一化 [%s]: %s", name, args)
            return None
        try:
            result = provider.call_tool(name, normalized)
        except Exception as exc:
            logger.warning("地图工具执行失败 [%s]: %s", name, exc)
            return None
        if not is_tool_result_usable(result):
            logger.warning("地图工具返回不可用 [%s]: %.120s", name, result or "")
            return None
        return result

    def _append_direct_tool_result(
        self,
        working: List[LLMMessage],
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        result: str,
        call_id_prefix: str,
    ) -> bool:
        if not is_tool_result_usable(result):
            logger.warning("直调 %s 返回不可用结果，跳过", tool_name)
            return False
        call_id = f"{call_id_prefix}_{uuid.uuid4().hex[:12]}"
        working.append(
            LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                ],
            )
        )
        working.append(
            LLMMessage(
                role="tool",
                content=result,
                tool_call_id=call_id,
                name=tool_name,
            )
        )
        return True

    def _try_direct_weather_fallback(
        self,
        working: List[LLMMessage],
        *,
        user_input: str,
        provider: LocationToolProvider,
    ) -> bool:
        """模型未调 tool 时服务端直调 map_weather，成功则追加 tool 消息。"""
        if not should_direct_weather_call(user_input):
            return False

        ctx = self._get_location_context_struct()
        weather_args = normalize_map_weather_args({}, ctx)
        if not weather_args:
            region_hint = infer_weather_region(user_input, ctx)
            weather_args = normalize_map_weather_args(
                {"region": region_hint} if region_hint else {},
                ctx,
            )
        if not weather_args:
            logger.warning("天气直调降级：无法构造 map_weather 参数，跳过")
            return False

        result = self._execute_map_tool(
            provider, "map_weather", weather_args, user_input=user_input
        )
        if result is None:
            return False

        ok = self._append_direct_tool_result(
            working,
            tool_name="map_weather",
            arguments=weather_args,
            result=result,
            call_id_prefix="direct_weather",
        )
        if ok:
            logger.info("天气直调降级成功: %s", weather_args)
        return ok

    def _try_direct_poi_fallback(
        self,
        working: List[LLMMessage],
        *,
        user_input: str,
        provider: LocationToolProvider,
    ) -> bool:
        """模型未调 tool 时服务端直调 map_search_places。"""
        if not should_direct_poi_search(user_input):
            return False

        ctx = self._get_location_context_struct()
        query = infer_poi_query(user_input)
        poi_args = normalize_map_search_places_args(
            {"query": query},
            ctx,
            default_query=query,
        )
        if not poi_args:
            logger.warning("POI 直调降级：无法构造 map_search_places 参数，跳过")
            return False

        result = self._execute_map_tool(
            provider, "map_search_places", poi_args, user_input=user_input
        )
        if result is None:
            return False

        ok = self._append_direct_tool_result(
            working,
            tool_name="map_search_places",
            arguments=poi_args,
            result=result,
            call_id_prefix="direct_poi",
        )
        if ok:
            logger.info("POI 直调降级成功: %s", poi_args)
        return ok

    def _prepare_location_messages(
        self,
        llm_messages: List[LLMMessage],
        *,
        user_input: str,
    ) -> List[LLMMessage]:
        """地图消息准备：天气/POI 明确意图走服务端直调，其余走 tool loop。"""
        if not self._location_tools_enabled(user_input):
            self.context.metadata.pop("map_tool_ms", None)
            return llm_messages

        provider = self._location_provider or get_location_provider(self.config.map)
        working = list(llm_messages)
        started = time.perf_counter()

        if should_direct_weather_call(user_input) or should_direct_poi_search(user_input):
            self._invoke_tool_callbacks(start=True)
            try:
                prefetched = False
                if should_direct_weather_call(user_input):
                    prefetched = self._try_direct_weather_fallback(
                        working, user_input=user_input, provider=provider
                    )
                if not prefetched and should_direct_poi_search(user_input):
                    prefetched = self._try_direct_poi_fallback(
                        working, user_input=user_input, provider=provider
                    )
            finally:
                self._invoke_tool_callbacks(start=False)
            if prefetched:
                self.context.metadata["map_tool_ms"] = int(
                    (time.perf_counter() - started) * 1000
                )
                logger.info("地图快路径直调成功，跳过同步 tool 选路")
                return working

        working, _direct = self._run_location_tool_loop(working, user_input=user_input)
        self.context.metadata["map_tool_ms"] = int((time.perf_counter() - started) * 1000)
        return working

    def _run_location_tool_loop(
        self,
        llm_messages: List[LLMMessage],
        *,
        user_input: str,
    ) -> tuple[List[LLMMessage], Optional[str]]:
        """执行地图 tool loop；返回更新后的 messages（不再把模型拒答当最终回复）。"""
        provider = self._location_provider or get_location_provider(self.config.map)
        channel = str(self.context.metadata.get("channel") or "cli")
        tools = provider.list_openai_tools(channel=channel)
        if not tools:
            return llm_messages, None

        working = list(llm_messages)
        max_rounds = max(1, int(self.config.map.max_tool_rounds))

        for _ in range(max_rounds):
            self._invoke_tool_callbacks(start=True)
            try:
                response = self.llm.chat(
                    messages=working,
                    system_prompt=self._system_prompt,
                    temperature=self.config.llm.temperature,
                    max_tokens=self.config.llm.max_tokens,
                    tools=tools,
                    tool_choice="auto",
                )
            finally:
                self._invoke_tool_callbacks(start=False)

            if not response.tool_calls:
                dsml_calls = extract_dsml_tool_calls(response.content or "")
                if dsml_calls:
                    logger.info(
                        "DSML tool calls parsed: %s",
                        [c.name for c in dsml_calls],
                    )
                    response_tool_calls = [
                        LLMToolCall(id=c.id, name=c.name, arguments=c.arguments)
                        for c in dsml_calls
                    ]
                else:
                    response_tool_calls = None
            else:
                response_tool_calls = response.tool_calls

            if not response_tool_calls:
                if self._try_direct_weather_fallback(
                    working, user_input=user_input, provider=provider
                ):
                    return working, None
                if self._try_direct_poi_fallback(
                    working, user_input=user_input, provider=provider
                ):
                    return working, None
                return working, None

            assistant_content = strip_dsml_blocks(response.content or "")
            executed: list[tuple[Any, Dict[str, Any], str]] = []
            for call in response_tool_calls:
                try:
                    args = json.loads(call.arguments or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except json.JSONDecodeError:
                    args = {}

                normalized = self._normalize_map_tool_call(
                    call.name, args, user_input=user_input
                )
                if not normalized:
                    logger.warning("跳过无效工具调用 [%s]: %s", call.name, args)
                    continue

                result = self._execute_map_tool(
                    provider,
                    call.name,
                    normalized,
                    user_input=user_input,
                )
                if result is None:
                    continue
                executed.append((call, normalized, result))

            if not executed:
                if self._try_direct_weather_fallback(
                    working, user_input=user_input, provider=provider
                ):
                    return working, None
                if self._try_direct_poi_fallback(
                    working, user_input=user_input, provider=provider
                ):
                    return working, None
                return working, None

            openai_calls: List[Dict[str, Any]] = []
            for call, normalized, _result in executed:
                openai_calls.append(
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(normalized, ensure_ascii=False),
                        },
                    }
                )
            working.append(
                LLMMessage(
                    role="assistant",
                    content=assistant_content,
                    tool_calls=openai_calls,
                )
            )
            for call, _normalized, result in executed:
                working.append(
                    LLMMessage(
                        role="tool",
                        content=result,
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )

        return working, None

    def _generate_llm_reply(self, llm_messages: List[LLMMessage], *, user_input: str) -> str:
        llm_messages = self._prepare_location_messages(
            llm_messages, user_input=user_input
        )

        response = self.llm.chat(
            messages=llm_messages,
            system_prompt=self._system_prompt,
            temperature=self.config.llm.temperature,
            max_tokens=self.config.llm.max_tokens,
        )
        return strip_dsml_blocks(response.content or "")

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
        llm_messages = self._build_llm_messages()

        blocked_content = self._get_blocked_llm_response()
        if blocked_content is not None:
            self.memory.add_message("assistant", blocked_content)
            self.plugins.invoke_hook("on_ai_message", agent=self, message=blocked_content)
            return blocked_content

        # 4. 调用 LLM（含可选地图 tool loop）
        try:
            final_content = self._generate_llm_reply(llm_messages, user_input=user_input)
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

        llm_messages = self._build_llm_messages()

        blocked_content = self._get_blocked_llm_response()
        if blocked_content is not None:
            self.memory.add_message("assistant", blocked_content)
            self.plugins.invoke_hook("on_ai_message", agent=self, message=blocked_content)
            return blocked_content

        try:
            llm_messages_for_reply = self._prepare_location_messages(
                llm_messages, user_input=user_input
            )
            response = await self.llm.chat_async(
                messages=llm_messages_for_reply,
                system_prompt=self._system_prompt,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
            )
            final_content = strip_dsml_blocks(response.content or "")
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

        llm_messages = self._build_llm_messages()

        blocked_content = self._get_blocked_llm_response()
        if blocked_content is not None:
            self.memory.add_message("assistant", blocked_content)
            self.plugins.invoke_hook("on_ai_message", agent=self, message=blocked_content)
            yield blocked_content
            return

        try:
            llm_messages_for_stream = self._prepare_location_messages(
                llm_messages, user_input=user_input
            )

            stream = self.llm.chat_stream(
                messages=llm_messages_for_stream,
                system_prompt=self._system_prompt,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
            )

            full_content: str = ""
            for chunk in stream:
                full_content += chunk
                yield chunk

            if not self._is_speakable_reply(full_content):
                fallback = self._empty_reply_fallback()
                full_content = fallback
                yield fallback

            # 输出转换 Hook（流式模式下在完成后统一处理）
            hook_results = self.plugins.invoke_hook(
                "transform_output", agent=self, content=full_content
            )
            for _plugin_name, result in hook_results:
                if result is not None and result != full_content:
                    yield f"\n\n*（初心的情绪似乎有些变化）*"

            self.memory.add_message("assistant", full_content)
            self.plugins.invoke_hook("on_ai_message", agent=self, message=full_content)

        except Exception as e:
            error_kind = classify_llm_error(e)
            self.context.metadata["llm_error_kind"] = error_kind
            logger.exception("LLM 流式调用失败 [kind=%s]", error_kind)
            yield self._get_fallback_response()

    def _get_blocked_llm_response(self) -> Optional[str]:
        """Return a plugin replacement when calling the LLM would be wasted."""
        sentinel = f"__shuxin_no_llm_probe_{uuid.uuid4().hex}__"
        hook_results = self.plugins.invoke_hook(
            "transform_output", agent=self, content=sentinel
        )
        for _plugin_name, result in hook_results:
            if result is not None and result != sentinel:
                return result
        return None

    @staticmethod
    def _is_speakable_reply(text: str) -> bool:
        """流式/TTS 是否有可朗读正文（非空且非纯括号动作）。"""
        from shuxin.voice.text_sanitize import prepare_speakable_text

        return bool(prepare_speakable_text(text or ""))

    @staticmethod
    def _empty_reply_fallback() -> str:
        return "地图数据暂时没查出来，你可以告诉我大概在哪个区，我再帮你查天气或附近吃的。"

    @staticmethod
    def _get_fallback_response() -> str:
        """LLM 调用失败时的降级回复。"""
        return "模型连接有点慢，刚才没有及时响应。我们稍等一下再试。"

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
            "## 初心可用命令",
            "",
            "### 内置命令",
            "/help          — 显示此帮助",
            "/status        — 查看初心当前状态",
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
            f"## 初心状态\n\n"
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

        logger.info("正在关闭初心智能体...")
        try:
            self.plugins.invoke_hook("on_session_end", agent=self)
        except Exception as e:
            logger.warning("关闭时 Hook 执行异常: %s", e)

        self._initialized = False
        logger.info("初心智能体已关闭")
