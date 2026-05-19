"""舒心 LLM 提供者抽象层

对标 Hermes 的 provider 系统，支持多模型后端切换。

架构：
- BaseLLMProvider: 抽象基类，定义统一接口
- OpenAIProvider: OpenAI 兼容 API 实现
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
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "")
        self.model = model

        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
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
                    client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
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
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error("LLM 流式调用失败 [model=%s]: %s", self.model, e)
            raise


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
            provider_type: 提供者类型，目前支持 "openai"。
            **kwargs: 提供者特定的初始化参数
                      (api_key, base_url, model 等)。

        Raises:
            ValueError: 不支持的提供者类型时抛出。

        Example:
            >>> provider = LLMProvider()
            >>> provider.initialize("openai", model="gpt-4o")
        """
        with self._lock:
            if provider_type == "openai":
                self._provider = OpenAIProvider(
                    api_key=kwargs.get("api_key"),
                    base_url=kwargs.get("base_url"),
                    model=kwargs.get("model", "gpt-4o"),
                )
            else:
                raise ValueError(f"不支持的 LLM 提供者: {provider_type}")

            logger.info("LLM 提供者已初始化: %s [model=%s]", provider_type, kwargs.get("model", "gpt-4o"))

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
