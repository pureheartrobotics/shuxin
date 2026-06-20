#!/usr/bin/env python3
"""Batch-generate device flash prompt audio (TTS -> Opus) for firmware UI strings."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuxin.voice.agents import AgentRecord, DEFAULT_AGENT_ID  # noqa: E402
from shuxin.voice.opus_codec import (  # noqa: E402
    DEFAULT_FRAME_DURATION_MS,
    FLASH_OPUS_BITRATE,
    FLASH_SAMPLE_RATE,
    opus_available,
    transcode_mp3_to_opus_frames,
)
from shuxin.voice.tts_config import create_tts_provider_from_agent  # noqa: E402

SILENCE_FILTER = "silenceremove=stop_periods=-1:stop_duration=0.3:stop_threshold=-40dB"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate device prompt Opus assets from strings JSON")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "device_assets" / "strings.zh-CN.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "device_assets" / "zh-CN",
    )
    parser.add_argument("--agent-id", default=os.environ.get("SHUXIN_DEVICE_ASSETS_AGENT_ID", DEFAULT_AGENT_ID))
    parser.add_argument("--voice-type", default=os.environ.get("VOLCENGINE_TTS_VOICE_TYPE", ""))
    parser.add_argument(
        "--format",
        choices=("ogg", "opus_bin", "both"),
        default="both",
        help="Output format (default: both)",
    )
    parser.add_argument(
        "--flash-sample-rate",
        type=int,
        default=FLASH_SAMPLE_RATE,
        help="Flash prompt sample rate in Hz (default: 16000, aligned with xiaozhi-esp32)",
    )
    parser.add_argument(
        "--flash-bitrate",
        default="16k",
        help="Flash Opus bitrate for ffmpeg OGG and opuslib encoder (default: 16k)",
    )
    parser.add_argument("--trim-silence", dest="trim_silence", action="store_true", default=True)
    parser.add_argument("--no-trim-silence", dest="trim_silence", action="store_false")
    parser.add_argument("--keep-tmp", action="store_true", help="Keep TTS intermediate MP3 files")
    parser.add_argument(
        "--reencode-existing",
        action="store_true",
        help="Skip TTS; re-encode existing {key}.ogg in --out (offline flash resize)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keys", default="", help="Comma-separated subset of keys to generate")
    return parser.parse_args()


def _parse_bitrate(value: str) -> int:
    normalized = value.strip().lower()
    match = re.fullmatch(r"(\d+)(k)?", normalized)
    if not match:
        raise ValueError(f"Invalid bitrate: {value!r}")
    amount = int(match.group(1))
    return amount * 1000 if match.group(2) else amount


def _load_strings(path: Path) -> tuple[str, dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    language = str((payload.get("language") or {}).get("type") or "zh-CN")
    strings = payload.get("strings")
    if not isinstance(strings, dict):
        raise ValueError(f"Missing strings object in {path}")
    normalized = {str(k): str(v) for k, v in strings.items()}
    return language, normalized


def _merge_manifest_entries(
    new_manifest: dict,
    existing_manifest: dict,
    strings: dict[str, str],
) -> dict:
    """Keep untouched entries when regenerating a subset with --keys."""
    merged = dict(new_manifest)
    by_key: dict[str, dict] = {}
    for entry in existing_manifest.get("entries") or []:
        key = str(entry.get("key") or "")
        if key:
            by_key[key] = dict(entry)
    for entry in new_manifest.get("entries") or []:
        key = str(entry.get("key") or "")
        if key:
            by_key[key] = dict(entry)

    merged["entries"] = [by_key[key] for key in strings if key in by_key]

    skipped_by_key: dict[str, dict] = {}
    for entry in existing_manifest.get("skipped") or []:
        key = str(entry.get("key") or "")
        if key:
            skipped_by_key[key] = dict(entry)
    for entry in new_manifest.get("skipped") or []:
        key = str(entry.get("key") or "")
        if key:
            skipped_by_key[key] = dict(entry)
    if skipped_by_key:
        merged["skipped"] = [skipped_by_key[key] for key in strings if key in skipped_by_key]
    return merged


def _write_length_prefixed_opus_bin(frames: list[bytes], path: Path) -> None:
    """Raw Opus packets: repeated [uint16_be length][packet bytes]."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for packet in frames:
            if not packet:
                continue
            if len(packet) > 0xFFFF:
                raise ValueError(f"Opus packet too large: {len(packet)} bytes")
            handle.write(struct.pack(">H", len(packet)))
            handle.write(packet)


