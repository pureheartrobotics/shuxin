from shuxin.core.config import MapConfig
from shuxin.integrations.location.gate import may_need_location, should_attach_location_tools


def test_may_need_location_positive_samples():
    assert may_need_location("北京今天天气怎么样")
    assert may_need_location("从这到国贸怎么走")
    assert may_need_location("附近有什么餐厅")
    assert may_need_location("你知道我们现在在什么")
    assert may_need_location("我们这个地方有什么好吃的吗？")


def test_may_need_location_negative_samples():
    assert not may_need_location("你好呀")
    assert not may_need_location("")
    assert not may_need_location("   ")


def test_should_attach_location_tools_respects_gate_flag():
    cfg = MapConfig(gate_enabled=False)
    assert should_attach_location_tools("你好", cfg)

    cfg_on = MapConfig(gate_enabled=True)
    assert should_attach_location_tools("今天天气", cfg_on)
    assert not should_attach_location_tools("你好", cfg_on)
