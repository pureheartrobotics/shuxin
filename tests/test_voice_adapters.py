from pathlib import Path

import pytest

from shuxin.voice.adapters import VoiceAdapterRegistry


def test_voice_adapter_registry_exposes_allowlisted_actions(tmp_path: Path) -> None:
    registry = VoiceAdapterRegistry(shuxin_home=tmp_path)

    adapters = {item["name"]: item["actions"] for item in registry.list_adapters()}

    assert adapters["skills"] == ["list", "read"]
    assert adapters["tools"] == ["list"]
    assert adapters["plugins"] == ["list"]
    assert adapters["agent"] == ["chat"]
    assert adapters["cli"] == ["command"]


def test_voice_adapter_registry_blocks_unknown_action(tmp_path: Path) -> None:
    registry = VoiceAdapterRegistry(shuxin_home=tmp_path)

    with pytest.raises(PermissionError):
        registry.call("tools", "call", {})


def test_voice_adapter_registry_lists_tools(tmp_path: Path) -> None:
    registry = VoiceAdapterRegistry(shuxin_home=tmp_path)

    assert registry.call("tools", "list", {}) == []