def _preprocess_mp3(
    mp3_path: Path,
    *,
    trim_silence: bool,
    work_dir: Path,
) -> Path:
    if not trim_silence:
        return mp3_path
    trimmed = work_dir / f"{mp3_path.stem}.trim.mp3"
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(mp3_path),
        "-af",
        SILENCE_FILTER,
        "-c:a",
        "libmp3lame",
        str(trimmed),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return trimmed


def _audio_to_ogg_opus(
    source_path: Path,
    ogg_path: Path,
    *,
    sample_rate: int,
    bitrate_bps: int,
    frame_duration_ms: int,
    trim_silence: bool,
) -> None:
    ogg_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_path),
    ]
    if trim_silence:
        cmd.extend(["-af", SILENCE_FILTER])
    cmd.extend(
        [
            "-c:a",
            "libopus",
            "-b:a",
            f"{max(1, bitrate_bps // 1000)}k",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            str(ogg_path),
        ]
    )
    subprocess.run(cmd, check=True, capture_output=True)


def _build_agent(agent_id: str, voice_type: str) -> AgentRecord:
    return AgentRecord(
        agent_id=agent_id,
        display_name="Device prompts",
        voice_type=voice_type or os.environ.get("VOLCENGINE_TTS_VOICE_TYPE", ""),
    )


async def _synthesize_one(
    provider,
    text: str,
    mp3_path: Path,
) -> None:
    await provider.synthesize(text, mp3_path)


def _reencode_existing(
    *,
    key: str,
    out_dir: Path,
    work: Path,
    output_format: str,
    flash_sample_rate: int,
    flash_bitrate_bps: int,
    trim_silence: bool,
) -> dict:
    source_ogg = out_dir / f"{key}.ogg"
    if not source_ogg.exists():
        raise FileNotFoundError(f"Missing source OGG for reencode: {source_ogg}")

    want_ogg = output_format in ("ogg", "both")
    want_bin = output_format in ("opus_bin", "both")
    ogg_path = out_dir / f"{key}.ogg"
    bin_path = out_dir / f"{key}.opus.bin"
    work_ogg = work / f"{key}.src.ogg"
    shutil.copy2(source_ogg, work_ogg)

    entry_files: dict[str, str] = {}
    opus_frame_count = 0

    if want_ogg:
        _audio_to_ogg_opus(
            work_ogg,
            ogg_path,
            sample_rate=flash_sample_rate,
            bitrate_bps=flash_bitrate_bps,
            frame_duration_ms=DEFAULT_FRAME_DURATION_MS,
            trim_silence=trim_silence,
        )
        entry_files["ogg"] = ogg_path.name
        bin_source = ogg_path
    else:
        bin_source = work_ogg

    if want_bin:
        frames = transcode_mp3_to_opus_frames(
            bin_source,
            sample_rate=flash_sample_rate,
            frame_duration_ms=DEFAULT_FRAME_DURATION_MS,
            bitrate=flash_bitrate_bps,
        )
        if not frames:
            raise RuntimeError(f"No Opus frames generated for {key}")
        _write_length_prefixed_opus_bin(frames, bin_path)
        entry_files["opus_bin"] = bin_path.name
        opus_frame_count = len(frames)

    entry: dict = {
        "key": key,
        "files": entry_files,
        "sample_rate": flash_sample_rate,
        "frame_duration_ms": DEFAULT_FRAME_DURATION_MS,
        "reencoded_from": source_ogg.name,
    }
    if opus_frame_count:
        entry["opus_frame_count"] = opus_frame_count
    return entry


