"""百度地图 MCP Streamable HTTP 客户端。"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional

import httpx

from shuxin.core.config import MapConfig
from shuxin.integrations.location.provider import (
    CLI_TOOL_WHITELIST,
    INTERNAL_TOOLS,
    LocationContext,
    LocationToolProvider,
    VOICE_TOOL_WHITELIST,
)

logger = logging.getLogger("shuxin.integrations.location.baidu_mcp")

MCP_PROTOCOL_VERSION = "2024-11-05"

# tools/list 失败时的最小 fallback schema（与百度 MCP 工具名对齐）
_FALLBACK_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "map_geocode": {
        "description": "将地址转换为地理坐标",
        "inputSchema": {
            "type": "object",
            "properties": {"address": {"type": "string", "description": "地址"}},
            "required": ["address"],
        },
    },
    "map_reverse_geocode": {
        "description": "将坐标转换为地址信息",
        "inputSchema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
            },
            "required": ["latitude", "longitude"],
        },
    },
    "map_search_places": {
        "description": "按关键词搜索地点",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "region": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    "map_place_details": {
        "description": "获取 POI 详情",
        "inputSchema": {
            "type": "object",
            "properties": {"uid": {"type": "string"}},
            "required": ["uid"],
        },
    },
    "map_directions": {
        "description": "两点路线规划",
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "mode": {"type": "string"},
            },
            "required": ["origin", "destination"],
        },
    },
    "map_directions_matrix": {
        "description": "批量路线规划",
        "inputSchema": {
            "type": "object",
            "properties": {
                "origins": {"type": "array"},
                "destinations": {"type": "array"},
            },
            "required": ["origins", "destinations"],
        },
    },
    "map_weather": {
        "description": "查询天气",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {"type": "string"},
                "location": {"type": "string"},
            },
        },
    },
    "map_ip_location": {
        "description": "根据 IP 定位城市",
        "inputSchema": {
            "type": "object",
            "properties": {"ip": {"type": "string"}},
            "required": ["ip"],
        },
    },
    "map_road_traffic": {
        "description": "查询路况",
        "inputSchema": {
            "type": "object",
            "properties": {"road_name": {"type": "string"}},
            "required": ["road_name"],
        },
    },
}


def _mcp_tool_to_openai(name: str, tool_def: Dict[str, Any]) -> Dict[str, Any]:
    schema = tool_def.get("inputSchema") or tool_def.get("parameters") or {
        "type": "object",
        "properties": {},
    }
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": tool_def.get("description", name),
            "parameters": schema,
        },
    }


def _extract_result_text(result: Any) -> str:
    if result is None:
        return "{}"
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        if "content" in result:
            content = result["content"]
            if isinstance(content, list):
                parts: List[str] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                    else:
                        parts.append(json.dumps(item, ensure_ascii=False))
                return "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


class BaiduMcpLocationProvider:
    """通过百度托管 MCP（Streamable HTTP）提供地图 tools。"""

    def __init__(self, map_config: MapConfig) -> None:
        self._config = map_config
        self._lock = threading.Lock()
        self._client: Optional[httpx.Client] = None
        self._session_id: Optional[str] = None
        self._request_id = 0
        self._tools_cache: Dict[str, Dict[str, Any]] = {}
        self._initialized = False

    def is_available(self) -> bool:
        return bool(
            self._config.enabled
            and self._config.api_key.strip()
        )

    def _endpoint_url(self) -> str:
        base = self._config.mcp_url.rstrip("/")
        ak = self._config.api_key.strip()
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}ak={ak}"

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(
                    connect=min(3.0, self._config.timeout_seconds),
                    read=self._config.timeout_seconds,
                    write=10.0,
                    pool=2.0,
                ),
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _parse_response_body(self, response: httpx.Response) -> Any:
        session_header = response.headers.get("mcp-session-id") or response.headers.get(
            "Mcp-Session-Id"
        )
        if session_header:
            self._session_id = session_header

        content_type = (response.headers.get("content-type") or "").lower()
        text = response.text.strip()
        if not text:
            return None

        if "text/event-stream" in content_type:
            for line in text.splitlines():
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload and payload != "[DONE]":
                        try:
                            message = json.loads(payload)
                            if "result" in message:
                                return message["result"]
                            if "error" in message:
                                raise RuntimeError(message["error"])
                        except json.JSONDecodeError:
                            continue
            return None

        message = json.loads(text)
        if isinstance(message, dict):
            if "error" in message and message["error"]:
                raise RuntimeError(message["error"])
            return message.get("result")
        return message

    def _send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        client = self._get_client()
        headers: Dict[str, str] = {}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }
        response = client.post(self._endpoint_url(), json=payload, headers=headers)
        response.raise_for_status()
        return self._parse_response_body(response)

    def _ensure_session(self) -> None:
        if self._initialized or not self.is_available():
            return
        with self._lock:
            if self._initialized:
                return
            try:
                self._send(
                    "initialize",
                    {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "shuxin", "version": "0.1.0"},
                    },
                )
                try:
                    self._send("notifications/initialized", {})
                except Exception:
                    pass
                result = self._send("tools/list", {})
                tools = []
                if isinstance(result, dict):
                    tools = result.get("tools") or []
                for tool in tools:
                    if isinstance(tool, dict) and tool.get("name"):
                        self._tools_cache[str(tool["name"])] = tool
                if not self._tools_cache:
                    self._tools_cache = dict(_FALLBACK_TOOL_SCHEMAS)
                    for name, schema in self._tools_cache.items():
                        if "name" not in schema:
                            schema = {**schema, "name": name}
                            self._tools_cache[name] = schema
                self._initialized = True
                logger.info("百度 MCP 已初始化，缓存 %d 个 tools", len(self._tools_cache))
            except Exception as exc:
                logger.warning("百度 MCP 初始化失败，使用 fallback schemas: %s", exc)
                self._tools_cache = {
                    name: {"name": name, **_FALLBACK_TOOL_SCHEMAS[name]}
                    for name in _FALLBACK_TOOL_SCHEMAS
                }
                self._initialized = True

    def _whitelist_for_channel(self, channel: str) -> frozenset[str]:
        if channel == "voice":
            return VOICE_TOOL_WHITELIST
        return CLI_TOOL_WHITELIST

    def list_openai_tools(self, *, channel: str = "voice") -> List[Dict[str, Any]]:
        if not self.is_available():
            return []
        self._ensure_session()
        whitelist = self._whitelist_for_channel(channel)
        tools: List[Dict[str, Any]] = []
        for name in sorted(whitelist):
            tool_def = self._tools_cache.get(name) or _FALLBACK_TOOL_SCHEMAS.get(name)
            if tool_def:
                tools.append(_mcp_tool_to_openai(name, tool_def))
        return tools

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        if not self.is_available():
            raise RuntimeError("百度地图 MCP 未配置")
        if name in INTERNAL_TOOLS or name in VOICE_TOOL_WHITELIST or name in CLI_TOOL_WHITELIST:
            pass
        else:
            raise ValueError(f"不允许调用的地图工具: {name}")

        self._ensure_session()
        try:
            result = self._send(
                "tools/call",
                {"name": name, "arguments": arguments or {}},
            )
            return _extract_result_text(result)
        except Exception as exc:
            logger.warning("地图工具调用失败 [%s]: %s", name, exc)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    def resolve_location_context(
        self,
        *,
        ip: Optional[str] = None,
        user_home: Optional[Any] = None,
    ) -> LocationContext:
        from pathlib import Path

        from shuxin.integrations.location.context import resolve_location_context

        home = Path(user_home) if user_home else None
        return resolve_location_context(
            self,
            ip=ip,
            user_home=home,
            default_region=self._config.default_region,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


_provider_lock = threading.Lock()
_provider_instance: Optional[BaiduMcpLocationProvider] = None
_provider_config_key: Optional[str] = None


def get_location_provider(map_config: Optional[MapConfig] = None) -> LocationToolProvider:
    """获取进程级地图 provider 单例。"""
    global _provider_instance, _provider_config_key

    if map_config is None:
        from shuxin.core.config import Config

        map_config = Config.load().map

    config_key = (
        f"{map_config.enabled}|{map_config.api_key}|{map_config.mcp_url}|"
        f"{map_config.timeout_seconds}"
    )

    with _provider_lock:
        if _provider_instance is None or _provider_config_key != config_key:
            if _provider_instance is not None:
                _provider_instance.close()
            _provider_instance = BaiduMcpLocationProvider(map_config)
            _provider_config_key = config_key
        return _provider_instance
