from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from shuxin.voice.config import DeviceConfigProvider
from shuxin.voice.service import VoiceService
from shuxin.voice.session import VoiceSessionRunner
from shuxin.voice.transport import FileAudioOutputTransport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChuXin voice demo CLI")
    parser.add_argument(
        "--device-config",
        default=None,
        help="Path to devices.yaml. Defaults to VOICE_DEVICE_CONFIG or data/devices.yaml.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    stt = subparsers.add_parser("stt", help="Transcribe an audio file")
    stt.add_argument("audio", type=Path)
    stt.add_argument("--device-id", default=None)

    tts = subparsers.add_parser("tts", help="Synthesize text into an audio file")
    tts.add_argument("text")
    tts.add_argument("--device-id", default=None)
    tts.add_argument("--out", type=Path, default=Path("outputs/tts.mp3"))

    chat_audio = subparsers.add_parser(
        "chat-audio",
        help="Transcribe audio, call the Agent, and synthesize the reply",
    )
    chat_audio.add_argument("audio", type=Path)
    chat_audio.add_argument("--device-id", default=None)
    chat_audio.add_argument("--out", type=Path, default=Path("outputs/reply.mp3"))

    session = subparsers.add_parser(
        "session",
        help="Run a no-hardware voice session loop",
    )
    session.add_argument("--device-id", default=None)
    session.add_argument("--out-dir", type=Path, default=Path("outputs/session"))
    session.add_argument(
        "--welcome-text",
        default="你好，我是初心，我们开始聊天吧。",
    )
    session.add_argument(
        "--play",
        action="store_true",
        help="Play generated audio with ffplay when available.",
    )
    session.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Maximum user turns. Use 0 to only generate init.mp3.",
    )

    return parser


async def run(args: argparse.Namespace) -> int:
    service = VoiceService(DeviceConfigProvider(args.device_config))

    if args.command == "stt":
        text = await service.transcribe(args.audio, args.device_id)
        print(text)
        return 0

    if args.command == "tts":
        output = await service.synthesize(args.text, args.out, args.device_id)
        print(output)
        return 0

    if args.command == "chat-audio":
        text, reply, output = await service.chat_audio(
            args.audio,
            args.out,
            args.device_id,
        )
        print(f"USER_TEXT={text}")
        print(f"AGENT_REPLY={reply}")
        print(f"VOICE_OUTPUT={output}")
        return 0

    if args.command == "session":
        runner = VoiceSessionRunner(
            service=service,
            device_id=args.device_id,
            out_dir=args.out_dir,
            welcome_text=args.welcome_text,
            output_transport=FileAudioOutputTransport(play=args.play),
            max_turns=args.max_turns,
        )
        await runner.run()
        return 0

    raise ValueError(f"Unknown command: {args.command}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
