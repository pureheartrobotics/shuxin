#!/usr/bin/env python3
"""WebSocket Opus smoke test — simulates hardware uplink/downlink without a device."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuxin.voice.opus_codec import (  # noqa: E402
    DOWNLINK_SAMPLE_RATE,
    extract_opus_packets_from_ogg,
    looks_like_mp3,
    opus_available,
    write_opus_packets_as_wav,
)

try:
    import websockets
except ImportError as exc:  # pragma: no cover
    raise SystemExit("websockets is required (requirements-voice-app.txt)") from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Opus WebSocket voice smoke test")
    parser.add_argument(
        "--url",
        default=os.environ.get("SHUXIN_VOICE_WS_URL", "ws://localhost:8765/ws/voice"),
    )
    parser.add_argument("--device-code", default=os.environ.get("SHUXIN_DEVICE_CODE", "demo-device-001"))
    parser.add_argument(
        "--device-secret",
        default=os.environ.get("SHUXIN_DEVICE_SHARED_SECRET", "dev-device-secret"),
    )
    parser.add_argument("--client-id", default="opus-smoke-client")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "test" / "activation.ogg",
        help="Ogg Opus file; converted to raw 60ms frames for uplink",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "outputs" / "opus-smoke-reply.wav",
        help="Decode downlink Opus frames to WAV for manual listening",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args()


async def run_smoke(args: argparse.Namespace) -> int:
    if not opus_available():
        print("ERROR: opuslib_next not installed. Redeploy Docker (requirements-voice-app.txt).", file=sys.stderr)
        return 2
    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 2

    uplink_frames = extract_opus_packets_from_ogg(args.input)
    if not uplink_frames:
        print("ERROR: no Opus frames extracted from input", file=sys.stderr)
        return 2

    stt_final = ""
    agent_reply = ""
    downlink_packets: list[bytes] = []
    in_tts_sentence = False
    errors: list[str] = []

    hello_payload = {
        "type": "hello",
        "device_code": args.device_code,
        "device_secret": args.device_secret,
        "client_id": args.client_id,
        "audio_params": {
            "format": "opus",
            "sample_rate": 16000,
            "channels": 1,
            "frame_duration": 60,
        },
    }

    print(f"connecting {args.url} ...")
    async with websockets.connect(args.url, open_timeout=10, close_timeout=5) as ws:
        ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=args.timeout))
        print("server ready:", ready)

        await ws.send(json.dumps(hello_payload, ensure_ascii=False))
        hello_ok = json.loads(await asyncio.wait_for(ws.recv(), timeout=args.timeout))
        print("hello ok:", hello_ok)
        if hello_ok.get("type") == "error" or hello_ok.get("state") != "ok":
            print("ERROR: hello failed:", hello_ok, file=sys.stderr)
            return 1
        if hello_ok.get("audio_params", {}).get("format") != "opus":
            print("ERROR: server did not negotiate opus", file=sys.stderr)
            return 1

        await ws.send(json.dumps({"type": "listen", "state": "start"}))
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=args.timeout))
        print("listen:", ack)

        for index, packet in enumerate(uplink_frames, start=1):
            await ws.send(packet)
            if index % 20 == 0:
                print(f"  uplink frame {index}/{len(uplink_frames)}")

        await ws.send(json.dumps({"type": "listen", "state": "stop"}))
        print("listen stop sent, waiting for pipeline ...")

        while True:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=args.timeout)
            except asyncio.TimeoutError:
                print("ERROR: timed out waiting for server messages", file=sys.stderr)
                break

            if isinstance(message, bytes):
                if in_tts_sentence:
                    if looks_like_mp3(message):
                        errors.append("downlink binary looks like mp3, expected opus")
                    downlink_packets.append(message)
                continue

            data = json.loads(message)
            msg_type = data.get("type")
            state = data.get("state")
            print("event:", data)

            if msg_type == "error":
                errors.append(str(data.get("message") or data))
            elif msg_type == "stt" and state == "final":
                stt_final = str(data.get("text") or "").strip()
            elif msg_type == "agent" and state == "reply":
                agent_reply = str(data.get("text") or "").strip()
            elif msg_type == "tts" and state == "sentence_start":
                in_tts_sentence = True
            elif msg_type == "tts" and state == "sentence_stop":
                in_tts_sentence = False
            elif msg_type == "tts" and state == "stop":
                break

    if errors:
        for item in errors:
            print("ERROR:", item, file=sys.stderr)
        return 1
    if not stt_final:
        print("ERROR: no stt/final text", file=sys.stderr)
        return 1
    if not agent_reply:
        print("ERROR: no agent/reply text", file=sys.stderr)
        return 1
    if not downlink_packets:
        print("ERROR: no downlink opus frames received", file=sys.stderr)
        return 1

    max_packet_bytes = max(len(packet) for packet in downlink_packets)
    if max_packet_bytes > 4096:
        print(
            f"ERROR: downlink packet too large: {max_packet_bytes} bytes (max 4096)",
            file=sys.stderr,
        )
        return 1

    write_opus_packets_as_wav(downlink_packets, args.output, sample_rate=DOWNLINK_SAMPLE_RATE)
    print(f"STT: {stt_final!r}")
    print(f"Agent: {agent_reply!r}")
    print(f"Downlink opus frames: {len(downlink_packets)}")
    print(f"Max downlink packet bytes: {max_packet_bytes}")
    print(f"WAV written: {args.output}")
    return 0


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(run_smoke(args)))


if __name__ == "__main__":
    main()
