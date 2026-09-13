"""RK3566 设备端入口。

开发机（无麦）可用 WAV 走一轮协议：
  python apps/rk3566/run.py --input samples/demo.wav --output outputs/rk3566-reply.wav --no-play

只测口令解析（不连云、不动真车）：
  python apps/rk3566/run.py --say 往前走一点

板上实时采集并语音控车：
  python apps/rk3566/run.py --live --seconds 4 --loop
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from shuxin_rk3566.audio import (  # noqa: E402
    AlsaCapture,
    AlsaPlayback,
    decode_and_play,
    encode_pcm_to_opus,
    pcm_from_wav,
    require_opus,
)
from shuxin_rk3566.chassis import MotionController, build_chassis  # noqa: E402
from shuxin_rk3566.client import Rk3566VoiceClient  # noqa: E402
from shuxin_rk3566.config import DeviceRuntimeConfig  # noqa: E402
from shuxin_rk3566.motion_intent import parse_motion_intent  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RK3566 ChuXin voice device client")
    parser.add_argument("--url", default=None, help="ws://host:8765/ws/voice")
    parser.add_argument("--device-code", default=None)
    parser.add_argument("--device-secret", default=None)
    parser.add_argument("--client-id", default=None)
    parser.add_argument("--input", type=Path, default=None, help="16 kHz mono wav for one turn")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "rk3566-reply.wav")
    parser.add_argument("--live", action="store_true", help="capture from ALSA arecord")
    parser.add_argument("--seconds", type=float, default=4.0, help="live capture length")
    parser.add_argument("--alsa-device", default="default")
    parser.add_argument("--no-play", action="store_true", help="do not call aplay")
    parser.add_argument("--say", default=None, help="parse a motion phrase without connecting")
    parser.add_argument(
        "--chassis",
        default=None,
        help="mock (default) or cmd; cmd uses --chassis-cmd / SHUXIN_CHASSIS_CMD",
    )
    parser.add_argument(
        "--chassis-cmd",
        default=None,
        help="external motor command, e.g. '/opt/car/drive {action} {duration} {speed}'",
    )
    parser.add_argument("--loop", action="store_true", help="keep listening after each turn")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def _log_motion(command) -> None:
    if command is None:
        logging.info("motion: (none)")
        return
    logging.info(
        "motion: %s duration=%.2fs speed=%.2f",
        command.action,
        command.duration_s,
        command.speed,
    )


async def _one_turn(
    *,
    args: argparse.Namespace,
    client: Rk3566VoiceClient,
    playback,
) -> int:
    if args.live:
        capture = AlsaCapture(device=args.alsa_device)
        pcm = await capture.capture_seconds(args.seconds)
    elif args.input is not None:
        pcm = pcm_from_wav(args.input)
    else:
        raise SystemExit("pass --input <wav>, --live, or --say")

    packets = encode_pcm_to_opus(pcm)
    turn = await client.converse(packets)
    logging.info("STT: %s", turn.stt_text or "(empty)")
    logging.info("Agent: %s", turn.agent_reply or "(empty)")
    _log_motion(turn.motion)
    if turn.error_kind:
        logging.error("error_kind=%s", turn.error_kind)
    logging.info("actions: %s", turn.actions)
    logging.info("downlink opus frames: %s", len(turn.downlink_packets))
    await decode_and_play(turn.downlink_packets, playback, args.output)
    if turn.error_kind == "quota_exhausted":
        return 3
    if not turn.stt_text and not turn.agent_reply:
        return 1
    return 0


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    chassis = build_chassis(args.chassis, args.chassis_cmd)
    motion = MotionController(chassis)

    if args.say:
        command = parse_motion_intent(args.say)
        _log_motion(command)
        if command is None:
            return 1
        await motion.handle(command)
        await asyncio.sleep(command.duration_s if command.duration_s > 0 else 0.05)
        await motion.close()
        return 0

    require_opus()
    config = DeviceRuntimeConfig.from_env(
        ws_url=args.url,
        device_code=args.device_code,
        device_secret=args.device_secret,
        client_id=args.client_id,
    )
    playback = None if args.no_play or not args.live else AlsaPlayback(device=args.alsa_device)

    def on_action(action: str, raw: str) -> None:
        logging.getLogger("shuxin.rk3566.action").info("%s | raw=%s", action, raw)

    async with Rk3566VoiceClient(config, on_action=on_action, motion=motion) as client:
        if client.session.get("factory_acceptance"):
            logging.warning("device is in factory acceptance mode; staying connected for QA")
            await asyncio.sleep(30)
            return 0
        code = await _one_turn(args=args, client=client, playback=playback)
        while args.loop and code == 0:
            logging.info("listening again; Ctrl+C to stop")
            code = await _one_turn(args=args, client=client, playback=playback)
        return code


def main() -> None:
    args = _parse_args()
    try:
        raise SystemExit(asyncio.run(_run(args)))
    except KeyboardInterrupt:
        logging.info("stopped")
        raise SystemExit(0)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
