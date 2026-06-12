"""Tests for Karen DSP v2."""

from __future__ import annotations

import numpy as np
import pytest

from shuxin.voice.karen_dsp import (
    KAREN_V2_MED,
    _flatten_pitch,
    _ring_modulate_wet_dry,
    apply_karen_dsp,
)


def test_ring_modulate_wet_dry_preserves_length():
    sr = 24000
    mono = np.sin(2 * np.pi * 440 * np.arange(sr) / sr).astype(np.float32) * 0.5
    out = _ring_modulate_wet_dry(mono, sr, 90.0, 0.4)
    assert len(out) == len(mono)


def test_flatten_pitch_short_audio_no_crash():
    pytest.importorskip("librosa")
    sr = 24000
    mono = np.sin(2 * np.pi * 300 * np.arange(1000) / sr).astype(np.float32) * 0.3
    out = _flatten_pitch(mono, sr, 0.10)
    assert len(out) == len(mono)


def test_apply_karen_dsp_short_segment():
    pytest.importorskip("librosa")
    pytest.importorskip("pydub")
    from pydub import AudioSegment
    from pydub.generators import Sine

    tone = Sine(440).to_audio_segment(duration=500)
    out = apply_karen_dsp(tone, preset=KAREN_V2_MED)
    assert len(out) > 0
    assert out.frame_rate == tone.frame_rate
