"""从 TTS sentence 原始文本中解析括弧动作，供屏幕/舵机使用。"""

from __future__ import annotations

import re

_ACTION_RE = re.compile(r"[\(（]([^\)）]*)[\)）]")


def extract_actions(text: str) -> list[str]:
    """Return parenthetical action phrases, preserving order."""
    return [match.strip() for match in _ACTION_RE.findall(text or "") if match.strip()]


def spoken_text(text: str) -> str:
    """Strip action parentheses so logs show what would be spoken."""
    cleaned = _ACTION_RE.sub("", text or "")
    return re.sub(r"\s{2,}", " ", cleaned).strip()