async def _generate_all(
    *,
    strings: dict[str, str],
    out_dir: Path,
    agent: AgentRecord,
    dry_run: bool,
    only_keys: set[str] | None,
    output_format: str,
    flash_sample_rate: int,
    flash_bitrate_bps: int,
    trim_silence: bool,
    keep_tmp: bool,
    reencode_existing: bool,
) -> dict:
    if not dry_run and not opus_available():
        raise SystemExit("opuslib_next is required; redeploy Docker or pip install requirements-voice-app.txt")

    entries: list[dict] = []
    skipped: list[dict] = []
    want_ogg = output_format in ("ogg", "both")
    want_bin = output_format in ("opus_bin", "both")

    if dry_run:
        for key, text in strings.items():
            if only_keys and key not in only_keys:
                continue
            if "%" in text:
                skipped.append({"key": key, "text": text, "reason": "contains printf placeholder"})
                continue
            entries.append({"key": key, "text": text, "dry_run": True})
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "profile": "flash",
            "sample_rate": flash_sample_rate,
            "opus_bitrate_bps": flash_bitrate_bps,
            "frame_duration_ms": DEFAULT_FRAME_DURATION_MS,
            "output_format": output_format,
            "entries": entries,
            "skipped": skipped,
        }

    work = out_dir / "_tmp"
    work.mkdir(parents=True, exist_ok=True)
    provider = None if reencode_existing else create_tts_provider_from_agent(agent, output_dir=str(work))

    try:
        for key, text in strings.items():
            if only_keys and key not in only_keys:
                continue
            if "%" in text:
                skipped.append({"key": key, "text": text, "reason": "contains printf placeholder"})
                continue
            if not text.strip():
                skipped.append({"key": key, "text": text, "reason": "empty text"})
                continue

            if reencode_existing:
                print(f"[assets] reencode {key}")
                entry = _reencode_existing(
                    key=key,
                    out_dir=out_dir,
                    work=work,
                    output_format=output_format,
                    flash_sample_rate=flash_sample_rate,
                    flash_bitrate_bps=flash_bitrate_bps,
                    trim_silence=trim_silence,
                )
                entry["text"] = text
                entries.append(entry)
                continue

            mp3_path = work / f"{key}.mp3"
            ogg_path = out_dir / f"{key}.ogg"
            bin_path = out_dir / f"{key}.opus.bin"

            print(f"[assets] TTS {key}: {text!r}")
            await _synthesize_one(provider, text.strip(), mp3_path)
            source_mp3 = _preprocess_mp3(mp3_path, trim_silence=trim_silence, work_dir=work)

            entry_files: dict[str, str] = {}
            opus_frame_count = 0

            if want_bin:
                frames = transcode_mp3_to_opus_frames(
                    source_mp3,
                    sample_rate=flash_sample_rate,
                    frame_duration_ms=DEFAULT_FRAME_DURATION_MS,
                    bitrate=flash_bitrate_bps,
                )
                if not frames:
                    raise RuntimeError(f"No Opus frames generated for {key}")
                _write_length_prefixed_opus_bin(frames, bin_path)
                entry_files["opus_bin"] = bin_path.name
                opus_frame_count = len(frames)

            if want_ogg:
                _audio_to_ogg_opus(
                    source_mp3,
                    ogg_path,
                    sample_rate=flash_sample_rate,
                    bitrate_bps=flash_bitrate_bps,
                    frame_duration_ms=DEFAULT_FRAME_DURATION_MS,
                    trim_silence=False,
                )
                entry_files["ogg"] = ogg_path.name

            entry: dict = {
                "key": key,
                "text": text,
                "files": entry_files,
                "sample_rate": flash_sample_rate,
                "frame_duration_ms": DEFAULT_FRAME_DURATION_MS,
            }
            if opus_frame_count:
                entry["opus_frame_count"] = opus_frame_count
            entries.append(entry)
    finally:
        if not keep_tmp:
            shutil.rmtree(work, ignore_errors=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_id": agent.agent_id,
        "voice_type": agent.voice_type,
        "profile": "flash",
        "sample_rate": flash_sample_rate,
        "opus_bitrate_bps": flash_bitrate_bps,
        "frame_duration_ms": DEFAULT_FRAME_DURATION_MS,
        "output_format": output_format,
        "trim_silence": trim_silence,
        "encoding_reference": "xiaozhi-esp32 scripts/mp3_to_ogg.sh",
        "opus_bin_format": "uint16_be_length_prefix + raw_packet",
        "entries": entries,
        "skipped": skipped,
    }


def main() -> int:
    args = _parse_args()
    language, strings = _load_strings(args.input)
    only_keys = {k.strip() for k in args.keys.split(",") if k.strip()} or None
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    flash_bitrate_bps = _parse_bitrate(args.flash_bitrate)

    agent = _build_agent(args.agent_id, args.voice_type)
    manifest = asyncio.run(
        _generate_all(
            strings=strings,
            out_dir=out_dir,
            agent=agent,
            dry_run=args.dry_run,
            only_keys=only_keys,
            output_format=args.format,
            flash_sample_rate=args.flash_sample_rate,
            flash_bitrate_bps=flash_bitrate_bps,
            trim_silence=args.trim_silence,
            keep_tmp=args.keep_tmp,
            reencode_existing=args.reencode_existing,
        )
    )
    manifest["language"] = language
    manifest_path = out_dir / "manifest.json"
    if only_keys and not args.dry_run and manifest_path.exists():
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = _merge_manifest_entries(manifest, existing_manifest, strings)
    if not args.dry_run:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[assets] wrote {len(manifest['entries'])} entries -> {out_dir}")
        print(f"[assets] manifest: {manifest_path}")
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
