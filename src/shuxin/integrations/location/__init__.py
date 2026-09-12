"""地图能力集成 — 百度 MCP 首版实现。"""

from shuxin.integrations.location.context import (
    format_location_context_block,
    resolve_location_context,
)
from shuxin.integrations.location.gate import may_need_location, should_attach_location_tools
from shuxin.integrations.location.provider import (
    CLI_TOOL_WHITELIST,
    LocationContext,
    LocationToolProvider,
    VOICE_TOOL_WHITELIST,
)

__all__ = [
    "BaiduMcpLocationProvider",
    "CLI_TOOL_WHITELIST",
    "LocationContext",
    "LocationToolProvider",
    "VOICE_TOOL_WHITELIST",
    "format_location_context_block",
    "get_location_provider",
    "may_need_location",
    "resolve_location_context",
    "should_attach_location_tools",
]


def __getattr__(name: str):
    if name == "get_location_provider":
        from shuxin.integrations.location.baidu_mcp import get_location_provider

        return get_location_provider
    if name == "BaiduMcpLocationProvider":
        from shuxin.integrations.location.baidu_mcp import BaiduMcpLocationProvider

        return BaiduMcpLocationProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
