from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

from shuxin.core.llm import (
    _ThinkTagFilter,
    _THINK_CLOSE,
    _THINK_OPEN,
    _openai_stream_delta_text,
)

THINK_OPEN = _THINK_OPEN
THINK_CLOSE = _THINK_CLOSE


def test_reasoning_content_not_yielded() -> None:
    delta = SimpleNamespace(content="", reasoning_content="内心独白不应输出")
    assert _openai_stream_delta_text(delta) == ""


def test_reasoning_content_logged_debug() -> None:
    delta = SimpleNamespace(content="", reasoning_content="some reasoning")
    with patch("shuxin.core.llm.logger") as mock_logger:
        _openai_stream_delta_text(delta)
        mock_logger.debug.assert_called_once()
        assert "[LLM-REASONING]" in mock_logger.debug.call_args[0][0]


def test_content_passthrough() -> None:
    delta = SimpleNamespace(content="Hello", reasoning_content="ignored")
    assert _openai_stream_delta_text(delta) == "Hello"


def test_think_tag_single_chunk() -> None:
    filt = _ThinkTagFilter()
    raw = f"{THINK_OPEN}内心{THINK_CLOSE}答案"
    assert filt.feed(raw) == "答案"


def test_think_tag_split_across_chunks() -> None:
    filt = _ThinkTagFilter()
    assert filt.feed("<thi") == ""
    assert filt.feed("nk>内心</th") == ""
    assert filt.feed("ink>答案") == "答案"


def test_think_tag_preserves_outside_text() -> None:
    filt = _ThinkTagFilter()
    assert filt.feed("前缀") == "前缀"
    assert filt.feed(f"{THINK_OPEN}隐藏{THINK_CLOSE}后缀") == "后缀"
