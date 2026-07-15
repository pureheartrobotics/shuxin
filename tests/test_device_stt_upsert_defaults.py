"""Guard: empty stt_config must not become TTS type volcengine-clone on STT path."""

from __future__ import annotations

import pytest

from shuxin.voice.config.config import ProviderConfig, default_tencent_stt_config
from shuxin.voice.integrations.tencent_realtime_asr import is_tencent_realtime_stt
from shuxin.voice.providers import create_stt_provider


def test_empty_provider_config_defaults_to_volcengine_clone_name() -> None:
    """Documents the shared dataclass pitfall; upsert must not leave STT empty."""
    cfg = ProviderConfig(**{})
    assert cfg.type == "volcengine-clone"


def test_empty_stt_is_not_tencent_and_create_stt_raises() -> None:
    cfg = ProviderConfig(**{})
    assert not is_tencent_realtime_stt(cfg)
    with pytest.raises(ValueError, match="Unsupported STT provider type"):
        create_stt_provider(cfg)


def test_default_tencent_stt_skips_create_stt_provider() -> None:
    cfg = ProviderConfig(**default_tencent_stt_config())
    assert is_tencent_realtime_stt(cfg)
    assert cfg.type == "tencent-realtime"


def test_upsert_empty_stt_payload_helpers() -> None:
    """Mirrors device_repo.upsert_device empty-object rule."""
    raw_stt: dict = {}
    has_stt = isinstance(raw_stt, dict) and bool(raw_stt)
    assert has_stt is False
    chosen = raw_stt if has_stt else default_tencent_stt_config()
    assert chosen["type"] == "tencent-realtime"
