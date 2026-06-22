import json
from typing import List, Optional

from shuxin.core.config import MapConfig
from shuxin.integrations.location.baidu_mcp import BaiduMcpLocationProvider


class _FakeResponse:
    def __init__(self, payload: dict, headers: Optional[dict] = None) -> None:
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, responses: List[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url: str, json: dict, headers: Optional[dict] = None):
        self.calls.append({"url": url, "json": json, "headers": headers or {}})
        payload = self.responses.pop(0)
        return _FakeResponse(payload)


def test_list_openai_tools_uses_whitelist_without_network():
    cfg = MapConfig(api_key="test-ak", enabled=True)
    provider = BaiduMcpLocationProvider(cfg)
    provider._initialized = True
    provider._tools_cache = {}

    tools = provider.list_openai_tools(channel="voice")
    names = {item["function"]["name"] for item in tools}

    assert "map_weather" in names
    assert "map_ip_location" not in names


def test_call_tool_invokes_mcp_tools_call():
    cfg = MapConfig(api_key="test-ak", enabled=True)
    provider = BaiduMcpLocationProvider(cfg)
    provider._client = _FakeClient(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "晴"}]}},
        ]
    )
    provider._initialized = True

    result = provider.call_tool("map_weather", {"region": "北京"})
    assert "晴" in result
    assert provider._client.calls[-1]["json"]["method"] == "tools/call"


def test_is_available_requires_api_key():
    assert not BaiduMcpLocationProvider(MapConfig(api_key="")).is_available()
    assert BaiduMcpLocationProvider(MapConfig(api_key="ak", enabled=True)).is_available()
    assert not BaiduMcpLocationProvider(MapConfig(api_key="ak", enabled=False)).is_available()
