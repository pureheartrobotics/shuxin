from __future__ import annotations

from shuxin.integrations.location.dsml import (
    DsmlStreamFilter,
    extract_dsml_tool_calls,
    strip_dsml_blocks,
)

_SAMPLE_PREFIX = "（初心指尖轻轻划过，调出天气图） 我查一下现在的情况—— "
_SAMPLE_DSML = (
    '<｜｜DSML｜｜tool_calls> <｜｜DSML｜｜invoke name="map_weather"> '
    '<｜｜DSML｜｜parameter name="location" string="true">东京都江东区</｜｜DSML｜｜parameter> '
    '<｜｜DSML｜｜parameter name="is_chinese_mainland" string="false">false</｜｜DSML｜｜parameter> '
    "</｜｜DSML｜｜invoke> </｜｜DSML｜｜tool_calls>"
)


def test_extract_dsml_tool_calls_map_weather():
    calls = extract_dsml_tool_calls(_SAMPLE_PREFIX + _SAMPLE_DSML)
    assert len(calls) == 1
    assert calls[0].name == "map_weather"
    assert "东京都江东区" in calls[0].arguments
    assert calls[0].id.startswith("dsml_")


def test_strip_dsml_blocks_removes_tool_calls():
    cleaned = strip_dsml_blocks(_SAMPLE_PREFIX + _SAMPLE_DSML)
    assert "DSML" not in cleaned
    assert "我查一下现在的情况" in cleaned


def test_dsml_stream_filter_single_chunk():
    filt = DsmlStreamFilter()
    raw = _SAMPLE_PREFIX + _SAMPLE_DSML
    out = filt.feed(raw)
    assert "DSML" not in out
    assert "我查一下" in out


def test_dsml_stream_filter_split_across_chunks():
    filt = DsmlStreamFilter()
    raw = _SAMPLE_PREFIX + _SAMPLE_DSML
    mid = len(_SAMPLE_PREFIX) + 10
    part1 = raw[:mid]
    part2 = raw[mid:]
    out1 = filt.feed(part1)
    out2 = filt.feed(part2)
    assert "DSML" not in (out1 + out2)
    assert "我查一下" in (out1 + out2)


def test_strip_preserves_normal_chinese():
    text = "北京今天天气不错，适合出门。"
    assert strip_dsml_blocks(text) == text
