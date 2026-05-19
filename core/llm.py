"""舒心 LLM 提供者抽象层

对标 Hermes 的 provider 系统，支持多模型后端切换。
"""

from __future__ import annotations

import os
import json
import logging
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, AsyncIterator
from dataclasses import dataclass, field

logger = logging.getLogger("shuxin.llm")


@dataclass
class LLMMessage:
    """LLM 消息"""
    role: str  # system, user, assistant
    content: str


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: str = ""


class BaseLLMProvider(ABC):
    """LLM 提供者基类"""

    @abstractmethod
    def chat(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
        """同步对话"""
        ...

    @abstractmethod
    async def chat_async(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
        """异步对话"""
        ...

    @abstractmethod
    def chat_stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> AsyncIterator[str]:
        """流式对话"""
        ...


class OpenAIProvider(BaseLLMProvider):
    """OpenAI 兼容 API 提供者"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o",
    ):
        from openai import OpenAI

        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "")
        self.model = model

        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self.client = OpenAI(**client_kwargs)
        self._async_client = None

    @property
    def async_client(self):
        if self._async_client is None:
            from openai import AsyncOpenAI
            client_kwargs = {"api_key": self.api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self._async_client = AsyncOpenAI(**client_kwargs)
        return self._async_client

    def _to_openai_messages(self, messages: List[LLMMessage], system_prompt: Optional[str] = None):
        """转换为 OpenAI 消息格式"""
        result = []
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
        **kwargs,
    ) -> LLMResponse:
        openai_messages = self._to_openai_messages(messages, system_prompt)
        try:
            response = self.client.chat.completions.create(
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
            logger.error(f"LLM 调用失败: {e}")
            raise

    async def chat_async(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
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
            logger.error(f"LLM 异步调用失败: {e}")
            raise

    def chat_stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ):
        openai_messages = self._to_openai_messages(messages, system_prompt)

        def _stream():
            try:
                stream = self.client.chat.completions.create(
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
                logger.error(f"LLM 流式调用失败: {e}")
                raise

        return _stream()


class LLMProvider:
    """LLM 提供者门面 — 统一接口"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._provider: Optional[BaseLLMProvider] = None

    def initialize(self, provider_type: str = "openai", **kwargs) -> None:
        """初始化 LLM 提供者"""
        if provider_type == "openai":
            self._provider = OpenAIProvider(
                api_key=kwargs.get("api_key"),
                base_url=kwargs.get("base_url"),
                model=kwargs.get("model", "gpt-4o"),
            )
        else:
            raise ValueError(f"不支持的 LLM 提供者: {provider_type}")

        logger.info(f"LLM 提供者已初始化: {provider_type}")

    @property
    def provider(self) -> BaseLLMProvider:
        if self._provider is None:
            raise RuntimeError("LLM 提供者未初始化，请先调用 initialize()")
        return self._provider

    def chat(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
        return self.provider.chat(messages, system_prompt, temperature, max_tokens, **kwargs)

    async def chat_async(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
        return await self.provider.chat_async(messages, system_prompt, temperature, max_tokens, **kwargs)

    def chat_stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ):
        return self.provider.chat_stream(messages, system_prompt, temperature, max_tokens, **kwargs)
