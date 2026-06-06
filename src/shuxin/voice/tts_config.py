"""TTS profile registry and config resolver (cross-cutting layer for voice providers)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from shuxin.voice.agents import AgentRecord, DEFAULT_AGENT_ID
from shuxin.voice.config import ProviderConfig, _expand_env

TTS_PROFILES_CONFIG_ENV = "VOICE_TTS_PROFILES_CONFIG"
DEFAULT_TTS_PROFILES_PATH = Path("data/tts_profiles.yaml")

VOLCENGINE_TTS_API_KEY_ENV = "VOLCENGINE_TTS_API_KEY"
VOLCENGINE_TTS_API_URL_ENV = "VOLCENGINE_TTS_API_URL"
VOLCENGINE_TTS_VOICE_TYPE_ENV = "VOLCENGINE_TTS_VOICE_TYPE"
DEFAULT_VOLCENGINE_TTS_API_URL = "https://openspeech.bytedance.com/api/v1/tts"

@dataclass(frozen=True)
class TtsProfile:
    profile_id: str
    voice_type: str = ""
    cluster: str = "volcano_icl"
    speed_ratio: float = 1.0
    encoding: str = "mp3"
    uid: str = "shuxin"


@dataclass(frozen=True)
class ResolvedTtsConfig:
    """Fully resolved TTS settings passed to VolcengineCloneTTSProvider."""

    provider_type: str
    api_url: str
    api_key: str
    voice_type: str
    cluster: str
    speed_ratio: float
    encoding: str
    uid: str
    output_dir: str = "outputs"
    profile_id: str = ""


@dataclass
class TtsProfileRegistry:
    default_profile_id: str = "shuxin"
    profiles: dict[str, TtsProfile] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> TtsProfileRegistry:
        config_path = path or Path(
            os.environ.get(TTS_PROFILES_CONFIG_ENV, DEFAULT_TTS_PROFILES_PATH)
        )
        if not config_path.exists():
            return cls(
                default_profile_id="shuxin",
                profiles={
                    "shuxin": TtsProfile(
                        profile_id="shuxin",
                        voice_type=os.environ.get("VOLCENGINE_TTS_VOICE_TYPE", ""),
                    )
                },
            )

        with config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"TTS profiles config must be a mapping: {config_path}")

        expanded = _expand_env(raw)
        default_id = str(expanded.get("default_profile_id") or "shuxin")
        profiles_raw = expanded.get("profiles") or {}
        profiles: dict[str, TtsProfile] = {}
        for profile_id, data in profiles_raw.items():
            if not isinstance(data, dict):
                continue
            speed = data.get("speed_ratio", 1.0)
            profiles[str(profile_id)] = TtsProfile(
                profile_id=str(profile_id),
                voice_type=str(data.get("voice_type") or ""),
                cluster=str(data.get("cluster") or "volcano_icl"),
                speed_ratio=float(speed),
                encoding=str(data.get("encoding") or "mp3"),
                uid=str(data.get("uid") or profile_id),
            )
        return cls(default_profile_id=default_id, profiles=profiles)

    def get(self, profile_id: str | None) -> TtsProfile:
        selected = (profile_id or self.default_profile_id).strip() or self.default_profile_id
        if selected in self.profiles:
            return self.profiles[selected]
        if self.default_profile_id in self.profiles:
            return self.profiles[self.default_profile_id]
        raise ValueError(f"Unknown TTS profile_id: {selected}")


@lru_cache(maxsize=1)
def get_tts_profile_registry() -> TtsProfileRegistry:
    return TtsProfileRegistry.load()


def _coerce_speed_ratio(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _pick_non_blank(device: ProviderConfig, key: str) -> Any:
    value = getattr(device, key, None)
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def resolve_tts_config(device_tts: ProviderConfig) -> ResolvedTtsConfig:
    """Merge profile defaults, device overrides, and env secrets."""
    provider_type = (device_tts.type or "volcengine-clone").strip().lower()
    registry = get_tts_profile_registry()

    profile_id = str(_pick_non_blank(device_tts, "profile_id") or registry.default_profile_id)
    if provider_type in {"volcengine-clone", "volcengine", "volc-clone"}:
        profile = registry.get(profile_id)
    else:
        profile = TtsProfile(profile_id=profile_id)

    voice_type = str(
        _pick_non_blank(device_tts, "voice")
        or getattr(device_tts, "voice_type", None)
        or profile.voice_type
        or os.environ.get(VOLCENGINE_TTS_VOICE_TYPE_ENV, "")
        or ""
    )
    cluster = str(
        _pick_non_blank(device_tts, "cluster")
        or profile.cluster
    )
    encoding = str(_pick_non_blank(device_tts, "encoding") or profile.encoding or "mp3")
    uid = str(_pick_non_blank(device_tts, "uid") or profile.uid)
    output_dir = str(_pick_non_blank(device_tts, "output_dir") or "outputs")

    speed_override = _coerce_speed_ratio(getattr(device_tts, "speed_ratio", None))
    if speed_override is None and device_tts.rate:
        speed_override = _coerce_speed_ratio(device_tts.rate)
    speed_ratio = speed_override if speed_override is not None else profile.speed_ratio

    api_url = str(
        _pick_non_blank(device_tts, "api_url")
        or os.environ.get(VOLCENGINE_TTS_API_URL_ENV, DEFAULT_VOLCENGINE_TTS_API_URL)
    )
    api_key = str(
        _pick_non_blank(device_tts, "api_key")
        or os.environ.get(VOLCENGINE_TTS_API_KEY_ENV, "")
    )

    if provider_type in {"volcengine-clone", "volcengine", "volc-clone"}:
        if not voice_type.strip():
            raise ValueError(
                "volcengine-clone TTS requires voice_type "
                "(set VOLCENGINE_TTS_VOICE_TYPE or tts.voice / profile voice_type). "
                "If configured in host .env, run bash scripts/redeploy_docker.sh to "
                "recreate the container, or pass VOLCENGINE_TTS_VOICE_TYPE=... to docker exec."
            )
        if not api_key.strip():
            raise ValueError(
                "volcengine-clone TTS requires api_key (set VOLCENGINE_TTS_API_KEY). "
                "If configured in host .env, run bash scripts/redeploy_docker.sh to "
                "recreate the container, or pass VOLCENGINE_TTS_API_KEY=... to docker exec."
            )

    return ResolvedTtsConfig(
        provider_type=provider_type,
        api_url=api_url,
        api_key=api_key,
        voice_type=voice_type,
        cluster=cluster,
        speed_ratio=speed_ratio,
        encoding=encoding,
        uid=uid,
        output_dir=output_dir,
        profile_id=profile_id,
    )


def resolve_tts_config_from_agent(
    agent: AgentRecord,
    *,
    output_dir: str = "outputs",
) -> ResolvedTtsConfig:
    """Resolve Volcengine TTS settings from a Postgres agent record."""
    voice_type = str(agent.voice_type or os.environ.get(VOLCENGINE_TTS_VOICE_TYPE_ENV, "") or "")
    api_url = str(os.environ.get(VOLCENGINE_TTS_API_URL_ENV, DEFAULT_VOLCENGINE_TTS_API_URL))
    api_key = str(os.environ.get(VOLCENGINE_TTS_API_KEY_ENV, ""))
    if not voice_type.strip():
        raise ValueError(
            "volcengine-clone TTS requires voice_type on agent or VOLCENGINE_TTS_VOICE_TYPE env"
        )
    if not api_key.strip():
        raise ValueError(
            "volcengine-clone TTS requires api_key (set VOLCENGINE_TTS_API_KEY)"
        )
    return ResolvedTtsConfig(
        provider_type="volcengine-clone",
        api_url=api_url,
        api_key=api_key,
        voice_type=voice_type,
        cluster=str(agent.cluster or "volcano_icl"),
        speed_ratio=float(agent.speed_ratio or 1.0),
        encoding=str(agent.encoding or "mp3"),
        uid=str(agent.uid or agent.agent_id),
        output_dir=output_dir,
        profile_id=agent.agent_id,
    )


def create_tts_provider_from_agent(agent: AgentRecord, *, output_dir: str = "outputs"):
    """Create TTS provider from agent record (user-bound voice)."""
    from shuxin.voice.providers import create_tts_provider

    resolved = resolve_tts_config_from_agent(agent, output_dir=output_dir)
    stub = ProviderConfig(type="volcengine-clone", profile_id=agent.agent_id)
    return create_tts_provider(stub, resolved=resolved)


def create_tts_provider_from_device(device_tts: ProviderConfig):
    """Unified factory: resolve config then instantiate provider."""
    from shuxin.voice.providers import create_tts_provider

    resolved = resolve_tts_config(device_tts)
    return create_tts_provider(device_tts, resolved=resolved)
