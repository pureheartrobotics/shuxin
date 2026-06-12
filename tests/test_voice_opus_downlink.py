from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shuxin.voice.opus_codec import looks_like_mp3, opus_available
from shuxin.voice.server import (
    HARD_WS_DOWNLINK_MAX_BYTES as SERVER_HARD_MAX,
    _VoiceWebSocketSession,
    _negotiate_audio_params,
    _ws_downlink_max_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
VOLC_DEMO_MP3 = ROOT / "outputs" / "volc-demo.mp3"


def _make_downlink_session() -> _VoiceWebSocketSession:
    session = _VoiceWebSocketSession(
        websocket=SimpleNamespace(),
        service=SimpleNamespace(),
        repo=SimpleNamespace(),
        shuxin_home=Path("/tmp"),
        default_device_id="demo-device-001",
        out_dir=Path("/tmp"),
    )
    session.audio_params = _negotiate_audio_params(
        {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}
    )
    session.audio_wire_format = "opus"
    session.hardware_session = True
    session.client_id = "opus-smoke-client"
    session.sent_bytes: list[bytes] = []
    session.websocket.send_bytes = AsyncMock(
        side_effect=lambda data: session.sent_bytes.append(data)
    )
    return session


def test_ws_downlink_max_bytes_clamped():
    assert _ws_downlink_max_bytes() <= SERVER_HARD_MAX


@pytest.mark.skipif(not opus_available(), reason="opuslib_next not installed")
def test_send_opus_downlink_stream_multiple_small_frames():
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    if not VOLC_DEMO_MP3.exists():
        pytest.skip("outputs/volc-demo.mp3 not found")
    session = _make_downlink_session()

    async def run() -> None:
        await session._send_opus_downlink_stream(VOLC_DEMO_MP3)

    asyncio.run(run())
    assert len(session.sent_bytes) > 1
    for packet in session.sent_bytes:
        assert len(packet) <= SERVER_HARD_MAX
        assert not looks_like_mp3(packet)


@pytest.mark.skipif(not opus_available(), reason="opuslib_next not installed")
def test_hardware_session_uses_opus_downlink_not_whole_mp3():
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    if not VOLC_DEMO_MP3.exists():
        pytest.skip("outputs/volc-demo.mp3 not found")
    session = _make_downlink_session()
    session.audio_wire_format = "pcm"
    assert session._uses_opus_downlink()

    async def run() -> None:
        await session._send_opus_downlink_stream(VOLC_DEMO_MP3)

    asyncio.run(run())
    assert len(session.sent_bytes) > 1
    assert not any(looks_like_mp3(packet) for packet in session.sent_bytes)


def test_web_demo_uses_mp3_downlink_not_opus():
    session = _make_downlink_session()
    session.client_id = "web-demo"
    session.hardware_session = True
    session.audio_wire_format = "pcm"
    assert not session._uses_opus_downlink()


def test_send_downlink_bytes_chunks_large_binary_for_hardware():
    session = _make_downlink_session()
    session.client_id = "hw-client"
    big = b"x" * 5000

    async def run() -> None:
        await session._send_downlink_bytes(big)

    asyncio.run(run())
    assert session.sent_bytes
    assert all(len(chunk) <= SERVER_HARD_MAX for chunk in session.sent_bytes)
    assert sum(len(chunk) for chunk in session.sent_bytes) == len(big)


def test_send_downlink_bytes_web_demo_sends_whole_blob():
    session = _make_downlink_session()
    session.client_id = "web-demo"
    payload = b"whole-mp3-blob"

    async def run() -> None:
        await session._send_downlink_bytes(payload)

    asyncio.run(run())
    assert session.sent_bytes == [payload]
