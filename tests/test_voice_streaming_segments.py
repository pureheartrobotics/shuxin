from __future__ import annotations

from shuxin.voice.api.ws_tts import TtsSentenceSegmenter
from shuxin.voice.audio.text_sanitize import (
    clean_action_text,
    has_unclosed_parenthesis,
    prepare_speakable_text,
    strip_markdown_for_tts,
)

def _pop_speakable_segments(buffer: str, *, force: bool = False, allow_weak_punctuation: bool = False) -> tuple[list[str], str]:
    return TtsSentenceSegmenter(None).pop_segments(buffer, force=force, allow_weak_punctuation=allow_weak_punctuation)


def test_pop_speakable_segments_waits_for_sentence_boundary() -> None:
    segments, rest = _pop_speakable_segments("你好，我是")

    assert segments == []
    assert rest == "你好，我是"


def test_pop_speakable_segments_splits_on_weak_punctuation_for_first_segment() -> None:
    segments, rest = _pop_speakable_segments("你好，我是初心", allow_weak_punctuation=True)

    assert segments == ["你好，"]
    assert rest == "我是初心"


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
    assert clean_action_text("（查到结果后，抬头看向你，语气干脆利落 我们目前") == "我们目前"
    assert clean_action_text("我们目前（查到结果后，抬头看向你") == "我们目前"


def test_pop_speakable_segments_ignores_punctuation_in_parentheses() -> None:
    segments, rest = _pop_speakable_segments("（动作。描述。）你好。")
    assert segments == ["（动作。描述。）你好。"]
    assert rest == ""


def test_pop_speakable_segments_does_not_cut_inside_unclosed_parentheses() -> None:
    long_action = "（" + "查" * 50 + "我们目前在深圳"
    segments, rest = _pop_speakable_segments(long_action)

    assert segments == []
    assert rest == long_action
    assert has_unclosed_parenthesis(rest)


def test_pop_speakable_segments_force_strips_unclosed_action_for_tts() -> None:
    long_action = "（" + "查" * 50 + " 我们目前在深圳"
    segments, rest = _pop_speakable_segments(long_action, force=True)

    assert segments == [long_action]
    assert rest == ""
    assert prepare_speakable_text(segments[0]) == "我们目前在深圳"


def test_strip_markdown_for_tts() -> None:
    assert strip_markdown_for_tts("我们目前在**广东省深圳市**。") == "我们目前在广东省深圳市。"
    assert strip_markdown_for_tts("室外温度 **28°C**") == "室外温度 28°C"
    assert strip_markdown_for_tts("`*code*` and __bold__") == "code and bold"


def test_prepare_speakable_text_weather_example() -> None:
    raw = "（查到结果后，抬头看向你，语气干脆利落） 我们目前在**广东省深圳市**。"
    assert prepare_speakable_text(raw) == "我们目前在广东省深圳市。"


def test_prepare_speakable_text_action_only_is_empty() -> None:
    assert prepare_speakable_text("（查到结果后，抬头看向你）") == ""
