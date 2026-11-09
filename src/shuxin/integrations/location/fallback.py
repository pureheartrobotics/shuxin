"""地图 tool 降级 — 模型未调用 tool 时服务端直调。"""

from __future__ import annotations

import json
import re
from typing import Optional, Union

from shuxin.integrations.location.provider import LocationContext

_WEATHER_KEYWORDS: tuple[str, ...] = (
    "天气",
    "气温",
    "下雨",
    "下雪",
    "冷不冷",
    "热不热",
    "weather",
)

_POI_KEYWORDS: tuple[str, ...] = (
    "好吃",
    "好吃的",
    "吃什么",
    "美食",
    "餐厅",
    "饭店",
    "小吃",
    "夜宵",
    "早饭",
    "早餐",
    "午饭",
    "晚餐",
)

_CITY_IN_QUERY = re.compile(
    r"([\u4e00-\u9fff]{2,8}?)(?:的)?(?:天气|气温|下雨|下雪)"
)
_LOCATION_CONTEXT_CITY = re.compile(r"(?:用户大致在|推测可能在)：([^（\n]+)")
_LOW_CONFIDENCE_CITY = re.compile(r"推测可能在：([^（\n]+)")


def is_tool_result_usable(result: str) -> bool:
    """MCP/工具返回是否可作为 LLM 依据。"""
    text = (result or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if "authentication failed" in lowered:
        return False
    if "ip校验失败" in lowered or "ip 校验失败" in lowered:
        return False
    if "api response error" in lowered:
        return False
    if "请求参数格式错误" in text:
        return False
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            if data.get("error"):
                return False
            status = data.get("status")
            if status is not None and str(status) not in ("0", "ok"):
                return False
    except json.JSONDecodeError:
        pass
    return True


def should_direct_weather_call(user_input: str) -> bool:
    """用户是否在问天气（适合服务端直调 map_weather）。"""
    text = (user_input or "").strip().lower()
    if not text:
        return False
    return any(keyword in text for keyword in _WEATHER_KEYWORDS)


def should_direct_poi_search(user_input: str) -> bool:
    """用户是否在问周边吃喝（适合服务端直调 map_search_places）。"""
    text = (user_input or "").strip().lower()
    if not text:
        return False
    if any(keyword in text for keyword in _POI_KEYWORDS):
        return True
    return any(token in text for token in ("这个地方", "这边", "这里", "附近", "周边"))


def infer_poi_query(user_input: str) -> str:
    """从用户句推断 POI 检索关键词。"""
    text = (user_input or "").strip()
    if any(token in text for token in ("好吃", "吃什么", "美食", "餐厅", "饭店", "小吃")):
        return "美食"
    if "早饭" in text or "早餐" in text:
        return "早餐"
    if "午饭" in text or "午餐" in text:
        return "午餐"
    if "晚餐" in text or "晚饭" in text:
        return "晚餐"
    if "夜宵" in text:
        return "夜宵"
    return "美食"


def _label_from_context(ctx: Union[LocationContext, str, None]) -> str:
    if isinstance(ctx, LocationContext):
        return (ctx.label or "").strip()
    if isinstance(ctx, str) and ctx.strip():
        for pattern in (_LOCATION_CONTEXT_CITY, _LOW_CONFIDENCE_CITY):
            match = pattern.search(ctx)
            if match:
                return match.group(1).strip()
    return ""


def infer_search_region(ctx: Union[LocationContext, str, None]) -> Optional[str]:
    """从位置上下文推断 POI/天气检索区域。"""
    label = _label_from_context(ctx)
    if not label:
        return None
    # 去掉常见后缀，保留城市级名称
    for suffix in ("市", "省", "区", "县"):
        if label.endswith(suffix) and len(label) > len(suffix) + 1:
            return label
    return label


def infer_weather_region(
    user_input: str,
    location_context: Union[LocationContext, str, None],
) -> Optional[str]:
    """从用户句子和位置上下文中推断查询区域。"""
    text = (user_input or "").strip()
    match = _CITY_IN_QUERY.search(text)
    if match:
        city = match.group(1).strip()
        if city and city not in ("今天", "现在", "这边", "这里", "当地"):
            return city

    region = infer_search_region(location_context)
    if region:
        return region

    return None
