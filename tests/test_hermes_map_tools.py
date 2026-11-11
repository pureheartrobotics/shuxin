from __future__ import annotations

import json

from shuxin.core.config import MapConfig
from shuxin.integrations.hermes.companion_hooks import bind_voice_agent, reset_voice_agent
from shuxin.integrations.hermes.map_tools import (
    _parse_weather_display,
    prefetch_map_facts,
    register_map_tools,
)
from shuxin.integrations.hermes.robot_tools import RobotSessionBridge, bind_robot_session, reset_robot_session
from shuxin.integrations.location.provider import LocationContext


class _Provider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def is_available(self) -> bool:
        return True

    def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, arguments))
        if name == "map_weather":
            return json.dumps({"city": "杭州", "now": {"temp": 18, "text": "多云"}})
        if name == "map_search_places":
            return json.dumps({"places": [{"name": "市儿童医院"}]})
        return "{}"


class _Agent:
    def __init__(self, provider: _Provider) -> None:
        self._provider = provider
        self.config = type("Cfg", (), {"map": MapConfig(enabled=True, api_key="ak")})()
        self.context = type(
            "Ctx",
            (),
            {
                "metadata": {
                    "location_ctx": LocationContext(
                        label="杭州市",
                        city="杭州市",
                        city_adcode="330100",
                        lat=30.25,
                        lng=120.15,
                        source="profile",
                        confidence="high",
                    ).to_metadata_dict()
                }
            },
        )()


def test_parse_weather_display_now_block() -> None:
    region, temperature, summary = _parse_weather_display(
        json.dumps({"city": "杭州", "now": {"temp": "18℃", "text": "多云"}}),
        {},
    )
    assert region == "杭州"
    assert temperature == 18
    assert summary == "多云"


def test_prefetch_weather_and_show_on_face(monkeypatch) -> None:
    from shuxin.integrations.hermes import map_tools as mt

    provider = _Provider()
    agent = _Agent(provider)
    monkeypatch.setattr(mt, "get_location_provider", lambda _cfg: provider)
    mcp: list[tuple[str, dict]] = []
    bridge = RobotSessionBridge(
        call_mcp=lambda name, args: mcp.append((name, args)) or "ok",
        wait_vision=lambda _t: None,
        caption=lambda *_a: "",
        has_tool=lambda name: name == "self.display.weather",
    )
    token = bind_voice_agent(agent)
    robot = bind_robot_session(bridge)
    try:
        block = prefetch_map_facts("明天带伞吗")
        assert "18" in block
        assert "map_weather" in block or "temp" in block
        assert provider.calls and provider.calls[0][0] == "map_weather"
        assert mcp and mcp[0][0] == "self.display.weather"
        assert mcp[0][1]["temperature"] == 18
    finally:
        reset_robot_session(robot)
        reset_voice_agent(token)


def test_prefetch_nearby_pediatrics(monkeypatch) -> None:
    from shuxin.integrations.hermes import map_tools as mt

    provider = _Provider()
    agent = _Agent(provider)
    monkeypatch.setattr(mt, "get_location_provider", lambda _cfg: provider)
    token = bind_voice_agent(agent)
    try:
        block = prefetch_map_facts("附近有没有儿科")
        assert "places" in block
        assert provider.calls[0][0] == "map_search_places"
        assert provider.calls[0][1]["query"] == "儿科"
    finally:
        reset_voice_agent(token)


def test_register_map_tools_skips_when_disabled() -> None:
    register_map_tools(type("Cfg", (), {"map": MapConfig(enabled=False)})())
