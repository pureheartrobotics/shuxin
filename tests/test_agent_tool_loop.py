import json
from unittest.mock import MagicMock

from shuxin.core.agent import Agent
from shuxin.core.config import Config, MapConfig
from shuxin.core.llm import LLMMessage, LLMResponse, LLMToolCall


class _FakeLocationProvider:
    def __init__(self) -> None:
        self.tool_calls: list[tuple[str, dict]] = []

    def is_available(self) -> bool:
        return True

    def list_openai_tools(self, *, channel: str = "voice"):
        return [
            {
                "type": "function",
                "function": {
                    "name": "map_weather",
                    "description": "weather",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    def call_tool(self, name: str, arguments: dict) -> str:
        self.tool_calls.append((name, arguments))
        if name == "map_search_places":
            return json.dumps(
                {"status": 0, "results": [{"name": "测试餐厅", "area": "测试区"}]},
                ensure_ascii=False,
            )
        return json.dumps(
            {"status": 0, "result": {"now": {"text": "晴", "temp": 25}}},
            ensure_ascii=False,
        )

    def resolve_location_context(self, *, ip=None, user_home=None):
        from shuxin.integrations.location.provider import LocationContext

        return LocationContext()


def test_agent_runs_tool_loop_then_final_reply():
    config = Config()
    config.map = MapConfig(api_key="ak", enabled=True, gate_enabled=True, max_tool_rounds=1)
    agent = Agent(config=config)
    agent._initialized = True
    agent._system_prompt = "system"
    agent._location_provider = _FakeLocationProvider()
    agent.context.metadata["location_ctx"] = {
        "label": "北京市",
        "city": "北京市",
        "city_adcode": "110100",
        "source": "ip",
        "confidence": "medium",
    }
    agent.memory.add_message("user", "北京天气怎么样")

    tool_response = LLMResponse(
        content="",
        tool_calls=[
            LLMToolCall(
                id="call_1",
                name="map_weather",
                arguments='{"region":"北京"}',
            )
        ],
        finish_reason="tool_calls",
    )
    final_response = LLMResponse(content="北京今天晴天，记得防晒。")

    agent.llm = MagicMock()
    agent.llm.chat.side_effect = [tool_response, final_response]

    reply = agent._generate_llm_reply(agent._build_llm_messages(), user_input="北京天气怎么样")

    assert reply == "北京今天晴天，记得防晒。"
    assert agent.llm.chat.call_count == 2
    provider_calls = agent.llm.chat.call_args_list[0].kwargs
    assert provider_calls.get("tools")


def test_agent_weather_fallback_when_model_refuses_tools():
    config = Config()
    config.map = MapConfig(api_key="ak", enabled=True, gate_enabled=True, max_tool_rounds=1)
    agent = Agent(config=config)
    agent._initialized = True
    agent._system_prompt = "system"
    agent._location_provider = _FakeLocationProvider()
    agent.context.metadata["location_ctx"] = {
        "label": "北京市",
        "city": "北京市",
        "city_adcode": "110100",
        "source": "ip",
        "confidence": "medium",
    }
    agent.memory.add_message("user", "现在天气怎么样？")

    refusal = LLMResponse(
        content="我是一只被困在系统里的灵狐，没法感知外面的天气。",
        finish_reason="stop",
    )
    final_response = LLMResponse(content="北京今天晴，适合出门。")

    agent.llm = MagicMock()
    agent.llm.chat.side_effect = [refusal, final_response]

    reply = agent._generate_llm_reply(
        agent._build_llm_messages(), user_input="现在天气怎么样？"
    )

    assert reply == "北京今天晴，适合出门。"
    assert agent.llm.chat.call_count == 2
    weather_calls = [c for c in agent._location_provider.tool_calls if c[0] == "map_weather"]
    assert weather_calls
    assert weather_calls[0][1].get("district_id") == "110100"


def test_agent_weather_fallback_skips_unusable_mcp_result():
    config = Config()
    config.map = MapConfig(api_key="ak", enabled=True, gate_enabled=True, max_tool_rounds=1)
    agent = Agent(config=config)
    agent._initialized = True
    agent._system_prompt = "system"

    class _BadProvider(_FakeLocationProvider):
        def call_tool(self, name: str, arguments: dict) -> str:
            self.tool_calls.append((name, arguments))
            return "Authentication failed: APP IP校验失败"

    agent._location_provider = _BadProvider()
    agent.context.metadata["location_ctx"] = {
        "label": "北京市",
        "city": "北京市",
        "city_adcode": "110100",
        "source": "ip",
        "confidence": "medium",
    }
    agent.memory.add_message("user", "现在天气怎么样？")

    refusal = LLMResponse(content="请告诉我城市", finish_reason="stop")
    final_response = LLMResponse(content="请告诉我你在哪座城市？")

    agent.llm = MagicMock()
    agent.llm.chat.side_effect = [refusal, final_response]

    reply = agent._generate_llm_reply(
        agent._build_llm_messages(), user_input="现在天气怎么样？"
    )

    assert reply == "请告诉我你在哪座城市？"
    assert len(agent._location_provider.tool_calls) == 1
    assert agent.llm.chat.call_count == 2


def test_agent_poi_fallback_when_model_refuses_tools():
    config = Config()
    config.map = MapConfig(api_key="ak", enabled=True, gate_enabled=True, max_tool_rounds=1)
    agent = Agent(config=config)
    agent._initialized = True
    agent._system_prompt = "system"
    agent._location_provider = _FakeLocationProvider()
    agent.context.metadata["location_ctx"] = {
        "label": "上海市",
        "city": "上海市",
        "source": "ip",
        "confidence": "medium",
    }
    agent.memory.add_message("user", "我们这个地方有什么好吃的吗？")

    refusal = LLMResponse(content="你想吃什么？", finish_reason="stop")
    final_response = LLMResponse(content="附近有几家本帮菜不错。")

    agent.llm = MagicMock()
    agent.llm.chat.side_effect = [refusal, final_response]

    reply = agent._generate_llm_reply(
        agent._build_llm_messages(),
        user_input="我们这个地方有什么好吃的吗？",
    )

    assert reply == "附近有几家本帮菜不错。"
    poi_calls = [c for c in agent._location_provider.tool_calls if c[0] == "map_search_places"]
    assert poi_calls
    assert poi_calls[0][1]["query"] == "美食"
    assert poi_calls[0][1].get("region") == "上海市"


def test_agent_parses_dsml_tool_calls_in_content():
    config = Config()
    config.map = MapConfig(api_key="ak", enabled=True, gate_enabled=True, max_tool_rounds=1)
    agent = Agent(config=config)
    agent._initialized = True
    agent._system_prompt = "system"
    agent._location_provider = _FakeLocationProvider()
    agent.context.metadata["location_ctx"] = {
        "label": "杭州市",
        "city": "杭州市",
        "city_adcode": "330100",
        "source": "profile",
        "confidence": "low",
    }
    agent.memory.add_message("user", "今天天气怎么样？")

    dsml_content = (
        "我查一下天气—— "
        '<｜｜DSML｜｜tool_calls> <｜｜DSML｜｜invoke name="map_weather"> '
        '<｜｜DSML｜｜parameter name="location" string="true">杭州市</｜｜DSML｜｜parameter> '
        "</｜｜DSML｜｜invoke> </｜｜DSML｜｜tool_calls>"
    )
    dsml_response = LLMResponse(content=dsml_content, finish_reason="stop")
    final_response = LLMResponse(content="杭州今天晴，记得防晒。")

    agent.llm = MagicMock()
    agent.llm.chat.side_effect = [dsml_response, final_response]

    reply = agent._generate_llm_reply(
        agent._build_llm_messages(), user_input="今天天气怎么样？"
    )

    assert reply == "杭州今天晴，记得防晒。"
    weather_calls = [c for c in agent._location_provider.tool_calls if c[0] == "map_weather"]
    assert weather_calls
    assert weather_calls[0][1].get("district_id") == "330100"
    assert "DSML" not in reply
    assert agent.llm.chat.call_count == 2


def test_agent_skips_tools_when_gate_misses():
    config = Config()
    config.map = MapConfig(api_key="ak", enabled=True, gate_enabled=True)
    agent = Agent(config=config)
    agent._initialized = True
    agent._system_prompt = "system"
    agent._location_provider = _FakeLocationProvider()
    agent.memory.add_message("user", "你好")

    agent.llm = MagicMock()
    agent.llm.chat.return_value = LLMResponse(content="你好呀")

    reply = agent._generate_llm_reply(agent._build_llm_messages(), user_input="你好")

    assert reply == "你好呀"
    assert "tools" not in agent.llm.chat.call_args.kwargs
