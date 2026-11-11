from shuxin.voice.stt_noise import is_noise_utterance


def test_fillers_are_noise() -> None:
    assert is_noise_utterance("嗯")
    assert is_noise_utterance("嗯。")
    assert is_noise_utterance("啊")
    assert is_noise_utterance("哦")
    assert is_noise_utterance("嗯嗯")
    assert is_noise_utterance("uh")
    assert is_noise_utterance("")
    assert is_noise_utterance("   ")


def test_real_speech_is_kept() -> None:
    assert not is_noise_utterance("你好")
    assert not is_noise_utterance("嗯，好的")
    assert not is_noise_utterance("几点了")
    assert not is_noise_utterance("喂")
    assert not is_noise_utterance("停")
