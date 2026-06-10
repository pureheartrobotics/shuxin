"""Opus wire-format helpers for hardware WebSocket audio."""

from __future__ import annotations

import shutil
import struct
import subprocess
from collections.abc import Iterator
from pathlib import Path

DEFAULT_FRAME_DURATION_MS = 60
UPLINK_SAMPLE_RATE = 16000
DOWNLINK_SAMPLE_RATE = 24000
FLASH_SAMPLE_RATE = 16000
FLASH_OPUS_BITRATE = 16000
DEFAULT_CHANNELS = 1

_opuslib = None


def _load_opuslib():
    """Lazy import so runtime `pip install opuslib_next` works without restarting voice server."""
    global _opuslib
    if _opuslib is not None:
        return _opuslib
    try:
        import opuslib_next as opuslib
    except ImportError:
        return None
    _opuslib = opuslib
    return _opuslib


def opus_available() -> bool:
    return _load_opuslib() is not None


def frame_samples(sample_rate: int, frame_duration_ms: int = DEFAULT_FRAME_DURATION_MS) -> int:
    return int(sample_rate * frame_duration_ms / 1000)


class OpusStreamDecoder:
    """Decode raw Opus packets into PCM16 mono bytes."""

    def __init__(
        self,
        sample_rate: int = UPLINK_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        frame_duration_ms: int = DEFAULT_FRAME_DURATION_MS,
    ) -> None:
        opuslib = _load_opuslib()
        if opuslib is None:
            raise RuntimeError("opuslib_next is not installed")
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_size = frame_samples(sample_rate, frame_duration_ms)
        self._decoder = opuslib.Decoder(sample_rate, channels)

    def decode_packet(self, packet: bytes) -> bytes:
        if not packet:
            return b""
        pcm = self._decoder.decode(packet, self.frame_size)
        return pcm[: self.frame_size * self.channels * 2]

    def decode_packets(self, packets: list[bytes]) -> bytes:
        return b"".join(self.decode_packet(packet) for packet in packets if packet)


class OpusStreamEncoder:
    """Encode PCM16 mono bytes into raw Opus packets."""

    def __init__(
        self,
        sample_rate: int = UPLINK_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        frame_duration_ms: int = DEFAULT_FRAME_DURATION_MS,
        bitrate: int | None = None,
    ) -> None:
        opuslib = _load_opuslib()
        if opuslib is None:
            raise RuntimeError("opuslib_next is not installed")
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_size = frame_samples(sample_rate, frame_duration_ms)
        self.frame_bytes = self.frame_size * channels * 2
        self._encoder = opuslib.Encoder(
            sample_rate,
            channels,
            opuslib.APPLICATION_AUDIO,
        )
        if bitrate is not None:
            self._encoder.bitrate = bitrate
        self._buffer = bytearray()

    def encode_chunk(self, pcm: bytes, *, end_of_stream: bool = False) -> list[bytes]:
        if pcm:
            self._buffer.extend(pcm)
        packets: list[bytes] = []
        while len(self._buffer) >= self.frame_bytes:
            frame = bytes(self._buffer[: self.frame_bytes])
            del self._buffer[: self.frame_bytes]
            encoded = self._encoder.encode(frame, self.frame_size)
            if encoded:
                packets.append(encoded)
        if end_of_stream and self._buffer:
            last = bytearray(self.frame_bytes)
            last[: len(self._buffer)] = self._buffer
            self._buffer.clear()
            encoded = self._encoder.encode(bytes(last), self.frame_size)
            if encoded:
                packets.append(encoded)
        return packets

    def encode_all(self, pcm: bytes) -> list[bytes]:
        packets = self.encode_chunk(pcm)
        packets.extend(self.encode_chunk(b"", end_of_stream=True))
        return packets


def decode_opus_packets(
    packets: list[bytes],
    *,
    sample_rate: int = UPLINK_SAMPLE_RATE,
    frame_duration_ms: int = DEFAULT_FRAME_DURATION_MS,
) -> bytes:
    return OpusStreamDecoder(
        sample_rate=sample_rate,
        frame_duration_ms=frame_duration_ms,
    ).decode_packets(packets)


