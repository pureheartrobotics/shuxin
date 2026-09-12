from __future__ import annotations

from types import SimpleNamespace

from shuxin.core.llm import (
    LLMMessage,
    OpenAIProvider,
    _normalize_openai_base_url,
    _openai_stream_delta_text,
)


def test_normalize_openai_base_url_appends_v1() -> None:
    assert _normalize_openai_base_url("https://www.dmxapi.cn") == "https://www.dmxapi.cn/v1"
    assert _normalize_openai_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    assert _normalize_openai_base_url("") == ""


def test_openai_stream_delta_text_prefers_content() -> None:
    delta = SimpleNamespace(content="答案", reasoning_content="思考")
    assert _openai_stream_delta_text(delta) == "答案"


def test_openai_stream_delta_text_falls_back_to_reasoning() -> None:
    delta = SimpleNamespace(content=None, reasoning_content="推理片段")
    assert _openai_stream_delta_text(delta) == ""


def test_chat_stream_yields_reasoning_when_content_missing(monkeypatch) -> None:
    chunks = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, reasoning_content="好"),
                )
            ]
        ),
    ]

    class FakeCompletions:
        def create(self, **kwargs):
            return chunks

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(OpenAI=lambda **kwargs: FakeClient(), AsyncOpenAI=lambda **kwargs: object()),
    )

    provider = OpenAIProvider(api_key="test-key", model="test-model")
    out = list(
        provider.chat_stream(
            [LLMMessage(role="user", content="hi")],
            system_prompt="sys",
        )
    )
    assert out == []


def test_chat_stream_yields_content_as_before(monkeypatch) -> None:
    chunks = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="可见", reasoning_content=None),
                )
            ]
        ),
    ]

    class FakeCompletions:
        def create(self, **kwargs):
            return chunks

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(OpenAI=lambda **kwargs: FakeClient(), AsyncOpenAI=lambda **kwargs: object()),
    )

    provider = OpenAIProvider(api_key="test-key", model="test-model")
    out = list(
        provider.chat_stream(
            [LLMMessage(role="user", content="hi")],
        )
    )
    assert out == ["可见"]
