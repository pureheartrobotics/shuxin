"""TTS 后处理：初心式电脑女声（FX 串行链，处理人声本身，不叠背景电流）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pydub import AudioSegment

EFFECT_KAREN = "karen"
EFFECT_ELECTRIC = "electric"
KAREN_STYLE_EFFECTS = frozenset({EFFECT_KAREN, EFFECT_ELECTRIC})
STRENGTH_LEVELS = ("low", "medium", "high")


@dataclass(frozen=True)
class KarenPreset:
    hp_hz: int
    lp_hz: int
    downsample_hz: int
    bits: int
    clip_drive: float
    chorus_delay_ms: float
    chorus_mix: float
    ring_hz: float
    ring_mix: float
    compress_threshold: float
    compress_ratio: float


# Tuning variants for voiceover reference matching (see scripts/generate_voiceover_candidates.py).
VOICEOVER_PRESET_CLEAR = KarenPreset(
    hp_hz=480,
    lp_hz=4200,
    downsample_hz=16000,
    bits=8,
    clip_drive=1.9,
    chorus_delay_ms=18.0,
    chorus_mix=0.18,
    ring_hz=62.0,
    ring_mix=0.05,
    compress_threshold=0.26,
    compress_ratio=2.8,
)
VOICEOVER_PRESET_BALANCED = KarenPreset(
    hp_hz=400,
    lp_hz=3900,
    downsample_hz=14000,
    bits=8,
    clip_drive=2.0,
    chorus_delay_ms=19.0,
    chorus_mix=0.22,
    ring_hz=63.0,
    ring_mix=0.07,
    compress_threshold=0.25,
    compress_ratio=2.9,
)
VOICEOVER_PRESET_GRIT = KarenPreset(
    hp_hz=450,
    lp_hz=3800,
    downsample_hz=14000,
    bits=6,
    clip_drive=2.4,
    chorus_delay_ms=20.0,
    chorus_mix=0.20,
    ring_hz=65.0,
    ring_mix=0.06,
    compress_threshold=0.24,
    compress_ratio=3.0,
)
# shuxin_real 导向：暖色基链 + 中等机器感，弱化 chorus、加强轻环调
VOICEOVER_PRESET_WARM_ROBOT_LIGHT = KarenPreset(
    hp_hz=420,
    lp_hz=4100,
    downsample_hz=16000,
    bits=9,
    clip_drive=1.7,
    chorus_delay_ms=16.0,
    chorus_mix=0.10,
    ring_hz=88.0,
    ring_mix=0.08,
    compress_threshold=0.27,
    compress_ratio=3.0,
)
VOICEOVER_PRESET_WARM_ROBOT = KarenPreset(
    hp_hz=400,
    lp_hz=4000,
    downsample_hz=15000,
    bits=8,
    clip_drive=1.85,
    chorus_delay_ms=17.0,
    chorus_mix=0.12,
    ring_hz=92.0,
    ring_mix=0.10,
    compress_threshold=0.26,
    compress_ratio=3.1,
)
VOICEOVER_PRESET_WARM_ROBOT_MED = KarenPreset(
    hp_hz=380,
    lp_hz=3900,
    downsample_hz=14000,
    bits=8,
    clip_drive=2.0,
    chorus_delay_ms=18.0,
    chorus_mix=0.14,
    ring_hz=95.0,
    ring_mix=0.12,
    compress_threshold=0.25,
    compress_ratio=3.2,
)

_PRESETS: dict[str, KarenPreset] = {
    "low": KarenPreset(
        hp_hz=280,
        lp_hz=3800,
        downsample_hz=16000,
        bits=8,
        clip_drive=1.8,
        chorus_delay_ms=16.0,
        chorus_mix=0.22,
        ring_hz=60.0,
        ring_mix=0.06,
        compress_threshold=0.28,
        compress_ratio=2.5,
    ),
    "medium": VOICEOVER_PRESET_CLEAR,
    "high": KarenPreset(
        hp_hz=320,
        lp_hz=3400,
        downsample_hz=10000,
        bits=6,
        clip_drive=2.8,
        chorus_delay_ms=24.0,
        chorus_mix=0.38,
        ring_hz=72.0,
        ring_mix=0.12,
        compress_threshold=0.22,
        compress_ratio=3.5,
    ),
}


def is_karen_style_effect(effect: str) -> bool:
    return (effect or "").strip().lower() in KAREN_STYLE_EFFECTS


def _normalize_strength(strength: str | None) -> str:
    value = (strength or "medium").strip().lower()
    if value not in _PRESETS:
        return "medium"
    return value


def _to_float_mono(samples: np.ndarray, sample_width: int, channels: int) -> np.ndarray:
    max_val = float(1 << (8 * sample_width - 1))
    arr = samples.astype(np.float32) / max_val
    if channels == 1:
        return arr
    arr = arr.reshape(-1, channels)
    return arr.mean(axis=1)


def _from_float_mono(mono: np.ndarray, *, sample_width: int) -> np.ndarray:
    max_val = float(1 << (8 * sample_width - 1) - 1)
    clipped = np.clip(mono, -1.0, 1.0)
    return (clipped * max_val).astype(np.int16)


def _telephone_band(segment: "AudioSegment", preset: KarenPreset) -> "AudioSegment":
    from pydub.effects import high_pass_filter, low_pass_filter

    out = high_pass_filter(segment, preset.hp_hz)
    return low_pass_filter(out, preset.lp_hz)


def _downsample_upsample(segment: "AudioSegment", target_hz: int) -> "AudioSegment":
    native = segment.frame_rate
    if target_hz >= native:
        return segment
    return segment.set_frame_rate(target_hz).set_frame_rate(native)


def _bitcrush(mono: np.ndarray, bits: int) -> np.ndarray:
    levels = max(2, 2**bits)
    step = 2.0 / levels
    return np.round(mono / step) * step


def _soft_clip(mono: np.ndarray, drive: float) -> np.ndarray:
    if drive <= 0:
        return mono
    return np.tanh(mono * drive).astype(np.float32) / np.tanh(drive)


def _mono_chorus(mono: np.ndarray, sample_rate: int, delay_ms: float, mix: float) -> np.ndarray:
    if mix <= 0 or len(mono) == 0:
        return mono
    delay_samples = int(sample_rate * delay_ms / 1000.0)
    if delay_samples <= 0 or delay_samples >= len(mono):
        return mono
    delayed = np.zeros_like(mono)
    delayed[delay_samples:] = mono[:-delay_samples]
    return (mono + delayed * mix).astype(np.float32)


def _ring_modulate(mono: np.ndarray, sample_rate: int, hz: float, mix: float) -> np.ndarray:
    if mix <= 0 or len(mono) == 0:
        return mono
    t = np.arange(len(mono), dtype=np.float32) / float(sample_rate)
    carrier = np.sin(2.0 * np.pi * hz * t, dtype=np.float32)
    return mono * ((1.0 - mix) + mix * carrier)


def _compress(mono: np.ndarray, threshold: float, ratio: float) -> np.ndarray:
    if ratio <= 1.0:
        return mono
    out = mono.copy()
    magnitude = np.abs(out)
    over = magnitude > threshold
    if not np.any(over):
        return out
    out[over] = np.sign(out[over]) * (
        threshold + (magnitude[over] - threshold) / ratio
    )
    return out.astype(np.float32)


def _segment_from_mono(
    mono: np.ndarray,
    *,
    frame_rate: int,
    sample_width: int,
) -> "AudioSegment":
    from pydub import AudioSegment

    pcm = _from_float_mono(mono, sample_width=sample_width)
    return AudioSegment(
        pcm.tobytes(),
        frame_rate=frame_rate,
        sample_width=sample_width,
        channels=1,
    )


def apply_karen_voice(
    segment: "AudioSegment",
    *,
    strength: str | None = "medium",
    preset_override: KarenPreset | None = None,
) -> "AudioSegment":
    """Karen-style FX: telephone → downsample → crush/clip → chorus → ring → compress."""
    preset = preset_override or _PRESETS[_normalize_strength(strength)]
    return _apply_karen_preset(segment, preset)


def _apply_karen_preset(segment: "AudioSegment", preset: KarenPreset) -> "AudioSegment":
    if segment.channels > 1:
        segment = segment.set_channels(1)

    out = _telephone_band(segment, preset)
    out = _downsample_upsample(out, preset.downsample_hz)

    sample_width = out.sample_width
    frame_rate = out.frame_rate
    mono = _to_float_mono(
        np.array(out.get_array_of_samples()),
        sample_width,
        1,
    )
    mono = _bitcrush(mono, preset.bits)
    mono = _soft_clip(mono, preset.clip_drive)
    mono = _mono_chorus(mono, frame_rate, preset.chorus_delay_ms, preset.chorus_mix)
    mono = _ring_modulate(mono, frame_rate, preset.ring_hz, preset.ring_mix)
    mono = _compress(mono, preset.compress_threshold, preset.compress_ratio)

    out = _segment_from_mono(mono, frame_rate=frame_rate, sample_width=sample_width)

    try:
        from pydub.effects import compress_dynamic_range

        out = compress_dynamic_range(
            out,
            threshold=-18.0,
            ratio=float(preset.compress_ratio),
            attack=5.0,
            release=80.0,
        )
    except Exception:
        pass

    if out.max_dBFS < -3.0:
        out = out.apply_gain(min(6.0, -1.0 - out.max_dBFS))
    return out


def apply_electric_voice(
    segment: "AudioSegment",
    *,
    strength: str | None = "medium",
    preset_override: KarenPreset | None = None,
) -> "AudioSegment":
    """Backward-compatible alias for the Karen FX chain (no background hiss)."""
    return apply_karen_voice(
        segment,
        strength=strength,
        preset_override=preset_override,
    )
