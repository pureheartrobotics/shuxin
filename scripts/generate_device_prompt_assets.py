#!/usr/bin/env python3
"""Batch-generate device flash prompt audio (TTS -> Opus) for firmware UI strings."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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
    DOWNLINK_SAMPLE_RATE,
    opus_available,
    transcode_mp3_to_opus_frames,
)
from shuxin.voice.tts_config import create_tts_provider_from_agent  # noqa: E402


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
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keys", default="", help="Comma-separated subset of keys to generate")
    return parser.parse_args()


def _load_strings(path: Path) -> tuple[str, dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    language = str((payload.get("language") or {}).get("type") or "zh-CN")
    strings = payload.get("strings")
    if not isinstance(strings, dict):
        raise ValueError(f"Missing strings object in {path}")
    normalized = {str(k): str(v) for k, v in strings.items()}
    return language, normalized


def _write_length_prefixed_opus_bin(frames: list[bytes], path: Path) -> None:
    """Raw Opus packets: repeated [uint16_be length][packet bytes] (WebSocket wire compatible)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for packet in frames:
            if not packet:
                continue
            if len(packet) > 0xFFFF:
                raise ValueError(f"Opus packet too large: {len(packet)} bytes")
            handle.write(struct.pack(">H", len(packet)))
            handle.write(packet)


def _mp3_to_ogg_opus(mp3_path: Path, ogg_path: Path, *, sample_rate: int) -> None:
    ogg_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(mp3_path),
        "-c:a",
        "libopus",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        str(ogg_path),
    ]
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


async def _generate_all(
    *,
    strings: dict[str, str],
    out_dir: Path,
    agent: AgentRecord,
    dry_run: bool,
    only_keys: set[str] | None,
) -> dict:
    if not dry_run and not opus_available():
        raise SystemExit("opuslib_next is required; redeploy Docker or pip install requirements-voice-app.txt")

    entries: list[dict] = []
    skipped: list[dict] = []

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
            "sample_rate": DOWNLINK_SAMPLE_RATE,
            "frame_duration_ms": DEFAULT_FRAME_DURATION_MS,
            "entries": entries,
            "skipped": skipped,
        }

    provider = create_tts_provider_from_agent(agent, output_dir=str(out_dir / "_tmp"))
    work = out_dir / "_tmp"
    work.mkdir(parents=True, exist_ok=True)

    for key, text in strings.items():
        if only_keys and key not in only_keys:
            continue
        if "%" in text:
            skipped.append({"key": key, "text": text, "reason": "contains printf placeholder"})
            continue
        if not text.strip():
            skipped.append({"key": key, "text": text, "reason": "empty text"})
            continue

        mp3_path = work / f"{key}.mp3"
        ogg_path = out_dir / f"{key}.ogg"
        bin_path = out_dir / f"{key}.opus.bin"

        print(f"[assets] TTS {key}: {text!r}")
        await _synthesize_one(provider, text.strip(), mp3_path)
        frames = transcode_mp3_to_opus_frames(
            mp3_path,
            sample_rate=DOWNLINK_SAMPLE_RATE,
            frame_duration_ms=DEFAULT_FRAME_DURATION_MS,
        )
        if not frames:
            raise RuntimeError(f"No Opus frames generated for {key}")

        _mp3_to_ogg_opus(mp3_path, ogg_path, sample_rate=DOWNLINK_SAMPLE_RATE)
        _write_length_prefixed_opus_bin(frames, bin_path)

        entries.append(
            {
                "key": key,
                "text": text,
                "files": {
                    "ogg": ogg_path.name,
                    "opus_bin": bin_path.name,
                },
                "opus_frame_count": len(frames),
                "sample_rate": DOWNLINK_SAMPLE_RATE,
                "frame_duration_ms": DEFAULT_FRAME_DURATION_MS,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_id": agent.agent_id,
        "voice_type": agent.voice_type,
        "sample_rate": DOWNLINK_SAMPLE_RATE,
        "frame_duration_ms": DEFAULT_FRAME_DURATION_MS,
        "opus_bin_format": "uint16_be_length_prefix + raw_packet (matches WebSocket downlink packets)",
        "entries": entries,
        "skipped": skipped,
    }


def main() -> int:
    args = _parse_args()
    language, strings = _load_strings(args.input)
    only_keys = {k.strip() for k in args.keys.split(",") if k.strip()} or None
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    agent = _build_agent(args.agent_id, args.voice_type)
    manifest = asyncio.run(
        _generate_all(
            strings=strings,
            out_dir=out_dir,
            agent=agent,
            dry_run=args.dry_run,
            only_keys=only_keys,
        )
    )
    manifest["language"] = language
    manifest_path = out_dir / "manifest.json"
    if not args.dry_run:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[assets] wrote {len(manifest['entries'])} entries -> {out_dir}")
        print(f"[assets] manifest: {manifest_path}")
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
