"""Soft-voice continuous mode + [SOFT-VOICE] observability helpers."""

from __future__ import annotations

from shuxin.voice.api.soft_voice import is_soft_voice_client, resolve_conversation_mode


def test_soft_client_forces_continuous():
    assert resolve_conversation_mode("soft-miniprogram", "push_to_talk") == "continuous"
    assert resolve_conversation_mode("miniprogram", None) == "continuous"
    assert resolve_conversation_mode("soft-miniprogram", "") == "continuous"


def test_web_demo_respects_requested_mode():
    assert resolve_conversation_mode("web-demo", "continuous") == "continuous"
    assert resolve_conversation_mode("web-demo", "push_to_talk") == "push_to_talk"
    assert resolve_conversation_mode("web-demo", None) == "push_to_talk"
    assert resolve_conversation_mode("hardware-x", "CONTINUOUS") == "continuous"


def test_is_soft_voice_client():
    assert is_soft_voice_client("soft-miniprogram")
    assert is_soft_voice_client("miniprogram")
    assert not is_soft_voice_client("web-demo")
