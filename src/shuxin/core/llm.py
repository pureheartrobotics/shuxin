"""初心 LLM 提供者抽象层

对标 Hermes 的 provider 系统，支持多模型后端切换。

架构：
- BaseLLMProvider: 抽象基类，定义统一接口
- OpenAIProvider: OpenAI 兼容 API 实现（OpenAI、DeepSeek、Together AI 等）
- AnthropicProvider: Anthropic Claude API 实现
- LLMProvider: 门面类，提供懒加载和统一入口

支持同步、异步和流式三种调用模式。
"""

from __future__ import annotations

import os
import logging
import threading
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, AsyncIterator, Iterator
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.llm")

DEFAULT_LLM_READ_TIMEOUT_SECONDS = 60.0
DEFAULT_LLM_CONNECT_TIMEOUT_SECONDS = 5.0
LLM_TIMEOUT_ENV = "SHUXIN_LLM_TIMEOUT_SECONDS"
LLM_CONNECT_TIMEOUT_ENV = "SHUXIN_LLM_CONNECT_TIMEOUT_SECONDS"


def _get_llm_read_timeout_seconds() -> float:
    """Return the LLM read timeout configured for low-latency voice use."""
    raw = os.environ.get(LLM_TIMEOUT_ENV, str(DEFAULT_LLM_READ_TIMEOUT_SECONDS))
    try:
        timeout = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "无效的 %s=%r，使用默认 %.1fs",
            LLM_TIMEOUT_ENV,
            raw,
            DEFAULT_LLM_READ_TIMEOUT_SECONDS,
        )
        return DEFAULT_LLM_READ_TIMEOUT_SECONDS
    if timeout <= 0:
        logger.warning(
            "无效的 %s=%r，使用默认 %.1fs",
            LLM_TIMEOUT_ENV,
            raw,
            DEFAULT_LLM_READ_TIMEOUT_SECONDS,
        )
        return DEFAULT_LLM_READ_TIMEOUT_SECONDS
    return timeout


def _get_llm_connect_timeout_seconds() -> float:
    raw = os.environ.get(
        LLM_CONNECT_TIMEOUT_ENV,
        str(DEFAULT_LLM_CONNECT_TIMEOUT_SECONDS),
    )
    try:
        timeout = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_LLM_CONNECT_TIMEOUT_SECONDS
    if timeout <= 0:
        return DEFAULT_LLM_CONNECT_TIMEOUT_SECONDS
    return timeout


def _get_llm_timeout() -> Any:
    """Build granular httpx timeouts so connect failures fail fast."""
    import httpx

    return httpx.Timeout(
        connect=_get_llm_connect_timeout_seconds(),
        read=_get_llm_read_timeout_seconds(),
        write=10.0,
        pool=2.0,
    )


@dataclass
class LLMMessage:
    """LLM 消息。

    Attributes:
        role: 消息角色 (system, user, assistant)。
        content: 消息内容。
    """
    role: str
    content: str


@dataclass
class LLMResponse:
    """LLM 响应。

    Attributes:
        content: 响应文本内容。
        model: 使用的模型名称。
        usage: Token 使用统计。
        finish_reason: 结束原因 (stop, length, content_filter 等)。
    """
    content: str
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: str = ""


