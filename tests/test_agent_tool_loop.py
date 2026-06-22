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
            },
            {
                "type": "function",
                "function": {
                    "name": "map_directions",
                    "description": "directions",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict) -> str:
        self.tool_calls.append((name, arguments))
        if name == "map_search_places":
            return json.dumps(
                {"status": 0, "results": [{"name": "测试餐厅", "area": "测试区"}]},
                ensure_ascii=False,
            )
        if name == "map_directions":
            return json.dumps(
                {"status": 0, "result": {"distance": "25km", "duration": "40分钟"}},
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
    user_input = "从天安门到首都机场怎么走"
    agent.memory.add_message("user", user_input)

    tool_response = LLMResponse(
        content="",
        tool_calls=[
            LLMToolCall(
                id="call_1",
                name="map_directions",
                arguments='{"origin":"天安门","destination":"首都机场"}',
            )
        ],
        finish_reason="tool_calls",
    )
    final_response = LLMResponse(content="大概四十分钟，走机场高速。")

    agent.llm = MagicMock()
    agent.llm.chat.side_effect = [tool_response, final_response]

    reply = agent._generate_llm_reply(agent._build_llm_messages(), user_input=user_input)

    assert reply == "大概四十分钟，走机场高速。"
    assert agent.llm.chat.call_count == 2
    provider_calls = agent.llm.chat.call_args_list[0].kwargs
    assert provider_calls.get("tools")


def test_agent_weather_fast_path_skips_sync_tool_llm():
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
    user_input = "现在天气怎么样？"
    agent.memory.add_message("user", user_input)

    final_response = LLMResponse(content="北京今天晴，记得防晒。")
    agent.llm = MagicMock()
    agent.llm.chat.return_value = final_response

    reply = agent._generate_llm_reply(agent._build_llm_messages(), user_input=user_input)

    assert reply == "北京今天晴，记得防晒。"
    assert agent.llm.chat.call_count == 1
    assert "tools" not in agent.llm.chat.call_args.kwargs
    weather_calls = [c for c in agent._location_provider.tool_calls if c[0] == "map_weather"]
    assert weather_calls
    assert weather_calls[0][1].get("district_id") == "110100"
    assert int(agent.context.metadata.get("map_tool_ms") or 0) >= 0


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

    final_response = LLMResponse(content="北京今天晴，适合出门。")

    agent.llm = MagicMock()
    agent.llm.chat.return_value = final_response

    reply = agent._generate_llm_reply(
        agent._build_llm_messages(), user_input="现在天气怎么样？"
    )

    assert reply == "北京今天晴，适合出门。"
    assert agent.llm.chat.call_count == 1
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
    assert len(agent._location_provider.tool_calls) >= 1
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

    final_response = LLMResponse(content="附近有几家本帮菜不错。")

    agent.llm = MagicMock()
    agent.llm.chat.return_value = final_response

    reply = agent._generate_llm_reply(
        agent._build_llm_messages(),
        user_input="我们这个地方有什么好吃的吗？",
    )

    assert reply == "附近有几家本帮菜不错。"
    assert agent.llm.chat.call_count == 1
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
    user_input = "从天安门到西湖怎么走"
    agent.memory.add_message("user", user_input)

    dsml_content = (
        "我查一下路线—— "
        '<｜｜DSML｜｜tool_calls> <｜｜DSML｜｜invoke name="map_directions"> '
        '<｜｜DSML｜｜parameter name="origin" string="true">天安门</｜｜DSML｜｜parameter> '
        "</｜｜DSML｜｜invoke> </｜｜DSML｜｜tool_calls>"
    )
    dsml_response = LLMResponse(content=dsml_content, finish_reason="stop")
    final_response = LLMResponse(content="建议地铁换乘，约一小时。")

    agent.llm = MagicMock()
    agent.llm.chat.side_effect = [dsml_response, final_response]

    reply = agent._generate_llm_reply(
        agent._build_llm_messages(), user_input=user_input
    )

    assert reply == "建议地铁换乘，约一小时。"
    route_calls = [c for c in agent._location_provider.tool_calls if c[0] == "map_directions"]
    assert route_calls
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
    assert agent._location_provider.tool_calls == []
