"""web-demo vs hardware wire-format negotiation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from shuxin.voice.api.ws_session import _VoiceWebSocketSession, _negotiate_audio_params


def _make_session() -> _VoiceWebSocketSession:
    return _VoiceWebSocketSession(
        websocket=SimpleNamespace(),
        service=SimpleNamespace(),
        repo=SimpleNamespace(),
        shuxin_home=Path("/tmp"),
        default_device_id="demo-device-001",
        out_dir=Path("/tmp"),
    )


def test_web_demo_hardware_session_keeps_pcm_wire_format():
    session = _make_session()
    session.client_id = "web-demo"
    session.hardware_session = True
    session.audio_params = _negotiate_audio_params(None)
    if (
        session.hardware_session
        and not session._is_web_demo_client()
        and session.audio_params["format"] != "opus"
    ):
        session.audio_params = _negotiate_audio_params({"format": "opus"})
    session.audio_wire_format = str(session.audio_params["format"])
    assert session.audio_wire_format == "pcm"
    assert session._is_web_demo_client()
    assert not session._uses_opus_downlink()


def test_hardware_client_forces_opus_wire_format():
    session = _make_session()
    session.client_id = "esp32-c3"
    session.hardware_session = True
    session.audio_params = _negotiate_audio_params(None)
    if (
        session.hardware_session
        and not session._is_web_demo_client()
        and session.audio_params["format"] != "opus"
    ):
        session.audio_params = _negotiate_audio_params({"format": "opus"})
    session.audio_wire_format = str(session.audio_params["format"])
    assert session.audio_wire_format == "opus"
    assert session._uses_opus_downlink()


def test_soft_miniprogram_client_keeps_pcm_like_web_demo():
    session = _make_session()
    session.client_id = "soft-miniprogram"
    session.hardware_session = True
    session.audio_params = _negotiate_audio_params({"format": "pcm", "sample_rate": 16000})
    if (
        session.hardware_session
        and not session._is_web_demo_client()
        and session.audio_params["format"] != "opus"
    ):
        session.audio_params = _negotiate_audio_params({"format": "opus"})
    session.audio_wire_format = str(session.audio_params["format"])
    assert session._is_web_demo_client()
    assert session.audio_wire_format == "pcm"
    assert not session._uses_opus_downlink()
