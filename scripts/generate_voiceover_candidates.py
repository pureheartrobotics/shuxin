#!/usr/bin/env python3
"""Generate TTS candidates to match outputs/voiceover-candidates/shuxin_real.mp3 timbre."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shuxin.voice.audio_effects import (  # noqa: E402
    KarenPreset,
    VOICEOVER_PRESET_BALANCED,
    VOICEOVER_PRESET_CLEAR,
    VOICEOVER_PRESET_GRIT,
    VOICEOVER_PRESET_WARM_ROBOT,
    VOICEOVER_PRESET_WARM_ROBOT_LIGHT,
    VOICEOVER_PRESET_WARM_ROBOT_MED,
    apply_karen_voice,
)
from shuxin.voice.config import ProviderConfig  # noqa: E402
from shuxin.voice.karen_dsp import (  # noqa: E402
    KAREN_V2_10LIKE,
    KAREN_V2_BRIGHT,
    KAREN_V2_MED,
    KAREN_V2_MILD,
    KAREN_V2_SHUXIN_MED,
    KAREN_V2_SHUXIN_MILD,
    KAREN_V2_SHUXIN_WARM,
    KarenDspPreset,
    apply_karen_dsp,
)
from shuxin.voice.providers import EdgeTTSProvider  # noqa: E402

DEFAULT_TEXT = (
    "你好，我是舒心。我会陪你聊天、听你说话，也会记得我们最近聊过的事。"
    "此刻如果你愿意，可以直接对我说心里话。"
)
SHORT_TEXT = "你好，我是舒心。此刻如果你愿意，可以直接对我说心里话。"
OUT_DIR = ROOT / "outputs" / "voiceover-candidates"
XIAOYI_VOICE = "zh-CN-XiaoyiNeural"
DEFAULT_RATE = "-8%"
DEFAULT_PITCH = "-2Hz"
# Edge TTS mp3 is 24 kHz; pitch via asetrate must use 24000 not 44100.
EDGE_SAMPLE_RATE = 24000
SHUXIN_REAL_SAMPLE_RATE = 22050


@dataclass(frozen=True)
class Candidate:
    filename: str
    voice: str
    preset: KarenPreset
    preset_label: str
    rate: str
    pitch: str
    export_sample_rate: int | None = None


@dataclass(frozen=True)
class FfmpegCandidate:
    filename: str
    af_filter: str
    preset_label: str
    voice: str = XIAOYI_VOICE
    rate: str = DEFAULT_RATE
    pitch: str = DEFAULT_PITCH


@dataclass(frozen=True)
class HybridCandidate:
    filename: str
    preset: KarenPreset
    af_filter: str
    preset_label: str
    voice: str = XIAOYI_VOICE
    rate: str = DEFAULT_RATE
    pitch: str = DEFAULT_PITCH


CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "01_xiaoxiao_clear.mp3",
        "zh-CN-XiaoxiaoNeural",
        VOICEOVER_PRESET_CLEAR,
        "A_clear",
        "-8%",
        "-2Hz",
    ),
    Candidate(
        "02_xiaoxiao_balanced.mp3",
        "zh-CN-XiaoxiaoNeural",
        VOICEOVER_PRESET_BALANCED,
        "B_balanced",
        "-8%",
        "-2Hz",
    ),
    Candidate(
        "03_xiaoyi_clear.mp3",
        "zh-CN-XiaoyiNeural",
        VOICEOVER_PRESET_CLEAR,
        "A_clear",
        "-8%",
        "-2Hz",
    ),
    Candidate(
        "04_xiaoyi_balanced.mp3",
        "zh-CN-XiaoyiNeural",
        VOICEOVER_PRESET_BALANCED,
        "B_balanced",
        "-8%",
        "-2Hz",
    ),
    Candidate(
        "05_xiaoxiao_grit.mp3",
        "zh-CN-XiaoxiaoNeural",
        VOICEOVER_PRESET_GRIT,
        "C_grit",
        "-8%",
        "-2Hz",
    ),
)

_AFFTFILT_PHASE_ZERO = (
    "afftfilt=real='hypot(re\\,im)*cos(0)':imag='hypot(re\\,im)*sin(0)'"
)

FFMPEG_PHONE_CANDIDATES: tuple[FfmpegCandidate, ...] = (
    FfmpegCandidate(
        "06_xiaoyi_ffmpeg_mild.mp3",
        "highpass=f=220,lowpass=f=5200,acrusher=bits=12:mix=0.12,volume=1.05",
        "D_mild",
    ),
    FfmpegCandidate(
        "07_xiaoyi_ffmpeg_balanced.mp3",
        "highpass=f=250,lowpass=f=4200,acrusher=bits=10:mix=0.22,volume=1.1",
        "E_nochorus",
    ),
    FfmpegCandidate(
        "08_xiaoyi_ffmpeg_grit.mp3",
        "highpass=f=300,lowpass=f=3600,acrusher=bits=8:mix=0.35,volume=1.15",
        "F_nochorus_grit",
    ),
)

FFMPEG_ROBOT_CANDIDATES: tuple[FfmpegCandidate, ...] = (
    FfmpegCandidate(
        "09_robot_ringmod_mild.mp3",
        "highpass=f=300,lowpass=f=3600,tremolo=f=50:d=0.30,"
        "aecho=0.8:0.85:12:0.25,acrusher=bits=10:mix=0.15,volume=1.08",
        "G_ringmod",
    ),
    FfmpegCandidate(
        "10_robot_vocoder_med.mp3",
        f"asetrate={EDGE_SAMPLE_RATE}*1.04,aresample={EDGE_SAMPLE_RATE},highpass=f=300,lowpass=f=3400,"
        f"{_AFFTFILT_PHASE_ZERO}:win_size=512:overlap=0.75,"
        "tremolo=f=50:d=0.30,aecho=0.8:0.85:14:0.28,acrusher=bits=9:mix=0.18,volume=1.10",
        "H_vocoder",
    ),
    FfmpegCandidate(
        "11_robot_full_strong.mp3",
        f"asetrate={EDGE_SAMPLE_RATE}*1.05,aresample={EDGE_SAMPLE_RATE},atempo=0.97,highpass=f=320,lowpass=f=3200,"
        f"{_AFFTFILT_PHASE_ZERO}:win_size=1024:overlap=0.8,"
        "tremolo=f=45:d=0.45,aecho=0.85:0.9:16:0.32,acrusher=bits=8:mix=0.28,volume=1.12",
        "I_full",
    ),
    FfmpegCandidate(
        "12_robot_pitch_compress.mp3",
        f"asetrate={EDGE_SAMPLE_RATE}*1.035,aresample={EDGE_SAMPLE_RATE},atempo=0.97,highpass=f=280,lowpass=f=3800,"
        "acompressor=threshold=-22dB:ratio=3:attack=5:release=80,"
        "tremolo=f=22:d=0.18,acrusher=bits=9:mix=0.22,volume=1.1",
        "J_pitch",
    ),
    FfmpegCandidate(
        "13_robot_pitch_strong.mp3",
        f"asetrate={EDGE_SAMPLE_RATE}*1.06,aresample={EDGE_SAMPLE_RATE},atempo=0.95,highpass=f=320,lowpass=f=3400,"
        "acompressor=threshold=-24dB:ratio=4:attack=3:release=60,"
        "tremolo=f=28:d=0.24,acrusher=bits=8:mix=0.32,volume=1.15",
        "K_pitch_strong",
    ),
    FfmpegCandidate(
        "14_robot_eq_vocoder.mp3",
        f"asetrate={EDGE_SAMPLE_RATE}*1.045,aresample={EDGE_SAMPLE_RATE},atempo=0.96,highpass=f=350,lowpass=f=3200,"
        "equalizer=f=1200:t=q:w=1:g=3,equalizer=f=2500:t=q:w=1:g=4,"
        "acompressor=threshold=-25dB:ratio=4,tremolo=f=18:d=0.22,"
        "acrusher=bits=8:mix=0.28,aecho=0.8:0.85:14:0.22,volume=1.12",
        "L_eq",
    ),
    FfmpegCandidate(
        "15_robot_vocoder_light.mp3",
        f"asetrate={EDGE_SAMPLE_RATE}*1.03,aresample={EDGE_SAMPLE_RATE},highpass=f=280,lowpass=f=3600,"
        f"{_AFFTFILT_PHASE_ZERO}:win_size=256:overlap=0.5,"
        "tremolo=f=48:d=0.25,aecho=0.8:0.85:12:0.22,acrusher=bits=10:mix=0.12,volume=1.08",
        "M_vocoder_light",
    ),
)

FFMPEG_CANDIDATES: tuple[FfmpegCandidate, ...] = (
    FFMPEG_PHONE_CANDIDATES + FFMPEG_ROBOT_CANDIDATES
)


@dataclass(frozen=True)
class DspCandidate:
    filename: str
    preset: KarenDspPreset
    voice: str = XIAOYI_VOICE
    rate: str = DEFAULT_RATE
    pitch: str = DEFAULT_PITCH


DSP_REFINE_CANDIDATES: tuple[DspCandidate, ...] = (
    DspCandidate("16_karen_v2_mild.mp3", KAREN_V2_MILD),
    DspCandidate("17_karen_v2_med.mp3", KAREN_V2_MED),
    DspCandidate("18_karen_v2_bright.mp3", KAREN_V2_BRIGHT),
    DspCandidate("19_karen_v2_10like.mp3", KAREN_V2_10LIKE),
)

KAREN_V2_SHUXIN_MED_PITCH = KarenDspPreset(
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
    pitch_shift_rate=1.03,
    label="Y_shuxin_med_pitch",
)

SHUXIN_PYDUB_CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "20_shuxin_warm_robot_light.mp3",
        XIAOYI_VOICE,
        VOICEOVER_PRESET_WARM_ROBOT_LIGHT,
        "N_warm_light",
        DEFAULT_RATE,
        DEFAULT_PITCH,
    ),
    Candidate(
        "21_shuxin_warm_robot.mp3",
        XIAOYI_VOICE,
        VOICEOVER_PRESET_WARM_ROBOT,
        "O_warm",
        DEFAULT_RATE,
        DEFAULT_PITCH,
    ),
    Candidate(
        "22_shuxin_warm_robot_med.mp3",
        XIAOYI_VOICE,
        VOICEOVER_PRESET_WARM_ROBOT_MED,
        "P_warm_med",
        DEFAULT_RATE,
        DEFAULT_PITCH,
    ),
    Candidate(
        "23_shuxin_warm_robot_22k.mp3",
        XIAOYI_VOICE,
        VOICEOVER_PRESET_WARM_ROBOT,
        "O_warm_22k",
        DEFAULT_RATE,
        DEFAULT_PITCH,
        export_sample_rate=SHUXIN_REAL_SAMPLE_RATE,
    ),
)

SHUXIN_DSP_CANDIDATES: tuple[DspCandidate, ...] = (
    DspCandidate("24_shuxin_dsp_mild.mp3", KAREN_V2_SHUXIN_MILD),
    DspCandidate("25_shuxin_dsp_med.mp3", KAREN_V2_SHUXIN_MED),
    DspCandidate("26_shuxin_dsp_warm.mp3", KAREN_V2_SHUXIN_WARM),
    DspCandidate("27_shuxin_dsp_med_pitch.mp3", KAREN_V2_SHUXIN_MED_PITCH),
)

SHUXIN_FFMPEG_CANDIDATES: tuple[FfmpegCandidate, ...] = (
    FfmpegCandidate(
        "28_shuxin_ring_eq_mild.mp3",
        "highpass=f=280,lowpass=f=3800,tremolo=f=24:d=0.20,"
        "aecho=0.8:0.85:12:0.20,acrusher=bits=10:mix=0.14,"
        "equalizer=f=2500:t=q:w=1:g=3,volume=1.08",
        "Q_ring_eq",
    ),
    FfmpegCandidate(
        "29_shuxin_pitch_compress.mp3",
        f"asetrate={EDGE_SAMPLE_RATE}*1.025,aresample={EDGE_SAMPLE_RATE},"
        "highpass=f=270,lowpass=f=4000,"
        "acompressor=threshold=-22dB:ratio=3:attack=5:release=80,"
        "tremolo=f=20:d=0.16,acrusher=bits=10:mix=0.12,volume=1.08",
        "R_pitch_soft",
    ),
    FfmpegCandidate(
        "30_shuxin_ring_eq_22k.mp3",
        "highpass=f=280,lowpass=f=3800,tremolo=f=24:d=0.20,"
        "aecho=0.8:0.85:12:0.20,acrusher=bits=10:mix=0.14,"
        f"equalizer=f=2500:t=q:w=1:g=3,aresample={SHUXIN_REAL_SAMPLE_RATE},volume=1.08",
        "Q_ring_22k",
    ),
    FfmpegCandidate(
        "31_shuxin_robot_med.mp3",
        f"asetrate={EDGE_SAMPLE_RATE}*1.03,aresample={EDGE_SAMPLE_RATE},"
        "highpass=f=280,lowpass=f=3600,"
        "acompressor=threshold=-24dB:ratio=3.5:attack=5:release=80,"
        "tremolo=f=26:d=0.20,aecho=0.8:0.85:14:0.22,"
        "acrusher=bits=10:mix=0.16,equalizer=f=2200:t=q:w=1:g=2.5,volume=1.10",
        "S_robot_med",
    ),
    FfmpegCandidate(
        "32_shuxin_tremolo_presence.mp3",
        f"asetrate={EDGE_SAMPLE_RATE}*1.02,aresample={EDGE_SAMPLE_RATE},"
        "highpass=f=260,lowpass=f=4100,"
        "tremolo=f=90:d=0.22,aecho=0.8:0.85:13:0.18,"
        "acrusher=bits=11:mix=0.10,"
        "equalizer=f=2800:t=q:w=1:g=3.5,acompressor=threshold=-20dB:ratio=2.5,volume=1.08",
        "T_tremolo",
    ),
)

SHUXIN_HYBRID_CANDIDATES: tuple[HybridCandidate, ...] = (
    HybridCandidate(
        "33_shuxin_hybrid_eq.mp3",
        VOICEOVER_PRESET_WARM_ROBOT,
        "equalizer=f=2400:t=q:w=1:g=2.5,tremolo=f=18:d=0.12,volume=1.05",
        "U_hybrid_eq",
    ),
    HybridCandidate(
        "34_shuxin_hybrid_compress.mp3",
        VOICEOVER_PRESET_WARM_ROBOT_MED,
        "acompressor=threshold=-22dB:ratio=3:attack=5:release=80,"
        "equalizer=f=2600:t=q:w=1:g=2,volume=1.06",
        "V_hybrid_comp",
    ),
    HybridCandidate(
        "35_shuxin_hybrid_22k.mp3",
        VOICEOVER_PRESET_WARM_ROBOT,
        f"equalizer=f=2400:t=q:w=1:g=2,aresample={SHUXIN_REAL_SAMPLE_RATE},volume=1.05",
        "W_hybrid_22k",
    ),
)

SHUXIN_BATCH_CANDIDATES: tuple[DspCandidate, ...] = (
    DSP_REFINE_CANDIDATES + SHUXIN_DSP_CANDIDATES
)


async def _synthesize_edge_raw(
    *,
    voice: str,
    rate: str,
    pitch: str,
    text: str,
    tmp: Path,
) -> None:
    config = ProviderConfig(
        voice=voice,
        rate=rate,
        pitch=pitch,
        effect="none",
    )
    provider = EdgeTTSProvider(config)
    await provider.synthesize(text, tmp)


def _apply_ffmpeg_af(src: Path, dest: Path, af: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for FFmpeg voiceover candidates")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(src),
            "-af",
            af,
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "48k",
            str(dest),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _export_mp3(audio, out_path: Path, *, sample_rate: int | None = None) -> None:
    if sample_rate is not None and audio.frame_rate != sample_rate:
        audio = audio.set_frame_rate(sample_rate)
    audio.export(out_path, format="mp3", bitrate="48k")


async def _synthesize_one(candidate: Candidate, out_path: Path, text: str) -> None:
    tmp = out_path.with_suffix(".raw.mp3")
    await _synthesize_edge_raw(
        voice=candidate.voice,
        rate=candidate.rate,
        pitch=candidate.pitch,
        text=text,
        tmp=tmp,
    )

    from pydub import AudioSegment

    audio = AudioSegment.from_file(tmp)
    audio = apply_karen_voice(audio, preset_override=candidate.preset)
    _export_mp3(audio, out_path, sample_rate=candidate.export_sample_rate)
    tmp.unlink(missing_ok=True)


async def _synthesize_dsp_one(candidate: DspCandidate, out_path: Path, text: str) -> None:
    tmp = out_path.with_suffix(".raw.mp3")
    await _synthesize_edge_raw(
        voice=candidate.voice,
        rate=candidate.rate,
        pitch=candidate.pitch,
        text=text,
        tmp=tmp,
    )
    from pydub import AudioSegment

    audio = AudioSegment.from_file(tmp)
    audio = apply_karen_dsp(audio, preset=candidate.preset)
    _export_mp3(audio, out_path)
    tmp.unlink(missing_ok=True)


async def _synthesize_ffmpeg_one(candidate: FfmpegCandidate, out_path: Path, text: str) -> None:
    tmp = out_path.with_suffix(".raw.mp3")
    await _synthesize_edge_raw(
        voice=candidate.voice,
        rate=candidate.rate,
        pitch=candidate.pitch,
        text=text,
        tmp=tmp,
    )
    _apply_ffmpeg_af(tmp, out_path, candidate.af_filter)
    tmp.unlink(missing_ok=True)


async def _synthesize_hybrid_one(candidate: HybridCandidate, out_path: Path, text: str) -> None:
    tmp_raw = out_path.with_suffix(".raw.mp3")
    tmp_fx = out_path.with_suffix(".fx.wav")
    await _synthesize_edge_raw(
        voice=candidate.voice,
        rate=candidate.rate,
        pitch=candidate.pitch,
        text=text,
        tmp=tmp_raw,
    )

    from pydub import AudioSegment

    audio = AudioSegment.from_file(tmp_raw)
    audio = apply_karen_voice(audio, preset_override=candidate.preset)
    audio.export(tmp_fx, format="wav")
    tmp_raw.unlink(missing_ok=True)

    _apply_ffmpeg_af(tmp_fx, out_path, candidate.af_filter)
    tmp_fx.unlink(missing_ok=True)


def _append_candidate_table(
    lines: list[str],
    items: tuple[Candidate, ...],
) -> None:
    for item in items:
        sr_note = f" → {item.export_sample_rate}Hz" if item.export_sample_rate else ""
        lines.append(
            f"| `{item.filename}` | {item.voice} | {item.preset_label}{sr_note} | "
            f"{item.rate} | {item.pitch} |"
        )


def _append_dsp_table(lines: list[str], items: tuple[DspCandidate, ...]) -> None:
    for item in items:
        lines.append(
            f"| `{item.filename}` | {item.voice} | {item.preset.label} | "
            f"{item.rate} | {item.pitch} |"
        )


def _append_ffmpeg_table(lines: list[str], items: tuple[FfmpegCandidate, ...]) -> None:
    for item in items:
        lines.append(
            f"| `{item.filename}` | {item.voice} | {item.preset_label} | "
            f"{item.rate} | {item.pitch} | `{item.af_filter}` |"
        )


def _append_hybrid_table(lines: list[str], items: tuple[HybridCandidate, ...]) -> None:
    for item in items:
        lines.append(
            f"| `{item.filename}` | {item.voice} | {item.preset_label} | "
            f"{item.rate} | {item.pitch} | `{item.af_filter}` |"
        )


def _write_readme(out_dir: Path, text: str, *, include_shuxin: bool = True) -> None:
    lines = [
        "# Voiceover 候选试听",
        "",
        "听感参考：`outputs/voiceover-candidates/shuxin_real.mp3`（外部剪辑样本）",
        f"合成文案：{text}",
        "",
        "请逐条试听，回复编号（如 `25` 或 `31`）选定后会把参数写回默认 preset。",
        "",
        "## 01–05 pydub KarenPreset",
        "",
        "| 文件 | 女声 | FX | rate | pitch |",
        "|------|------|-----|------|-------|",
    ]
    _append_candidate_table(lines, CANDIDATES)
    lines.extend(
        [
            "",
            "## 06–08 FFmpeg 电话带（Xiaoyi）",
            "",
            "| 文件 | 女声 | FX | rate | pitch | `-af` |",
            "|------|------|-----|------|-------|-------|",
        ]
    )
    _append_ffmpeg_table(lines, FFMPEG_PHONE_CANDIDATES)
    lines.extend(
        [
            "",
            "## 09–15 机器人女声（环调 + 相位机器化 + 短延迟，无 chorus）",
            "",
            "试听顺序建议：可懂度 `09` → `15` → `12` → `10`；机器感 `11` → `13` → `14`。",
            "",
            "| 文件 | 女声 | FX | rate | pitch | `-af` |",
            "|------|------|-----|------|-------|-------|",
        ]
    )
    _append_ffmpeg_table(lines, FFMPEG_ROBOT_CANDIDATES)

    if include_shuxin:
        lines.extend(
            [
                "",
                "## 16–19 Karen DSP v2（音调平坦化 + 环调干湿 + 梳状 + EQ）",
                "",
                "链：pitch flatten → ring @80–120Hz wet/dry → comb 15ms → EQ 2–4kHz。无 chorus、无 afftfilt。",
                "",
                "| 文件 | 女声 | FX | rate | pitch |",
                "|------|------|-----|------|-------|",
            ]
        )
        _append_dsp_table(lines, DSP_REFINE_CANDIDATES)
        lines.extend(
            [
                "",
                "## 20–23 shuxin_real pydub 暖色机器人（无 vocoder）",
                "",
                "| 文件 | 女声 | FX | rate | pitch |",
                "|------|------|-----|------|-------|",
            ]
        )
        _append_candidate_table(lines, SHUXIN_PYDUB_CANDIDATES)
        lines.extend(
            [
                "",
                "## 24–27 shuxin_real Karen DSP 变体",
                "",
                "试听建议（对齐 shuxin_real）：**先听 24–27 → 28–32 → 20–23 → 对比 15**。",
                "",
                "| 文件 | 女声 | FX | rate | pitch |",
                "|------|------|-----|------|-------|",
            ]
        )
        _append_dsp_table(lines, SHUXIN_DSP_CANDIDATES)
        lines.extend(
            [
                "",
                "## 28–32 shuxin_real FFmpeg（无 afftfilt，中等机器感）",
                "",
                "| 文件 | 女声 | FX | rate | pitch | `-af` |",
                "|------|------|-----|------|-------|-------|",
            ]
        )
        _append_ffmpeg_table(lines, SHUXIN_FFMPEG_CANDIDATES)
        lines.extend(
            [
                "",
                "## 33–35 shuxin_real 混合链（pydub warm robot + 轻 FFmpeg）",
                "",
                "| 文件 | 女声 | FX | rate | pitch | post `-af` |",
                "|------|------|-----|------|-------|------------|",
            ]
        )
        _append_hybrid_table(lines, SHUXIN_HYBRID_CANDIDATES)
        lines.extend(
            [
                "",
                "## 36 短文案预览（约 5s，贴近 shuxin_real 时长）",
                "",
                "使用 `KAREN_V2_SHUXIN_MED` preset + 短文案，便于与参考样本直接对比。",
                "",
                "| 文件 | 女声 | FX | 文案 |",
                "|------|------|-----|------|",
                f"| `36_shuxin_real_text.mp3` | {XIAOYI_VOICE} | W_shuxin_med | {SHORT_TEXT} |",
            ]
        )

    lines.extend(
        [
            "",
            "生成命令：",
            "```bash",
            "# shuxin_real 批次（16–19 + 20–36）",
            "docker exec shuxin-voice-demo-pg env PYTHONPATH=/app/src \\",
            "  python /app/scripts/generate_voiceover_candidates.py --shuxin-batch",
            "",
            "# 若 DSP 内存不足，可分两步：",
            "docker exec shuxin-voice-demo-pg env PYTHONPATH=/app/src \\",
            "  python /app/scripts/generate_voiceover_candidates.py --shuxin-batch --shuxin-skip-dsp",
            "docker exec shuxin-voice-demo-pg env PYTHONPATH=/app/src \\",
            "  python /app/scripts/generate_voiceover_candidates.py --shuxin-dsp-only",
            "",
            "# pydub 01–05 + FFmpeg 06–15",
            "docker exec shuxin-voice-demo-pg env PYTHONPATH=/app/src \\",
            "  python /app/scripts/generate_voiceover_candidates.py",
            "",
            "# 仅 Karen DSP v2（16–19）",
            "docker exec shuxin-voice-demo-pg env PYTHONPATH=/app/src \\",
            "  python /app/scripts/generate_voiceover_candidates.py --refine-only",
            "",
            "# 仅机器人女声 09–15",
            "docker exec shuxin-voice-demo-pg env PYTHONPATH=/app/src \\",
            "  python /app/scripts/generate_voiceover_candidates.py --robot-only",
            "",
            "# 全部 FFmpeg 06–15",
            "docker exec shuxin-voice-demo-pg env PYTHONPATH=/app/src \\",
            "  python /app/scripts/generate_voiceover_candidates.py --ffmpeg-only",
            "```",
        ]
    )
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _run_shuxin_batch(
    out_dir: Path,
    text: str,
    *,
    skip_dsp: bool = False,
    dsp_only: bool = False,
) -> None:
    if not dsp_only:
        for item in SHUXIN_PYDUB_CANDIDATES:
            dest = out_dir / item.filename
            print(f"Generating {dest.name} ...", flush=True)
            await _synthesize_one(item, dest, text)

        for item in SHUXIN_FFMPEG_CANDIDATES:
            dest = out_dir / item.filename
            print(f"Generating {dest.name} ...", flush=True)
            await _synthesize_ffmpeg_one(item, dest, text)

        for item in SHUXIN_HYBRID_CANDIDATES:
            dest = out_dir / item.filename
            print(f"Generating {dest.name} ...", flush=True)
            await _synthesize_hybrid_one(item, dest, text)

    if skip_dsp:
        return

    for item in SHUXIN_BATCH_CANDIDATES:
        dest = out_dir / item.filename
        print(f"Generating {dest.name} ...", flush=True)
        await _synthesize_dsp_one(item, dest, text)

    dest = out_dir / "36_shuxin_real_text.mp3"
    print(f"Generating {dest.name} ...", flush=True)
    await _synthesize_dsp_one(
        DspCandidate("36_shuxin_real_text.mp3", KAREN_V2_SHUXIN_MED),
        dest,
        SHORT_TEXT,
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ffmpeg-only",
        action="store_true",
        help="Skip pydub 01–05; generate FFmpeg 06–15",
    )
    parser.add_argument(
        "--robot-only",
        action="store_true",
        help="Only generate robot-voice FFmpeg 09–15",
    )
    parser.add_argument(
        "--refine-only",
        action="store_true",
        help="Only generate Karen DSP v2 candidates 16–19",
    )
    parser.add_argument(
        "--shuxin-batch",
        action="store_true",
        help="Generate shuxin_real batch: 16–19 + 20–36",
    )
    parser.add_argument(
        "--shuxin-skip-dsp",
        action="store_true",
        help="With --shuxin-batch: skip Karen DSP items (16–19, 24–27, 36)",
    )
    parser.add_argument(
        "--shuxin-dsp-only",
        action="store_true",
        help="Only generate Karen DSP shuxin items (16–19, 24–27, 36)",
    )
    parser.add_argument(
        "text",
        nargs="*",
        help="Custom TTS text (default: built-in companion script)",
    )
    args = parser.parse_args()
    text = " ".join(args.text).strip() or DEFAULT_TEXT

    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.shuxin_batch or args.shuxin_dsp_only:
        await _run_shuxin_batch(
            out_dir,
            text,
            skip_dsp=args.shuxin_skip_dsp and not args.shuxin_dsp_only,
            dsp_only=args.shuxin_dsp_only,
        )
        _write_readme(out_dir, text, include_shuxin=True)
        print(f"Done. Files in {out_dir}")
        return 0

    skip_pydub = args.ffmpeg_only or args.robot_only or args.refine_only

    if args.refine_only:
        for item in DSP_REFINE_CANDIDATES:
            dest = out_dir / item.filename
            print(f"Generating {dest.name} ...", flush=True)
            await _synthesize_dsp_one(item, dest, text)
    else:
        if args.robot_only:
            ffmpeg_items = FFMPEG_ROBOT_CANDIDATES
        else:
            ffmpeg_items = FFMPEG_CANDIDATES

        if not skip_pydub:
            for item in CANDIDATES:
                dest = out_dir / item.filename
                print(f"Generating {dest.name} ...", flush=True)
                await _synthesize_one(item, dest, text)

        for item in ffmpeg_items:
            dest = out_dir / item.filename
            print(f"Generating {dest.name} ...", flush=True)
            await _synthesize_ffmpeg_one(item, dest, text)

    _write_readme(out_dir, text, include_shuxin=True)
    print(f"Done. Files in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
