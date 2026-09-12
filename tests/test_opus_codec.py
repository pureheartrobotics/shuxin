from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from shuxin.voice.audio.opus_codec import (
    DOWNLINK_SAMPLE_RATE,
    UPLINK_SAMPLE_RATE,
    OpusStreamDecoder,
    OpusStreamEncoder,
    decode_opus_packets,
    encode_pcm_to_opus_frames,
    extract_opus_packets_from_ogg,
    iter_transcode_mp3_to_opus_frames,
    looks_like_mp3,
    opus_available,
    transcode_mp3_to_opus_frames,
)

ROOT = Path(__file__).resolve().parents[1]
ACTIVATION_OGG = ROOT / "data" / "test" / "activation.ogg"
VOLC_DEMO_MP3 = ROOT / "outputs" / "volc-demo.mp3"


def test_negotiate_audio_params_pcm_default():
    from shuxin.voice.api.ws_session import _negotiate_audio_params

    result = _negotiate_audio_params(None)
    assert result["format"] == "pcm"
    assert result["uplink_sample_rate"] == UPLINK_SAMPLE_RATE


def test_negotiate_audio_params_opus():
    from shuxin.voice.api.ws_session import _negotiate_audio_params

    result = _negotiate_audio_params(
        {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}
    )
    assert result["format"] == "opus"
    assert result["downlink_sample_rate"] == DOWNLINK_SAMPLE_RATE


pytestmark = pytest.mark.skipif(not opus_available(), reason="opuslib_next not installed")


def test_extract_activation_ogg_and_decode_pcm():
    if not ACTIVATION_OGG.exists():
        pytest.skip("activation.ogg not found")
    packets = extract_opus_packets_from_ogg(ACTIVATION_OGG)
    assert packets
    pcm = decode_opus_packets(packets, sample_rate=UPLINK_SAMPLE_RATE)
    assert len(pcm) > 0


def test_pcm_round_trip_16k():
    pcm = b"\x00\x01" * (960 * 10)
    packets = encode_pcm_to_opus_frames(pcm, sample_rate=UPLINK_SAMPLE_RATE)
    assert packets
    decoded = decode_opus_packets(packets, sample_rate=UPLINK_SAMPLE_RATE)
    assert len(decoded) >= len(pcm) - 960 * 2


def test_opus_stream_encoder_decoder_single_frame():
    encoder = OpusStreamEncoder(sample_rate=UPLINK_SAMPLE_RATE)
    decoder = OpusStreamDecoder(sample_rate=UPLINK_SAMPLE_RATE)
    frame_pcm = b"\0\0" * 960
    packets = encoder.encode_all(frame_pcm)
    assert packets
    out = decoder.decode_packet(packets[0])
    assert len(out) == 960 * 2


def test_transcode_mp3_to_opus_frames_when_sample_exists():
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    if not VOLC_DEMO_MP3.exists():
        pytest.skip("outputs/volc-demo.mp3 not found")
    frames = transcode_mp3_to_opus_frames(VOLC_DEMO_MP3, sample_rate=DOWNLINK_SAMPLE_RATE)
    assert frames
    pcm = decode_opus_packets(frames, sample_rate=DOWNLINK_SAMPLE_RATE)
    assert len(pcm) > 0


def test_iter_transcode_matches_batch_packet_count():
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    if not VOLC_DEMO_MP3.exists():
        pytest.skip("outputs/volc-demo.mp3 not found")
    batch = transcode_mp3_to_opus_frames(VOLC_DEMO_MP3, sample_rate=DOWNLINK_SAMPLE_RATE)
    streamed = list(
        iter_transcode_mp3_to_opus_frames(VOLC_DEMO_MP3, sample_rate=DOWNLINK_SAMPLE_RATE)
    )
    assert len(streamed) == len(batch)
    assert streamed == batch


def test_transcode_opus_packets_within_downlink_limit():
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    if not VOLC_DEMO_MP3.exists():
        pytest.skip("outputs/volc-demo.mp3 not found")
    frames = transcode_mp3_to_opus_frames(VOLC_DEMO_MP3, sample_rate=DOWNLINK_SAMPLE_RATE)
    assert frames
    for packet in frames:
        assert len(packet) <= 4096
        assert not looks_like_mp3(packet)
