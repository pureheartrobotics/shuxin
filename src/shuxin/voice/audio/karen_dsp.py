"""Karen-style DSP v2: pitch flattening, ring modulation (wet/dry), comb, presence EQ."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pydub import AudioSegment

MIN_SAMPLES = 4096


@dataclass(frozen=True)
class KarenDspPreset:
    pitch_range_ratio: float
    ring_hz: float
    ring_wet: float
    comb_delay_ms: float
    comb_feedback: float
    eq_low_hz: float
    eq_low_db: float
    eq_high_hz: float
    eq_high_db: float
    hp_hz: int
    lp_hz: int
    crush_bits: int
    crush_mix: float
    pitch_shift_rate: float = 1.0
    label: str = ""


KAREN_V2_MILD = KarenDspPreset(
    pitch_range_ratio=0.08,
    ring_hz=85.0,
    ring_wet=0.35,
    comb_delay_ms=15.0,
    comb_feedback=0.30,
    eq_low_hz=2000.0,
    eq_low_db=3.0,
    eq_high_hz=3200.0,
    eq_high_db=3.5,
    hp_hz=250,
    lp_hz=4000,
    crush_bits=10,
    crush_mix=0.08,
    label="R_v2_mild",
)

KAREN_V2_MED = KarenDspPreset(
    pitch_range_ratio=0.10,
    ring_hz=90.0,
    ring_wet=0.40,
    comb_delay_ms=15.0,
    comb_feedback=0.30,
    eq_low_hz=2000.0,
    eq_low_db=3.0,
    eq_high_hz=3200.0,
    eq_high_db=3.5,
    hp_hz=250,
    lp_hz=4000,
    crush_bits=9,
    crush_mix=0.12,
    label="S_v2_med",
)

KAREN_V2_BRIGHT = KarenDspPreset(
    pitch_range_ratio=0.10,
    ring_hz=95.0,
    ring_wet=0.40,
    comb_delay_ms=15.0,
    comb_feedback=0.30,
    eq_low_hz=2000.0,
    eq_low_db=3.0,
    eq_high_hz=3000.0,
    eq_high_db=4.5,
    hp_hz=250,
    lp_hz=4200,
    crush_bits=9,
    crush_mix=0.10,
    label="T_v2_bright",
)

KAREN_V2_10LIKE = KarenDspPreset(
    pitch_range_ratio=0.10,
    ring_hz=90.0,
    ring_wet=0.40,
    comb_delay_ms=15.0,
    comb_feedback=0.30,
    eq_low_hz=2000.0,
    eq_low_db=3.0,
    eq_high_hz=3200.0,
    eq_high_db=3.5,
    hp_hz=250,
    lp_hz=4000,
    crush_bits=9,
    crush_mix=0.12,
    pitch_shift_rate=1.04,
    label="U_v2_10like",
)

# shuxin_real 导向：pitch flatten + 环调干湿，无 afftfilt vocoder
KAREN_V2_SHUXIN_MILD = KarenDspPreset(
    pitch_range_ratio=0.06,
    ring_hz=85.0,
    ring_wet=0.28,
    comb_delay_ms=14.0,
    comb_feedback=0.25,
    eq_low_hz=2000.0,
    eq_low_db=2.5,
    eq_high_hz=3200.0,
    eq_high_db=3.0,
    hp_hz=250,
    lp_hz=4100,
    crush_bits=10,
    crush_mix=0.06,
    label="V_shuxin_mild",
)

KAREN_V2_SHUXIN_MED = KarenDspPreset(
    pitch_range_ratio=0.08,
    ring_hz=90.0,
    ring_wet=0.32,
    comb_delay_ms=15.0,
    comb_feedback=0.28,
    eq_low_hz=2000.0,
    eq_low_db=3.0,
    eq_high_hz=3200.0,
    eq_high_db=3.5,
    hp_hz=250,
    lp_hz=4000,
    crush_bits=10,
    crush_mix=0.06,
    label="W_shuxin_med",
)

KAREN_V2_SHUXIN_WARM = KarenDspPreset(
    pitch_range_ratio=0.10,
    ring_hz=92.0,
    ring_wet=0.38,
    comb_delay_ms=15.0,
    comb_feedback=0.30,
    eq_low_hz=2100.0,
    eq_low_db=3.0,
    eq_high_hz=3000.0,
    eq_high_db=4.0,
    hp_hz=260,
    lp_hz=4200,
    crush_bits=9,
    crush_mix=0.08,
    label="X_shuxin_warm",
)


def _to_float_mono(samples: np.ndarray, sample_width: int, channels: int) -> np.ndarray:
    max_val = float(1 << (8 * sample_width - 1))
    arr = samples.astype(np.float32) / max_val
    if channels > 1:
        arr = arr.reshape(-1, channels).mean(axis=1)
    return arr


def _from_float_mono(mono: np.ndarray, *, sample_width: int) -> np.ndarray:
    max_val = float(1 << (8 * sample_width - 1) - 1)
    clipped = np.clip(mono, -1.0, 1.0)
    return (clipped * max_val).astype(np.int16)


def _flatten_pitch(mono: np.ndarray, sr: int, range_ratio: float) -> np.ndarray:
    """Compress pitch excursion toward median (±range_ratio), windowed pitch_shift."""
    import librosa

    orig_len = len(mono)
    work = mono.astype(np.float32)
    pad_len = 0
    if orig_len < MIN_SAMPLES:
        pad_len = MIN_SAMPLES - orig_len
        work = np.pad(work, (0, pad_len))

    f0, voiced_flag, _ = librosa.pyin(
        work,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C7"),
        sr=sr,
    )
    voiced = voiced_flag & np.isfinite(f0) & (f0 > 0)
    if not np.any(voiced):
        return mono

    median_f0 = float(np.nanmedian(f0[voiced]))
    win = max(int(0.2 * sr), 2048)
    hop = win // 2
    out = np.zeros_like(work)
    weight = np.zeros_like(work)

    for start in range(0, len(work) - win + 1, hop):
        end = start + win
        chunk = work[start:end]
        f0_chunk, vf_chunk, _ = librosa.pyin(
            chunk,
            fmin=librosa.note_to_hz("C2"),
            fmax=librosa.note_to_hz("C7"),
            sr=sr,
        )
        v = vf_chunk & np.isfinite(f0_chunk) & (f0_chunk > 0)
        if not np.any(v):
            corrected = chunk
        else:
            local = float(np.nanmedian(f0_chunk[v]))
            clamped = float(
                np.clip(local, median_f0 * (1.0 - range_ratio), median_f0 * (1.0 + range_ratio))
            )
            n_steps = 12.0 * np.log2(clamped / local) if local > 0 else 0.0
            n_steps = float(np.clip(n_steps, -2.0, 2.0))
            corrected = librosa.effects.pitch_shift(chunk, sr=sr, n_steps=n_steps)
            if len(corrected) != len(chunk):
                corrected = corrected[: len(chunk)]

        fade = np.hanning(len(chunk)).astype(np.float32)
        out[start:end] += corrected * fade
        weight[start:end] += fade

    mask = weight > 1e-6
    out[mask] /= weight[mask]
    out[~mask] = work[~mask]
    return out[:orig_len].astype(np.float32)


def _ring_modulate_wet_dry(
    mono: np.ndarray, sample_rate: int, hz: float, wet: float
) -> np.ndarray:
    if wet <= 0 or len(mono) == 0:
        return mono
    dry = 1.0 - wet
    t = np.arange(len(mono), dtype=np.float32) / float(sample_rate)
    carrier = np.sin(2.0 * np.pi * hz * t, dtype=np.float32)
    modulated = mono * carrier
    return (mono * dry + modulated * wet).astype(np.float32)


def _bitcrush(mono: np.ndarray, bits: int, mix: float) -> np.ndarray:
    if mix <= 0:
        return mono
    levels = max(2, 2**bits)
    step = 2.0 / levels
    crushed = np.round(mono / step) * step
    return (mono * (1.0 - mix) + crushed * mix).astype(np.float32)


def _ffmpeg_post(wav_path: Path, preset: KarenDspPreset) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for Karen DSP comb/EQ stage")
    delay = int(preset.comb_delay_ms)
    fb = preset.comb_feedback
    af = (
        f"aecho=0.8:0.85:{delay}:{fb},"
        f"equalizer=f={preset.eq_low_hz:.0f}:t=q:w=1:g={preset.eq_low_db},"
        f"equalizer=f={preset.eq_high_hz:.0f}:t=q:w=1:g={preset.eq_high_db}"
    )
    tmp = wav_path.with_suffix(".post.wav")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(wav_path),
            "-af",
            af,
            str(tmp),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    tmp.replace(wav_path)


def apply_karen_dsp(
    segment: "AudioSegment",
    preset: KarenDspPreset | None = None,
) -> "AudioSegment":
    """Pitch flatten → ring mod (wet/dry) → band → crush → ffmpeg comb+EQ."""
    from pydub import AudioSegment
    from pydub.effects import high_pass_filter, low_pass_filter

    p = preset or KAREN_V2_MED
    if segment.channels > 1:
        segment = segment.set_channels(1)

    if p.pitch_shift_rate != 1.0:
        shifted = int(segment.frame_rate * p.pitch_shift_rate)
        segment = segment._spawn(
            segment.raw_data,
            overrides={"frame_rate": shifted},
        ).set_frame_rate(segment.frame_rate)

    sr = segment.frame_rate
    sample_width = segment.sample_width
    mono = _to_float_mono(
        np.array(segment.get_array_of_samples()),
        sample_width,
        1,
    )

    mono = _flatten_pitch(mono, sr, p.pitch_range_ratio)
    mono = _ring_modulate_wet_dry(mono, sr, p.ring_hz, p.ring_wet)
    mono = _bitcrush(mono, p.crush_bits, p.crush_mix)

    out = _segment_from_mono(mono, frame_rate=sr, sample_width=sample_width)
    out = high_pass_filter(out, p.hp_hz)
    out = low_pass_filter(out, p.lp_hz)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        out.export(str(tmp_path), format="wav")
        _ffmpeg_post(tmp_path, p)
        out = AudioSegment.from_file(str(tmp_path), format="wav")
    finally:
        tmp_path.unlink(missing_ok=True)

    if out.max_dBFS < -3.0:
        out = out.apply_gain(min(6.0, -1.0 - out.max_dBFS))
    return out


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
