from __future__ import annotations

from types import SimpleNamespace

import httpx

from shuxin.core.llm import OpenAIProvider, _get_llm_connect_timeout_seconds


def test_openai_provider_uses_env_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["sync"] = kwargs

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["async"] = kwargs

    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(OpenAI=FakeOpenAI, AsyncOpenAI=FakeAsyncOpenAI),
    )
    monkeypatch.setenv("SHUXIN_LLM_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("SHUXIN_LLM_CONNECT_TIMEOUT_SECONDS", "4")

    provider = OpenAIProvider(api_key="test-key", model="test-model")
    _ = provider.async_client

    sync_timeout = captured["sync"]["timeout"]
    async_timeout = captured["async"]["timeout"]
    assert isinstance(sync_timeout, httpx.Timeout)
    assert sync_timeout.read == 10.0
    assert sync_timeout.connect == 4.0
    assert captured["sync"]["max_retries"] == 0
    assert isinstance(async_timeout, httpx.Timeout)
    assert async_timeout.read == 10.0
    assert async_timeout.connect == _get_llm_connect_timeout_seconds()
    assert captured["async"]["max_retries"] == 0
