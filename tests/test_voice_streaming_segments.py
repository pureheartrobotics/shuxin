from __future__ import annotations

from shuxin.voice.server import _pop_speakable_segments, clean_action_text


def test_pop_speakable_segments_waits_for_sentence_boundary() -> None:
    segments, rest = _pop_speakable_segments("你好，我是")

    assert segments == []
    assert rest == "你好，我是"


def test_pop_speakable_segments_splits_on_weak_punctuation_for_first_segment() -> None:
    segments, rest = _pop_speakable_segments("你好，我是舒心", allow_weak_punctuation=True)

    assert segments == ["你好，"]
    assert rest == "我是舒心"


def test_pop_speakable_segments_splits_finished_sentences() -> None:
    segments, rest = _pop_speakable_segments("你好。我在这里")

    assert segments == ["你好。"]
    assert rest == "我在这里"


def test_pop_speakable_segments_flushes_remaining_text_when_forced() -> None:
    segments, rest = _pop_speakable_segments("没有标点的最后一句", force=True)

    assert segments == ["没有标点的最后一句"]
    assert rest == ""


def test_clean_action_text() -> None:
    assert clean_action_text("（耳朵微微竖起）你还好吗？") == "你还好吗？"
    assert clean_action_text("(耳朵微微竖起，尾巴轻轻摆动，眼中带着一丝好奇与笑意)") == ""
    assert clean_action_text("（耳朵竖起）你好，（尾巴摆动）主人。") == "你好，主人。"
    assert clean_action_text("正常文本") == "正常文本"


def test_pop_speakable_segments_ignores_punctuation_in_parentheses() -> None:
    segments, rest = _pop_speakable_segments("（动作。描述。）你好。")
    assert segments == ["（动作。描述。）你好。"]
    assert rest == ""
