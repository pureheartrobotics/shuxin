"""Tests for Volcengine TTS config resolver and provider."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from shuxin.voice.config import ProviderConfig
from shuxin.voice.providers import create_tts_provider
from shuxin.voice.tts_config import TtsProfile, TtsProfileRegistry, resolve_tts_config
from shuxin.voice.volcengine_tts import (
    VolcengineCloneTTSProvider,
    VolcengineTTSError,
    _extract_audio_bytes,
)


def test_tts_profile_registry_loads_yaml(tmp_path: Path) -> None:
    config = tmp_path / "tts_profiles.yaml"
    config.write_text(
        """
default_profile_id: shuxin
profiles:
  shuxin:
    voice_type: voice_shuxin_001
    cluster: volcano_icl
    speed_ratio: 1.0
    encoding: mp3
    uid: shuxin
  guardian:
    voice_type: voice_guardian_001
    cluster: volcano_icl
    speed_ratio: 0.95
    encoding: mp3
    uid: guardian
""".strip(),
        encoding="utf-8",
    )
    registry = TtsProfileRegistry.load(config)
    assert registry.default_profile_id == "shuxin"
    assert registry.get("guardian").voice_type == "voice_guardian_001"
    assert registry.get("guardian").speed_ratio == pytest.approx(0.95)


def test_resolve_tts_config_merges_profile_and_device(monkeypatch) -> None:
    monkeypatch.setenv("VOLCENGINE_TTS_API_KEY", "test-key")
    monkeypatch.setenv("VOLCENGINE_TTS_VOICE_TYPE", "env_voice")
    from shuxin.voice.tts_config import get_tts_profile_registry

    get_tts_profile_registry.cache_clear()

    device = ProviderConfig(
        type="volcengine-clone",
        profile_id="shuxin",
        speed_ratio=0.92,
    )
    resolved = resolve_tts_config(device)
    assert resolved.api_key == "test-key"
    assert resolved.voice_type == "env_voice"
    assert resolved.speed_ratio == pytest.approx(0.92)
    assert resolved.cluster == "volcano_icl"
    assert resolved.encoding == "mp3"

    get_tts_profile_registry.cache_clear()


def test_resolve_tts_config_empty_speed_does_not_override_profile(monkeypatch) -> None:
    monkeypatch.setenv("VOLCENGINE_TTS_API_KEY", "test-key")
    monkeypatch.setenv("VOLCENGINE_TTS_VOICE_TYPE", "env_voice")
    from shuxin.voice.tts_config import get_tts_profile_registry

    get_tts_profile_registry.cache_clear()

    device = ProviderConfig(type="volcengine-clone", profile_id="shuxin", rate="")
    resolved = resolve_tts_config(device)
    assert resolved.speed_ratio == pytest.approx(1.0)

    get_tts_profile_registry.cache_clear()


def test_resolve_tts_config_requires_voice_type_and_api_key(monkeypatch) -> None:
    monkeypatch.delenv("VOLCENGINE_TTS_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_TTS_VOICE_TYPE", raising=False)
    from shuxin.voice.tts_config import get_tts_profile_registry

    get_tts_profile_registry.cache_clear()

    with pytest.raises(ValueError, match="voice_type"):
        resolve_tts_config(ProviderConfig(type="volcengine-clone", profile_id="shuxin"))

    monkeypatch.setenv("VOLCENGINE_TTS_VOICE_TYPE", "voice_001")
    get_tts_profile_registry.cache_clear()
    with pytest.raises(ValueError, match="api_key"):
        resolve_tts_config(ProviderConfig(type="volcengine-clone", profile_id="shuxin"))

    get_tts_profile_registry.cache_clear()


def test_extract_audio_bytes_success() -> None:
    payload = {"code": 3000, "data": base64.b64encode(b"mp3-bytes").decode("ascii")}
    assert _extract_audio_bytes(payload) == b"mp3-bytes"


def test_extract_audio_bytes_api_error() -> None:
    with pytest.raises(VolcengineTTSError) as exc:
        _extract_audio_bytes({"code": 4001, "message": "bad request"})
    assert exc.value.error_kind == "tts_api_error"
    assert exc.value.api_code == 4001


def test_resolve_tts_config_env_voice_type_fallback_when_profile_empty(monkeypatch) -> None:
    """Profile may cache empty voice_type; resolver still reads live env."""
    monkeypatch.setenv("VOLCENGINE_TTS_API_KEY", "test-key")
    monkeypatch.setenv("VOLCENGINE_TTS_VOICE_TYPE", "live_env_voice")

    empty_registry = TtsProfileRegistry(
        default_profile_id="shuxin",
        profiles={
            "shuxin": TtsProfile(profile_id="shuxin", voice_type=""),
        },
    )
    monkeypatch.setattr(
        "shuxin.voice.tts_config.get_tts_profile_registry",
        lambda: empty_registry,
    )

    resolved = resolve_tts_config(
        ProviderConfig(type="volcengine-clone", profile_id="shuxin")
    )
    assert resolved.voice_type == "live_env_voice"


def test_create_tts_provider_routes_volcengine(monkeypatch) -> None:
    monkeypatch.setenv("VOLCENGINE_TTS_API_KEY", "test-key")
    monkeypatch.setenv("VOLCENGINE_TTS_VOICE_TYPE", "voice_001")
    from shuxin.voice.tts_config import get_tts_profile_registry

    get_tts_profile_registry.cache_clear()

    provider = create_tts_provider(
        ProviderConfig(type="volcengine-clone", profile_id="shuxin")
    )
    assert isinstance(provider, VolcengineCloneTTSProvider)

    get_tts_profile_registry.cache_clear()


def test_volcengine_provider_writes_mp3(monkeypatch, tmp_path: Path) -> None:
    import asyncio

    from shuxin.voice.tts_config import ResolvedTtsConfig

    audio = base64.b64encode(b"fake-mp3").decode("ascii")

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"code": 3000, "data": audio}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("shuxin.voice.volcengine_tts.httpx.AsyncClient", lambda **kw: FakeClient())

    provider = VolcengineCloneTTSProvider(
        ResolvedTtsConfig(
            provider_type="volcengine-clone",
            api_url="https://example.test/tts",
            api_key="key",
            voice_type="voice_001",
            cluster="volcano_icl",
            speed_ratio=1.0,
            encoding="mp3",
            uid="shuxin",
        )
    )
    out = tmp_path / "out.mp3"

    async def _run():
        return await provider.synthesize("你好", out)

    result = asyncio.run(_run())
    assert result == out
    assert out.read_bytes() == b"fake-mp3"