class BaseLLMProvider(ABC):
    """LLM 提供者抽象基类。

    所有 LLM 后端必须实现此接口，支持同步、异步和流式三种调用模式。
    """

    @abstractmethod
    def chat(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """同步对话调用。

        Args:
            messages: 消息历史列表。
            system_prompt: 可选的系统提示，将作为 system 角色消息插入。
            temperature: 生成温度 (0.0-2.0)。
            max_tokens: 最大生成 token 数。
            **kwargs: 额外的提供者特定参数。

        Returns:
            LLMResponse: LLM 响应。

        Raises:
            ConnectionError: API 连接失败时抛出。
            RuntimeError: API 返回错误时抛出。
        """
        ...

    @abstractmethod
    async def chat_async(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """异步对话调用。

        Args:
            messages: 消息历史列表。
            system_prompt: 可选的系统提示。
            temperature: 生成温度。
            max_tokens: 最大生成 token 数。
            **kwargs: 额外的提供者特定参数。

        Returns:
            LLMResponse: LLM 响应。

        Raises:
            ConnectionError: API 连接失败时抛出。
            RuntimeError: API 返回错误时抛出。
        """
        ...

    @abstractmethod
    def chat_stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> Iterator[str]:
        """流式对话调用。

        Args:
            messages: 消息历史列表。
            system_prompt: 可选的系统提示。
            temperature: 生成温度。
            max_tokens: 最大生成 token 数。
            **kwargs: 额外的提供者特定参数。

        Yields:
            str: 流式响应的文本片段。

        Raises:
            ConnectionError: API 连接失败时抛出。
            RuntimeError: API 返回错误时抛出。
        """
        ...


class OpenAIProvider(BaseLLMProvider):
    """OpenAI 兼容 API 提供者。

    支持 OpenAI、Azure OpenAI 以及任何兼容 OpenAI 格式的 API
    （如 DeepSeek、Together AI、vLLM 等）。

    Attributes:
        api_key: API 密钥。
        base_url: API 基础地址。
        model: 模型名称。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o",
    ) -> None:
        """初始化 OpenAI 提供者。

        Args:
            api_key: API 密钥。如果为 None，从 OPENAI_API_KEY 环境变量读取。
            base_url: API 基础地址。如果为 None，从 OPENAI_BASE_URL 环境变量读取。
            model: 模型名称。

        Raises:
            ImportError: 当 openai 包未安装时抛出。
        """
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "需要安装 openai 包: pip install openai"
            ) from e

        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = _normalize_openai_base_url(
            base_url or os.environ.get("OPENAI_BASE_URL", "")
        )
        self.model = model

        client_kwargs: Dict[str, Any] = {
            "api_key": self.api_key,
            "timeout": _get_llm_timeout(),
            "max_retries": 0,
        }
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self._client = OpenAI(**client_kwargs)
        self._async_client: Optional[Any] = None
        self._lock = threading.Lock()

    @property
    def async_client(self) -> Any:
        """懒加载异步客户端。

        Returns:
            AsyncOpenAI: 异步 OpenAI 客户端实例。
        """
        if self._async_client is None:
            with self._lock:
                if self._async_client is None:
                    from openai import AsyncOpenAI
                    client_kwargs: Dict[str, Any] = {
                        "api_key": self.api_key,
                        "timeout": _get_llm_timeout(),
                        "max_retries": 0,
                    }
                    if self.base_url:
                        client_kwargs["base_url"] = self.base_url
                    self._async_client = AsyncOpenAI(**client_kwargs)
        return self._async_client

    @staticmethod
    def _to_openai_messages(
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """将内部消息格式转换为 OpenAI API 格式。

        Args:
            messages: 内部消息列表。
            system_prompt: 可选的系统提示。

        Returns:
            List[Dict[str, str]]: OpenAI 格式的消息列表。
        """
        result: List[Dict[str, str]] = []
        if system_prompt:
            result.append({"role": "system", "content": system_prompt})
        for msg in messages:
            result.append({"role": msg.role, "content": msg.content})
        return result

    def chat(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """同步对话调用。

        Args:
            messages: 消息历史列表。
            system_prompt: 可选的系统提示。
            temperature: 生成温度。
            max_tokens: 最大生成 token 数。
            **kwargs: 额外的 OpenAI API 参数。

        Returns:
            LLMResponse: LLM 响应。

        Raises:
            ConnectionError: API 连接失败时抛出。
            RuntimeError: API 返回错误时抛出。
        """
        openai_messages = self._to_openai_messages(messages, system_prompt)
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            choice = response.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
                finish_reason=choice.finish_reason or "",
            )
        except Exception as e:
            logger.error("LLM 同步调用失败 [model=%s]: %s", self.model, e)
            raise

    async def chat_async(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """异步对话调用。

        Args:
            messages: 消息历史列表。
            system_prompt: 可选的系统提示。
            temperature: 生成温度。
            max_tokens: 最大生成 token 数。
            **kwargs: 额外的 OpenAI API 参数。

        Returns:
            LLMResponse: LLM 响应。

        Raises:
            ConnectionError: API 连接失败时抛出。
            RuntimeError: API 返回错误时抛出。
        """
        openai_messages = self._to_openai_messages(messages, system_prompt)
        try:
            response = await self.async_client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            choice = response.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
                finish_reason=choice.finish_reason or "",
            )
        except Exception as e:
            logger.error("LLM 异步调用失败 [model=%s]: %s", self.model, e)
            raise

    def chat_stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> Iterator[str]:
        """流式对话调用。

        Args:
            messages: 消息历史列表。
            system_prompt: 可选的系统提示。
            temperature: 生成温度。
            max_tokens: 最大生成 token 数。
            **kwargs: 额外的 OpenAI API 参数。

        Yields:
            str: 流式响应的文本片段。

        Raises:
            ConnectionError: API 连接失败时抛出。
            RuntimeError: API 返回错误时抛出。
        """
        openai_messages = self._to_openai_messages(messages, system_prompt)

        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **kwargs,
            )
            think_filter = _ThinkTagFilter()
            for chunk in stream:
                if not chunk.choices:
                    continue
                raw = _openai_stream_delta_text(chunk.choices[0].delta)
                piece = think_filter.feed(raw) if raw else ""
                if piece:
                    yield piece
        except Exception as e:
            logger.error("LLM 流式调用失败 [model=%s]: %s", self.model, e)
            raise


def _normalize_openai_base_url(base_url: str) -> str:
    """Ensure OpenAI-compatible clients target the /v1 API prefix."""
    url = str(base_url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/v1"):
        return url
    return f"{url}/v1"


_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "</" + "think" + ">"


class _ThinkTagFilter:
    """State machine: strip `` blocks from streamed content."""

    def __init__(self) -> None:
        self._in_think = False
        self._buf = ""

    @staticmethod
    def _partial_tag_suffix(text: str, tag: str) -> int:
        max_keep = min(len(text), len(tag) - 1)
        for keep in range(max_keep, 0, -1):
            if text.endswith(tag[:keep]):
                return keep
        return 0

    def feed(self, text: str) -> str:
        """Feed a chunk; return speakable text (may be empty)."""
        self._buf += text
        out_parts: list[str] = []
        while True:
            if self._in_think:
                end = self._buf.find(_THINK_CLOSE)
                if end == -1:
                    keep = self._partial_tag_suffix(self._buf, _THINK_CLOSE)
                    self._buf = self._buf[len(self._buf) - keep :]
                    break
                self._buf = self._buf[end + len(_THINK_CLOSE) :]
                self._in_think = False
            else:
                start = self._buf.find(_THINK_OPEN)
                if start == -1:
                    keep = self._partial_tag_suffix(self._buf, _THINK_OPEN)
                    out_parts.append(self._buf[: len(self._buf) - keep])
                    self._buf = self._buf[len(self._buf) - keep :]
                    break
                out_parts.append(self._buf[:start])
                self._buf = self._buf[start + len(_THINK_OPEN) :]
                self._in_think = True
        return "".join(out_parts)


def _openai_stream_delta_text(delta: Any) -> str:
    """Extract speakable text from OpenAI-compatible stream deltas.

    reasoning_content (DeepSeek-R1/QwQ etc.) is never user-facing; log at DEBUG only.
    """
    reasoning = getattr(delta, "reasoning_content", None) or ""
    if reasoning:
        logger.debug("[LLM-REASONING] %.120s", reasoning)

    content = getattr(delta, "content", None) or ""
    return content


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude API 提供者。

    支持 Claude 系列模型（claude-3-opus, claude-3-sonnet, claude-3-haiku 等）。

    Attributes:
        api_key: API 密钥。
        base_url: API 基础地址。
        model: 模型名称。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
    ) -> None:
        """初始化 Anthropic 提供者。

        Args:
            api_key: API 密钥。如果为 None，从 ANTHROPIC_API_KEY 环境变量读取。
            base_url: API 基础地址。如果为 None，从 ANTHROPIC_BASE_URL 环境变量读取。
            model: 模型名称。

        Raises:
            ImportError: 当 anthropic 包未安装时抛出。
        """
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise ImportError(
                "需要安装 anthropic 包: pip install shuxin-agent[anthropic]"
            ) from e

        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL", "")
        self.model = model

        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self._client = Anthropic(**client_kwargs)
        self._async_client: Optional[Any] = None
        self._lock = threading.Lock()

    @property
    def async_client(self) -> Any:
        """懒加载异步客户端。

        Returns:
            AsyncAnthropic: 异步 Anthropic 客户端实例。
        """
        if self._async_client is None:
            with self._lock:
                if self._async_client is None:
                    from anthropic import AsyncAnthropic
                    client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
                    if self.base_url:
                        client_kwargs["base_url"] = self.base_url
                    self._async_client = AsyncAnthropic(**client_kwargs)
        return self._async_client

    @staticmethod
    def _to_anthropic_messages(
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        """将内部消息格式转换为 Anthropic Messages API 格式。

        Anthropic 的 system prompt 是顶层参数，不在 messages 数组中。

        Args:
            messages: 内部消息列表。
            system_prompt: 可选的系统提示。

        Returns:
            (system, messages) 元组，其中 system 是顶层 system prompt 字符串，
            messages 是 Anthropic 格式的消息列表。
        """
        anthropic_messages: List[Dict[str, Any]] = []
        for msg in messages:
            role = "assistant" if msg.role == "assistant" else "user"
            anthropic_messages.append({
                "role": role,
                "content": msg.content,
            })
        return system_prompt, anthropic_messages

    def chat(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """同步对话调用。

        Args:
            messages: 消息历史列表。
            system_prompt: 可选的系统提示。
            temperature: 生成温度。
            max_tokens: 最大生成 token 数。
            **kwargs: 额外的 Anthropic API 参数。

        Returns:
            LLMResponse: LLM 响应。

        Raises:
            ConnectionError: API 连接失败时抛出。
            RuntimeError: API 返回错误时抛出。
        """
        system, anthropic_messages = self._to_anthropic_messages(messages, system_prompt)
        try:
            create_kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": anthropic_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                **kwargs,
            }
            if system:
                create_kwargs["system"] = system

            response = self._client.messages.create(**create_kwargs)

            content = ""
            for block in response.content:
                if block.type == "text":
                    content += block.text

            return LLMResponse(
                content=content,
                model=response.model,
                usage={
                    "input_tokens": response.usage.input_tokens if response.usage else 0,
                    "output_tokens": response.usage.output_tokens if response.usage else 0,
                },
                finish_reason=response.stop_reason or "",
            )
        except Exception as e:
            logger.error("Anthropic 同步调用失败 [model=%s]: %s", self.model, e)
            raise

    async def chat_async(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """异步对话调用。

        Args:
            messages: 消息历史列表。
            system_prompt: 可选的系统提示。
            temperature: 生成温度。
            max_tokens: 最大生成 token 数。
            **kwargs: 额外的 Anthropic API 参数。

        Returns:
            LLMResponse: LLM 响应。

        Raises:
            ConnectionError: API 连接失败时抛出。
            RuntimeError: API 返回错误时抛出。
        """
        system, anthropic_messages = self._to_anthropic_messages(messages, system_prompt)
        try:
            create_kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": anthropic_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                **kwargs,
            }
            if system:
                create_kwargs["system"] = system

            response = await self.async_client.messages.create(**create_kwargs)

            content = ""
            for block in response.content:
                if block.type == "text":
                    content += block.text

            return LLMResponse(
                content=content,
                model=response.model,
                usage={
                    "input_tokens": response.usage.input_tokens if response.usage else 0,
                    "output_tokens": response.usage.output_tokens if response.usage else 0,
                },
                finish_reason=response.stop_reason or "",
            )
        except Exception as e:
            logger.error("Anthropic 异步调用失败 [model=%s]: %s", self.model, e)
            raise

    def chat_stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> Iterator[str]:
        """流式对话调用。

        Args:
            messages: 消息历史列表。
            system_prompt: 可选的系统提示。
            temperature: 生成温度。
            max_tokens: 最大生成 token 数。
            **kwargs: 额外的 Anthropic API 参数。

        Yields:
            str: 流式响应的文本片段。

        Raises:
            ConnectionError: API 连接失败时抛出。
            RuntimeError: API 返回错误时抛出。
        """
        system, anthropic_messages = self._to_anthropic_messages(messages, system_prompt)
        try:
            create_kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": anthropic_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
                **kwargs,
            }
            if system:
                create_kwargs["system"] = system

            stream = self._client.messages.create(**create_kwargs)
            for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield event.delta.text
        except Exception as e:
            logger.error("Anthropic 流式调用失败 [model=%s]: %s", self.model, e)
            raise


# 提供者注册表：名称 -> (实现类, 环境变量密钥名, 默认模型)
PROVIDER_REGISTRY: Dict[str, Dict[str, Any]] = {
    "openai": {
        "class": OpenAIProvider,
        "env_api_key": "OPENAI_API_KEY",
        "env_base_url": "OPENAI_BASE_URL",
        "default_model": "gpt-4o",
        "label": "OpenAI",
        "description": "OpenAI GPT 系列模型（需科学上网）",
    },
    "openai-compatible": {
        "class": OpenAIProvider,
        "env_api_key": "OPENAI_API_KEY",
        "env_base_url": "OPENAI_BASE_URL",
        "default_model": "gpt-4o",
        "label": "OpenAI 兼容",
        "description": "兼容 OpenAI API 格式的第三方服务（DeepSeek、Together AI、vLLM 等）",
    },
    "anthropic": {
        "class": AnthropicProvider,
        "env_api_key": "ANTHROPIC_API_KEY",
        "env_base_url": "ANTHROPIC_BASE_URL",
        "default_model": "claude-3-5-sonnet-20241022",
        "label": "Anthropic",
        "description": "Anthropic Claude 系列模型",
    },
    "deepseek": {
        "class": OpenAIProvider,
        "env_api_key": "DEEPSEEK_API_KEY",
        "env_base_url": "DEEPSEEK_BASE_URL",
        "default_model": "deepseek-chat",
        "label": "DeepSeek",
        "description": "DeepSeek 系列模型（国产，性价比高）",
    },
}


class LLMProvider:
    """LLM 提供者门面 — 统一接口。

    封装底层 LLM 提供者，提供懒加载和统一的调用入口。
    支持同步、异步和流式三种调用模式。

    Attributes:
        config: 提供者配置字典。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """初始化 LLM 提供者门面。

        Args:
            config: 可选的配置字典。
        """
        self.config: Dict[str, Any] = config or {}
        self._provider: Optional[BaseLLMProvider] = None
        self._lock = threading.Lock()

    def initialize(self, provider_type: str = "openai", **kwargs: Any) -> None:
        """初始化 LLM 提供者。

        Args:
            provider_type: 提供者类型，支持 "openai", "openai-compatible", "anthropic", "deepseek"。
            **kwargs: 提供者特定的初始化参数
                      (api_key, base_url, model 等)。

        Raises:
            ValueError: 不支持的提供者类型时抛出。

        Example:
            >>> provider = LLMProvider()
            >>> provider.initialize("openai", model="gpt-4o")
            >>> provider.initialize("anthropic", model="claude-3-5-sonnet-20241022")
            >>> provider.initialize("deepseek", model="deepseek-chat")
        """
        with self._lock:
            provider_info = PROVIDER_REGISTRY.get(provider_type)
            if provider_info is None:
                raise ValueError(
                    f"不支持的 LLM 提供者: {provider_type}。"
                    f" 支持的提供者: {', '.join(PROVIDER_REGISTRY.keys())}"
                )

            provider_class = provider_info["class"]
            env_api_key = provider_info["env_api_key"]
            env_base_url = provider_info["env_base_url"]
            default_model = provider_info["default_model"]

            api_key = kwargs.get("api_key") or os.environ.get(env_api_key)
            base_url = kwargs.get("base_url") or os.environ.get(env_base_url, "")
            model = kwargs.get("model", default_model)

            self._provider = provider_class(
                api_key=api_key,
                base_url=base_url,
                model=model,
            )

            logger.info(
                "LLM 提供者已初始化: %s [model=%s]",
                provider_type, model,
            )

    @property
    def provider(self) -> BaseLLMProvider:
        """获取底层 LLM 提供者实例。

        Returns:
            BaseLLMProvider: 已初始化的 LLM 提供者。

        Raises:
            RuntimeError: 如果提供者尚未初始化。
        """
        if self._provider is None:
            raise RuntimeError("LLM 提供者未初始化，请先调用 initialize()")
        return self._provider

    def chat(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """同步对话调用（委托给底层提供者）。

        Args:
            messages: 消息历史列表。
            system_prompt: 可选的系统提示。
            temperature: 生成温度。
            max_tokens: 最大生成 token 数。
            **kwargs: 额外的提供者特定参数。

        Returns:
            LLMResponse: LLM 响应。
        """
        return self.provider.chat(messages, system_prompt, temperature, max_tokens, **kwargs)

    async def chat_async(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """异步对话调用（委托给底层提供者）。

        Args:
            messages: 消息历史列表。
            system_prompt: 可选的系统提示。
            temperature: 生成温度。
            max_tokens: 最大生成 token 数。
            **kwargs: 额外的提供者特定参数。

        Returns:
            LLMResponse: LLM 响应。
        """
        return await self.provider.chat_async(messages, system_prompt, temperature, max_tokens, **kwargs)

    def chat_stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> Iterator[str]:
        """流式对话调用（委托给底层提供者）。

        Args:
            messages: 消息历史列表。
            system_prompt: 可选的系统提示。
            temperature: 生成温度。
            max_tokens: 最大生成 token 数。
            **kwargs: 额外的提供者特定参数。

        Yields:
            str: 流式响应的文本片段。
        """
        return self.provider.chat_stream(messages, system_prompt, temperature, max_tokens, **kwargs)
