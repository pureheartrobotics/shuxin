"""音频输入输出。

开发机可用 WAV 文件闭环；RK3566 Linux 可用 arecord/aplay（S16_LE）。
编码/解码 Opus 复用云端同一套 `shuxin.voice.audio.opus_codec`，避免两套帧格式。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import wave
from pathlib import Path

from shuxin.voice.audio.opus_codec import (
    DOWNLINK_SAMPLE_RATE,
    UPLINK_SAMPLE_RATE,
    OpusStreamDecoder,
    OpusStreamEncoder,
    opus_available,
    write_opus_packets_as_wav,
)

logger = logging.getLogger("shuxin.rk3566.audio")


def require_opus() -> None:
    if not opus_available():
        raise RuntimeError(
            "opuslib_next is required for RK3566 hardware wire format. "
            "Install apps/rk3566/requirements.txt"
        )


def pcm_from_wav(path: Path, expected_rate: int = UPLINK_SAMPLE_RATE) -> bytes:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1:
            raise ValueError(f"{path} must be mono")
        if handle.getsampwidth() != 2:
            raise ValueError(f"{path} must be 16-bit PCM")
        rate = handle.getframerate()
        pcm = handle.readframes(handle.getnframes())
    if rate != expected_rate:
        logger.warning("wav sample_rate=%s expected=%s (sending anyway)", rate, expected_rate)
    return pcm


def encode_pcm_to_opus(pcm: bytes) -> list[bytes]:
    require_opus()
    encoder = OpusStreamEncoder(sample_rate=UPLINK_SAMPLE_RATE)
    return encoder.encode_all(pcm)


def decode_opus_to_wav(packets: list[bytes], output: Path) -> Path:
    require_opus()
    output.parent.mkdir(parents=True, exist_ok=True)
    write_opus_packets_as_wav(packets, output, sample_rate=DOWNLINK_SAMPLE_RATE)
    return output


class AlsaCapture:
    """Capture 16 kHz mono S16_LE from the default capture device via arecord."""

    def __init__(self, device: str = "default", sample_rate: int = UPLINK_SAMPLE_RATE) -> None:
        self.device = device
        self.sample_rate = sample_rate

    async def capture_seconds(self, seconds: float) -> bytes:
        arecord = shutil.which("arecord")
        if not arecord:
            raise RuntimeError("arecord not found; install alsa-utils on the RK3566 image")
        frames = max(1, int(self.sample_rate * seconds))
        proc = await asyncio.create_subprocess_exec(
            arecord,
            "-q",
            "-D",
            self.device,
            "-f",
            "S16_LE",
            "-r",
            str(self.sample_rate),
            "-c",
            "1",
            "-t",
            "raw",
            "-d",
            str(max(1, int(seconds))),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode not in (0, None) and not stdout:
            raise RuntimeError(stderr.decode("utf-8", errors="replace") or "arecord failed")
        expected = frames * 2
        if len(stdout) > expected:
            return stdout[:expected]
        return stdout


class AlsaPlayback:
    """Play 24 kHz mono S16_LE on the default playback device via aplay."""

    def __init__(self, device: str = "default", sample_rate: int = DOWNLINK_SAMPLE_RATE) -> None:
        self.device = device
        self.sample_rate = sample_rate

    async def play_pcm(self, pcm: bytes) -> None:
        aplay = shutil.which("aplay")
        if not aplay:
            raise RuntimeError("aplay not found; install alsa-utils on the RK3566 image")
        if not pcm:
            return
        proc = await asyncio.create_subprocess_exec(
            aplay,
            "-q",
            "-D",
            self.device,
            "-f",
            "S16_LE",
            "-r",
            str(self.sample_rate),
            "-c",
            "1",
            "-t",
            "raw",
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate(pcm)
        if proc.returncode not in (0, None):
            logger.warning("aplay failed: %s", stderr.decode("utf-8", errors="replace"))


async def decode_and_play(packets: list[bytes], playback: AlsaPlayback | None, wav_out: Path | None) -> None:
    if not packets:
        return
    require_opus()
    decoder = OpusStreamDecoder(sample_rate=DOWNLINK_SAMPLE_RATE)
    pcm = decoder.decode_packets(packets)
    if wav_out is not None:
        decode_opus_to_wav(packets, wav_out)
    if playback is not None:
        await playback.play_pcm(pcm)
