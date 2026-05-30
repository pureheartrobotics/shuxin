from __future__ import annotations

from shuxin.voice.config import default_device_tts_config, default_tencent_stt_config


def test_default_tencent_stt_config_shape(monkeypatch) -> None:
    monkeypatch.setenv("TENCENT_ASR_APPID", "1250000000")
    cfg = default_tencent_stt_config()
    assert cfg["type"] == "tencent-realtime"
    assert cfg["appid"] == "1250000000"
    assert cfg["model"] == "16k_zh"
    assert cfg["output_dir"] == "outputs"


def test_default_device_tts_config_shape() -> None:
    cfg = default_device_tts_config()
    assert cfg["type"] == "local"
    assert cfg["voice"]
