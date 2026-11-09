from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LLMDeviceConfig:
    provider: str = ""
    model: str = ""
    base_url: str = ""
    api_key: str = ""


TTS_EFFECT_ENV = "SHUXIN_TTS_EFFECT"


@dataclass
class ProviderConfig:
    type: str = "volcengine-clone"
    model: str = ""
    model_dir: str = "models/SenseVoiceSmall"
    appid: str = ""
    api_url: str = ""
    api_key: str = ""
    voice: str = ""
    output_dir: str = "outputs"
    rate: str = ""
    pitch: str = ""
    volume: str = ""
    effect: str = ""
    effect_strength: str = "medium"
    profile_id: str = ""
    cluster: str = ""
    speed_ratio: float | None = None
    encoding: str = ""
    uid: str = ""


def resolve_tts_effect(config: ProviderConfig) -> tuple[str, str]:
    """Device tts.effect overrides env SHUXIN_TTS_EFFECT when set."""
    device_effect = (config.effect or "").strip().lower()
    env_effect = os.environ.get(TTS_EFFECT_ENV, "").strip().lower()
    selected = device_effect or env_effect or "none"
    if selected in {"", "none", "off", "false", "0"}:
        return "none", _normalize_effect_strength(config.effect_strength)
    return selected, _normalize_effect_strength(config.effect_strength)


def _normalize_effect_strength(strength: str | None) -> str:
    value = (strength or "medium").strip().lower()
    if value in {"low", "medium", "high"}:
        return value
    return "medium"


@dataclass
class DeviceConfig:
    device_id: str
    llm: LLMDeviceConfig = field(default_factory=LLMDeviceConfig)
    stt: ProviderConfig = field(default_factory=ProviderConfig)
    tts: ProviderConfig = field(default_factory=ProviderConfig)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VoiceConfig:
    default_device_id: str = "demo-device-001"
    stt: ProviderConfig = field(default_factory=ProviderConfig)
    tts: ProviderConfig = field(default_factory=ProviderConfig)


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        expanded = os.path.expandvars(value)
        return re.sub(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", "", expanded)
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


_LLM_MERGE_KEYS = ("provider", "model", "base_url", "api_key")


def default_tencent_stt_config() -> dict[str, Any]:
    """Default STT for provisioned devices and bulk apply; appid may come from env at runtime."""
    return {
        "type": "tencent-realtime",
        "appid": os.environ.get("TENCENT_ASR_APPID", ""),
        "model": "16k_zh",
        "output_dir": "outputs",
    }


def default_device_tts_config() -> dict[str, Any]:
    """Default TTS for factory-provisioned devices (Volcengine voice clone)."""
    return {
        "type": "volcengine-clone",
        "profile_id": "shuxin",
        "encoding": "mp3",
        "output_dir": "outputs",
    }


def merge_llm_device_config(
    base: LLMDeviceConfig,
    override: dict[str, Any],
) -> LLMDeviceConfig:
    """Merge user-level LLM overrides without blanking device defaults."""
    merged = dict(base.__dict__)
    for key in _LLM_MERGE_KEYS:
        if key not in override:
            continue
        value = override[key]
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[key] = value
    return LLMDeviceConfig(**merged)


class DeviceConfigProvider:
    """Loads demo device configuration from a local YAML file.

    The shape is intentionally close to a future remote config service: callers
    ask for a device id and receive LLM/STT/TTS settings for that device.
    """

    def __init__(self, config_path: str | os.PathLike[str] | None = None) -> None:
        self.config_path = Path(
            config_path
            or os.environ.get("VOICE_DEVICE_CONFIG", "data/devices.yaml")
        )
        self._raw = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        with self.config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Device config must be a mapping: {self.config_path}")
        return _expand_env(data)

    def get(self, device_id: str | None = None) -> DeviceConfig:
        defaults = self._raw.get("defaults", {})
        devices = self._raw.get("devices", {})
        selected_id = device_id or self._raw.get("default_device_id") or "demo-device-001"
        device_data = devices.get(selected_id, {})
        data = _merge_dict(defaults, device_data)

        return DeviceConfig(
            device_id=selected_id,
            llm=LLMDeviceConfig(**data.get("llm", {})),
            stt=ProviderConfig(**data.get("stt", {})),
            tts=ProviderConfig(**data.get("tts", {})),
        )
