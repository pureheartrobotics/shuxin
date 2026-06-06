from __future__ import annotations

import numpy as np
import pytest

from shuxin.voice.audio_effects import (
    VOICEOVER_PRESET_CLEAR,
    apply_electric_voice,
    apply_karen_voice,
    is_karen_style_effect,
)
from shuxin.voice.config import ProviderConfig, resolve_tts_effect


def _sine_segment(*, ms: int = 400, hz: int = 440) -> object:
    from pydub import AudioSegment

    sample_rate = 24000
    t = np.linspace(0, ms / 1000.0, int(sample_rate * ms / 1000), endpoint=False)
    wave = (0.4 * np.sin(2 * np.pi * hz * t) * 32767).astype(np.int16)
    return AudioSegment(
        wave.tobytes(),
        frame_rate=sample_rate,
        sample_width=2,
        channels=1,
    )


def test_apply_karen_changes_waveform() -> None:
    pytest.importorskip("pydub")
    original = _sine_segment()
    processed = apply_karen_voice(original, strength="medium")
    orig = np.array(original.get_array_of_samples(), dtype=np.float32)
    proc = np.array(processed.get_array_of_samples(), dtype=np.float32)
    assert len(orig) == len(proc)
    assert float(np.std(proc - orig)) > 100.0
    assert processed.channels == 1


def test_preset_override_differs_from_medium() -> None:
    pytest.importorskip("pydub")
    original = _sine_segment()
    medium = apply_karen_voice(original, strength="medium")
    clear = apply_karen_voice(original, preset_override=VOICEOVER_PRESET_CLEAR)
    m = np.array(medium.get_array_of_samples(), dtype=np.float32)
    c = np.array(clear.get_array_of_samples(), dtype=np.float32)
    assert float(np.std(m - c)) > 1.0


def test_electric_alias_matches_karen() -> None:
    pytest.importorskip("pydub")
    original = _sine_segment()
    karen = apply_karen_voice(original, strength="low")
    electric = apply_electric_voice(original, strength="low")
    k = np.array(karen.get_array_of_samples(), dtype=np.float32)
    e = np.array(electric.get_array_of_samples(), dtype=np.float32)
    assert len(k) == len(e)
    assert float(np.std(k - e)) < 1.0


def test_is_karen_style_effect() -> None:
    assert is_karen_style_effect("karen")
    assert is_karen_style_effect("electric")
    assert not is_karen_style_effect("none")


def test_resolve_tts_effect_env_and_device() -> None:
    cfg = ProviderConfig(effect="")
    assert resolve_tts_effect(cfg) == ("none", "medium")

    cfg_device = ProviderConfig(effect="karen", effect_strength="high")
    assert resolve_tts_effect(cfg_device) == ("karen", "high")

    cfg_electric = ProviderConfig(effect="electric")
    assert resolve_tts_effect(cfg_electric) == ("electric", "medium")


def test_resolve_tts_effect_env_override(monkeypatch) -> None:
    monkeypatch.setenv("SHUXIN_TTS_EFFECT", "karen")
    cfg = ProviderConfig(effect="")
    assert resolve_tts_effect(cfg) == ("karen", "medium")

    monkeypatch.setenv("SHUXIN_TTS_EFFECT", "electric")
    assert resolve_tts_effect(cfg) == ("electric", "medium")

    cfg_off = ProviderConfig(effect="none")
    assert resolve_tts_effect(cfg_off) == ("none", "medium")