def encode_pcm_to_opus_frames(
    pcm: bytes,
    *,
    sample_rate: int = UPLINK_SAMPLE_RATE,
    frame_duration_ms: int = DEFAULT_FRAME_DURATION_MS,
    bitrate: int | None = None,
) -> list[bytes]:
    return OpusStreamEncoder(
        sample_rate=sample_rate,
        frame_duration_ms=frame_duration_ms,
        bitrate=bitrate,
    ).encode_all(pcm)


def _ffmpeg_binary() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for audio transcoding")
    return ffmpeg


def _ffmpeg_pcm16_cmd(
    path: Path,
    *,
    sample_rate: int,
    channels: int = DEFAULT_CHANNELS,
) -> list[str]:
    return [
        _ffmpeg_binary(),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "pipe:1",
    ]


def ffmpeg_pcm16_from_file(
    path: Path,
    *,
    sample_rate: int,
    channels: int = DEFAULT_CHANNELS,
) -> bytes:
    result = subprocess.run(
        _ffmpeg_pcm16_cmd(path, sample_rate=sample_rate, channels=channels),
        check=True,
        capture_output=True,
    )
    return result.stdout


def extract_opus_packets_from_ogg(path: Path, *, sample_rate: int = UPLINK_SAMPLE_RATE) -> list[bytes]:
    """Convert an Ogg Opus file into raw 60ms Opus packets for WebSocket simulation."""
    pcm = ffmpeg_pcm16_from_file(path, sample_rate=sample_rate)
    return encode_pcm_to_opus_frames(pcm, sample_rate=sample_rate)


def iter_transcode_mp3_to_opus_frames(
    mp3_path: Path,
    *,
    sample_rate: int = DOWNLINK_SAMPLE_RATE,
    frame_duration_ms: int = DEFAULT_FRAME_DURATION_MS,
    bitrate: int | None = None,
    pcm_read_size: int = 4096,
) -> Iterator[bytes]:
    """Stream MP3 through ffmpeg pipe and yield raw Opus packets without buffering all PCM."""
    encoder = OpusStreamEncoder(
        sample_rate=sample_rate,
        frame_duration_ms=frame_duration_ms,
        bitrate=bitrate,
    )
    cmd = _ffmpeg_pcm16_cmd(mp3_path, sample_rate=sample_rate)
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        assert proc.stdout is not None
        while True:
            pcm_chunk = proc.stdout.read(pcm_read_size)
            if not pcm_chunk:
                break
            for packet in encoder.encode_chunk(pcm_chunk):
                yield packet
        stderr = proc.stderr.read() if proc.stderr is not None else b""
        if proc.wait() != 0:
            raise RuntimeError(
                f"ffmpeg transcoding failed: {stderr.decode('utf-8', errors='replace')}"
            )
    for packet in encoder.encode_chunk(b"", end_of_stream=True):
        yield packet


def transcode_mp3_to_opus_frames(
    mp3_path: Path,
    *,
    sample_rate: int = DOWNLINK_SAMPLE_RATE,
    frame_duration_ms: int = DEFAULT_FRAME_DURATION_MS,
    bitrate: int | None = None,
) -> list[bytes]:
    return list(
        iter_transcode_mp3_to_opus_frames(
            mp3_path,
            sample_rate=sample_rate,
            frame_duration_ms=frame_duration_ms,
            bitrate=bitrate,
        )
    )


def opus_packets_to_wav_bytes(
    packets: list[bytes],
    *,
    sample_rate: int = DOWNLINK_SAMPLE_RATE,
    frame_duration_ms: int = DEFAULT_FRAME_DURATION_MS,
) -> bytes:
    pcm = decode_opus_packets(
        packets,
        sample_rate=sample_rate,
        frame_duration_ms=frame_duration_ms,
    )
    return pcm16_to_wav_bytes(pcm, sample_rate=sample_rate)


def pcm16_to_wav_bytes(pcm: bytes, *, sample_rate: int, channels: int = DEFAULT_CHANNELS) -> bytes:
    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        len(pcm),
    )
    return header + pcm


def write_opus_packets_as_wav(
    packets: list[bytes],
    output_path: Path,
    *,
    sample_rate: int = DOWNLINK_SAMPLE_RATE,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        opus_packets_to_wav_bytes(packets, sample_rate=sample_rate)
    )
    return output_path


def looks_like_mp3(data: bytes) -> bool:
    if data.startswith(b"ID3"):
        return True
    return len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
