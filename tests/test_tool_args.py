from shuxin.integrations.location.provider import LocationContext
from shuxin.integrations.location.tool_args import (
    city_adcode_from_district,
    normalize_map_search_places_args,
    normalize_map_weather_args,
)


def test_city_adcode_from_district():
    assert city_adcode_from_district("440305") == "440300"


def test_normalize_weather_from_ctx_city_adcode():
    ctx = LocationContext(city="深圳市", city_adcode="440300", label="深圳市")
    args = normalize_map_weather_args({"region": "深圳市"}, ctx)
    assert args == {"district_id": "440300", "is_china": "true"}


def test_normalize_weather_rejects_city_name_without_ctx():
    assert normalize_map_weather_args({"location": "杭州市"}, None) is None


def test_normalize_poi_prefers_coordinates_for_profile():
    ctx = LocationContext(
        lat=22.54,
        lng=114.06,
        city="深圳市",
        label="深圳市",
        source="profile",
        confidence="low",
    )
    args = normalize_map_search_places_args({"query": "美食"}, ctx)
    assert args is not None
    assert args["location"] == "22.54,114.06"
    assert args["radius"] == 3000


def test_normalize_poi_ip_uses_city_region():
    ctx = LocationContext(
        lat=23.97,
        lng=113.83,
        city="深圳市",
        label="深圳市",
        source="ip",
    )
    args = normalize_map_search_places_args({"query": "美食"}, ctx)
    assert args is not None
    assert args.get("region") == "深圳市"
    assert "location" not in args


def test_normalize_poi_city_fallback():
    ctx = LocationContext(city="深圳市", label="深圳市")
    args = normalize_map_search_places_args({"query": "美食"}, ctx)
    assert args == {
        "query": "美食",
        "tag": "美食",
        "region": "深圳市",
        "is_chinese_mainland": "true",
    }
