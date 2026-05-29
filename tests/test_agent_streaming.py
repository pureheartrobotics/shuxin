from __future__ import annotations

from types import SimpleNamespace

from shuxin.core.agent import Agent


class FakePlugins:
    def __init__(self, blocked: str | None = None) -> None:
        self.blocked = blocked
        self.hooks: list[str] = []

    def invoke_hook(self, hook_name: str, **kwargs):
        self.hooks.append(hook_name)
        if hook_name == "transform_output" and self.blocked is not None:
            return [("fake", self.blocked)]
        if hook_name == "transform_output":
            return [("fake", kwargs.get("content"))]
        return []


class FakeMemory:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def add_message(self, role: str, content: str) -> None:
        self.messages.append((role, content))

    def build_context(self, **kwargs):
        return [{"role": role, "content": content} for role, content in self.messages]


class FakeLLM:
    def __init__(self, *, fail: bool = False) -> None:
        self.called = False
        self.fail = fail

    def chat_stream(self, **kwargs):
        self.called = True
        if self.fail:
            raise TimeoutError("Request timed out.")
        return iter(["你", "好"])


def make_agent(*, blocked: str | None = None) -> tuple[Agent, FakeLLM, FakeMemory]:
    agent = Agent.__new__(Agent)
    agent.context = SimpleNamespace(turn_count=0, metadata={})
    agent.plugins = FakePlugins(blocked=blocked)
    agent.memory = FakeMemory()
    agent.llm = FakeLLM()
    agent.config = SimpleNamespace(
        max_history=10,
        llm=SimpleNamespace(temperature=0.7, max_tokens=128),
    )
    agent._system_prompt = "system"
    agent._build_system_prompt = lambda: None
    return agent, agent.llm, agent.memory


def make_failing_agent() -> tuple[Agent, FakeLLM, FakeMemory]:
    agent, _llm, memory = make_agent()
    agent.llm = FakeLLM(fail=True)
    return agent, agent.llm, memory


def test_agent_chat_stream_iterates_provider_chunks() -> None:
    agent, llm, memory = make_agent()

    chunks = list(agent.chat_stream("你好"))

    assert chunks == ["你", "好"]
    assert llm.called
    assert memory.messages[-1] == ("assistant", "你好")


def test_agent_chat_stream_skips_llm_when_output_is_blocked() -> None:
    agent, llm, memory = make_agent(blocked="（舒心沉默着）")

    chunks = list(agent.chat_stream("你好"))

    assert chunks == ["（舒心沉默着）"]
    assert not llm.called
    assert memory.messages[-1] == ("assistant", "（舒心沉默着）")


def test_agent_chat_stream_timeout_uses_technical_fallback() -> None:
    agent, llm, _memory = make_failing_agent()

    chunks = list(agent.chat_stream("你好"))

    assert llm.called
    assert chunks == [agent._get_fallback_response()]
    assert "模型连接" in chunks[0]
    assert "不舒服" not in chunks[0]
