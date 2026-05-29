from __future__ import annotations

from shuxin.voice.server import _pop_speakable_segments


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
