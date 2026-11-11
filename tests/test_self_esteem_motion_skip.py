from __future__ import annotations

from shuxin.plugins.companion.self_esteem import (
    SelfEsteemSystem,
    is_non_social_utterance,
)


def test_drive_and_filler_are_non_social() -> None:
    assert is_non_social_utterance("往前走一点")
    assert is_non_social_utterance("小车前进")
    assert is_non_social_utterance("停一下")
    assert is_non_social_utterance("嗯。")
    assert is_non_social_utterance("哦")
    assert not is_non_social_utterance("你真没用")
    assert not is_non_social_utterance("今天心情不好")


def test_motion_does_not_hurt_or_keep_silence(tmp_path) -> None:
    system = SelfEsteemSystem(data_dir=str(tmp_path))
    system.state.value = 18
    system.state.is_silent = True
    system.state.silent_start = 1.0
    result = system.process_interaction("前进")
    assert result["is_silent"] is False
    assert result["delta"] == 0
    assert system.state.is_silent is False


def test_insult_still_can_trigger_silence(tmp_path) -> None:
    system = SelfEsteemSystem(data_dir=str(tmp_path))
    system.state.value = 25
    result = system.process_interaction("你真没用，废物")
    assert result["delta"] < 0
    assert result["is_silent"] is True
