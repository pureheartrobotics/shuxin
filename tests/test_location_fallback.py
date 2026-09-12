from shuxin.integrations.location.fallback import (
    infer_poi_query,
    infer_search_region,
    infer_weather_region,
    is_tool_result_usable,
    should_direct_poi_search,
    should_direct_weather_call,
)
from shuxin.integrations.location.provider import LocationContext


def test_should_direct_weather_call():
    assert should_direct_weather_call("现在天气怎么样？")
    assert not should_direct_weather_call("你知道我们现在在什么")


def test_should_direct_poi_search():
    assert should_direct_poi_search("我们这个地方有什么好吃的吗？")
    assert not should_direct_poi_search("你好呀")


def test_infer_poi_query():
    assert infer_poi_query("有什么好吃的") == "美食"


def test_infer_search_region_from_context():
    ctx = LocationContext(label="杭州市", source="ip", confidence="medium")
    assert infer_search_region(ctx) == "杭州市"


def test_infer_weather_region_from_context():
    ctx = LocationContext(label="北京市", source="ip", confidence="medium")
    assert infer_weather_region("今天的天气怎么", ctx) == "北京市"


def test_is_tool_result_usable_rejects_auth_error():
    assert not is_tool_result_usable("Authentication failed: APP IP校验失败")
    assert is_tool_result_usable('{"temp": 20}')
