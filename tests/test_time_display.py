"""Beijing timezone display formatting."""

from __future__ import annotations

from datetime import datetime, timezone

from shuxin.voice.time_display import format_beijing_display, format_beijing_iso


def test_format_beijing_display_from_utc() -> None:
    utc = datetime(2026, 6, 30, 3, 1, 16, 629832, tzinfo=timezone.utc)
    assert format_beijing_display(utc) == "2026-06-30 11:01:16"


def test_format_beijing_display_none() -> None:
    assert format_beijing_display(None) == ""


def test_format_beijing_iso_from_utc() -> None:
    utc = datetime(2026, 6, 30, 3, 1, 16, tzinfo=timezone.utc)
    assert format_beijing_iso(utc) == "2026-06-30T11:01:16+08:00"


def test_format_beijing_display_naive_as_utc() -> None:
    naive = datetime(2026, 6, 30, 3, 1, 16)
    assert format_beijing_display(naive) == "2026-06-30 11:01:16"


def test_miniapp_admin_portal_uses_beijing_timezone() -> None:
    from pathlib import Path

    text = Path("src/shuxin/voice/miniapp_admin.py").read_text(encoding="utf-8")
    assert "Asia/Shanghai" in text
    assert "formatTime" in text
