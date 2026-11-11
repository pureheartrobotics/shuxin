"""把百度地图 MCP 注册成 Hermes toolset ``map``（语音天气/附近）。"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from shuxin.integrations.hermes.companion_hooks import current_voice_agent
from shuxin.integrations.hermes.robot_tools import current_robot_session
from shuxin.integrations.location import get_location_provider
from shuxin.integrations.location.fallback import (
    infer_poi_query,
    infer_weather_region,
    is_tool_result_usable,
    should_direct_poi_search,
    should_direct_weather_call,
)
from shuxin.integrations.location.provider import LocationContext
from shuxin.integrations.location.tool_args import (
    normalize_map_search_places_args,
    normalize_map_weather_args,
)

logger = logging.getLogger("shuxin.hermes.map")

_REGISTERED = False

_TOOL_META: tuple[tuple[str, str, dict[str, Any]], ...] = (
    (
        "map_weather",
        "查询天气。用户问天气、气温、下雨、带伞、冷不冷时调用。",
        {
            "type": "object",
            "properties": {
                "region": {"type": "string", "description": "城市名，可空则用当前位置"},
                "location": {"type": "string", "description": "经纬度或地名"},
            },
        },
    ),
    (
        "map_search_places",
        "搜附近地点。用户问附近有没有儿科、医院、药店、餐厅时调用。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词，如儿科、医院、美食"},
                "region": {"type": "string", "description": "城市，可空则用当前位置"},
            },
            "required": ["query"],
        },
    ),
    (
        "map_geocode",
        "把地址转成坐标。",
        {
            "type": "object",
            "properties": {"address": {"type": "string"}},
            "required": ["address"],
        },
    ),
    (
        "map_reverse_geocode",
        "把坐标转成地址。",
        {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
            },
            "required": ["latitude", "longitude"],
        },
    ),
    (
        "map_directions",
        "两点怎么走。用户问路、多远、导航时调用。",
        {
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "mode": {"type": "string"},
            },
            "required": ["origin", "destination"],
        },
    ),
)


def _location_ctx() -> Optional[LocationContext]:
    agent = current_voice_agent()
    if agent is None:
        return None
    raw = getattr(getattr(agent, "context", None), "metadata", {}) or {}
    ctx_raw = raw.get("location_ctx")
    if isinstance(ctx_raw, dict):
        return LocationContext.from_metadata_dict(ctx_raw)
    return None


def _provider():
    agent = current_voice_agent()
    if agent is None:
        return None
    config = getattr(agent, "config", None)
    if config is None:
        return None
    provider = get_location_provider(config.map)
    if not provider.is_available():
        return None
    return provider


def _unavailable() -> str:
    return "现在还查不了地图和天气，等服务打开后再问我。"


def _mark_map_ms(started: float) -> None:
    agent = current_voice_agent()
    if agent is None:
        return
    elapsed = int((time.perf_counter() - started) * 1000)
    metadata = getattr(getattr(agent, "context", None), "metadata", None)
    if isinstance(metadata, dict):
        metadata["map_tool_ms"] = int(metadata.get("map_tool_ms") or 0) + elapsed


def _call(name: str, args: dict[str, Any], *, user_input: str = "") -> str:
    started = time.perf_counter()
    provider = _provider()
    if provider is None:
        return _unavailable()
    ctx = _location_ctx()
    if name == "map_weather":
        normalized = normalize_map_weather_args(args, ctx)
        if not normalized:
            region = infer_weather_region(user_input, ctx) or str(args.get("region") or "")
            normalized = normalize_map_weather_args({"region": region} if region else {}, ctx)
        if not normalized:
            return "还不知道你在哪，说一下城市，比如北京天气。"
    elif name == "map_search_places":
        query = str(args.get("query") or infer_poi_query(user_input) or "美食")
        merged = dict(args)
        merged.setdefault("query", query)
        normalized = normalize_map_search_places_args(merged, ctx, default_query=query)
        if not normalized:
            return "还不知道你在哪，说一下城市再找附近。"
    else:
        normalized = args if isinstance(args, dict) else {}
    try:
        result = provider.call_tool(name, normalized)
    except Exception as exc:
        logger.warning("Hermes map tool failed [%s]: %s", name, exc)
        return "刚才没查到，稍后再试一次。"
    finally:
        _mark_map_ms(started)
    if not is_tool_result_usable(result or ""):
        return "刚才没查到，稍后再试一次。"
    if name == "map_weather":
        _show_weather_on_face(result, normalized)
    return result


def _show_weather_on_face(result: str, args: dict[str, Any]) -> None:
    session = current_robot_session()
    if session is None or not session.has_tool("self.display.weather"):
        return
    region, temperature, summary = _parse_weather_display(result, args)
    if temperature is None or not summary:
        return
    payload: dict[str, Any] = {"summary": summary, "temperature": temperature}
    if region:
        payload["region"] = region
    try:
        session.call_mcp("self.display.weather", payload)
    except Exception:
        logger.debug("display weather MCP failed", exc_info=True)


def _parse_weather_display(result: str, args: dict[str, Any]) -> tuple[str, Optional[int], str]:
    region = str(args.get("region") or "").strip()
    temperature: Optional[int] = None
    summary = ""
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return region, None, ""
    if not isinstance(data, dict):
        return region, None, ""
    now = data.get("now") if isinstance(data.get("now"), dict) else data
    result_obj = data.get("result") if isinstance(data.get("result"), dict) else {}
    if isinstance(result_obj.get("now"), dict):
        now = result_obj["now"]
    if not region:
        region = str(
            data.get("city")
            or data.get("district")
            or result_obj.get("city")
            or now.get("city")
            or ""
        ).strip()
    for key in ("temp", "temperature", "temperature_2m", "tmp"):
        raw = now.get(key) if isinstance(now, dict) else None
        if raw is None and isinstance(data, dict):
            raw = data.get(key)
        if raw is None:
            continue
        try:
            temperature = int(float(str(raw).replace("℃", "").replace("°", "")))
            break
        except (TypeError, ValueError):
            continue
    for key in ("text", "weather", "summary", "phenomenon", "cond_txt"):
        value = now.get(key) if isinstance(now, dict) else None
        if not value and isinstance(data, dict):
            value = data.get(key)
        if value:
            summary = str(value).strip()
            break
    return region, temperature, summary


def _handler(name: str):
    def _run(args: dict[str, Any], **_kw: Any) -> str:
        message = str(_kw.get("user_message") or _kw.get("message") or "")
        return _call(name, args or {}, user_input=message)

    return _run


def prefetch_map_facts(user_input: str) -> str:
    """天气/附近问句先查一次，写进系统提示，避免模型空口编。"""
    if _provider() is None:
        return ""
    chunks: list[str] = []
    if should_direct_weather_call(user_input):
        result = _call("map_weather", {}, user_input=user_input)
        if result and result != _unavailable():
            chunks.append("【已查天气，按这个说，不要编】\n" + result)
    elif should_direct_poi_search(user_input):
        query = infer_poi_query(user_input)
        result = _call("map_search_places", {"query": query}, user_input=user_input)
        if result and result != _unavailable():
            chunks.append("【已查附近，按这个说，不要编店名】\n" + result)
    return "\n\n".join(chunks)


def register_map_tools(config: Any = None) -> None:
    """地图已开通时向 Hermes 注册 map toolset（幂等）。"""
    global _REGISTERED
    if _REGISTERED:
        return
    map_config = getattr(config, "map", None)
    if map_config is None:
        return
    provider = get_location_provider(map_config)
    if not provider.is_available():
        logger.info("skip map tools, MapConfig disabled or no AK")
        return
    try:
        from tools.registry import registry
    except Exception as exc:
        logger.warning("skip map tools, Hermes registry unavailable: %s", exc)
        return

    for name, description, schema in _TOOL_META:
        registry.register(
            name=name,
            toolset="map",
            schema={
                "name": name,
                "description": description,
                "parameters": schema,
            },
            handler=_handler(name),
            description=description,
            emoji="📍",
            override=True,
        )
    _REGISTERED = True
    logger.info("Hermes map toolset registered")
