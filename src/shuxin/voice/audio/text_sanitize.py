"""语音 TTS 可读性清洗 — 剥离括弧动作与 Markdown 标记。

sentence_start/stop 仍携带原始文本供硬件动作触发；本模块仅用于 TTS 合成输入。
"""

from __future__ import annotations

import re

_COMPLETE_PAREN_RE = re.compile(r"[\(（][^\)）]*[\)）]")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_UNDERLINE_BOLD_RE = re.compile(r"__(.+?)__")
_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_ITALIC_UNDER_RE = re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_STRAY_MARKDOWN_RE = re.compile(r"[*_`]+")
_EXTRA_SPACE_RE = re.compile(r"\s{2,}")


def _strip_unclosed_parenthesis(text: str) -> str:
    """去掉段首/段尾未闭合的括弧片段（流式截断或模型漏写 closing 时）。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    last_open = max(cleaned.rfind("("), cleaned.rfind("（"))
    if last_open > 0:
        tail = cleaned[last_open:]
        if ")" not in tail and "）" not in tail:
            cleaned = cleaned[:last_open].strip()

    if cleaned and cleaned[0] in "(（" and has_unclosed_parenthesis(cleaned):
        last_space = cleaned.rfind(" ")
        cleaned = cleaned[last_space + 1 :].lstrip() if last_space > 0 else ""
    return cleaned.strip()


def clean_action_text(text: str) -> str:
    """去除中英文括号及其包含的动作文本（含未闭合括弧片段）。"""
    cleaned = _COMPLETE_PAREN_RE.sub("", text or "")
    cleaned = _strip_unclosed_parenthesis(cleaned)
    return cleaned.strip()


def strip_markdown_for_tts(text: str) -> str:
    """剥离常见 Markdown 标记，避免 TTS 朗读星号等符号。"""
    cleaned = text or ""
    for pattern in (
        _BOLD_RE,
        _UNDERLINE_BOLD_RE,
        _ITALIC_STAR_RE,
        _ITALIC_UNDER_RE,
        _INLINE_CODE_RE,
    ):
        cleaned = pattern.sub(r"\1", cleaned)
    cleaned = _STRAY_MARKDOWN_RE.sub("", cleaned)
    cleaned = _EXTRA_SPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def prepare_speakable_text(text: str) -> str:
    """TTS 合成前的最终可读文本：去括弧动作 + 去 Markdown；无实质可读内容则空串。"""
    cleaned = strip_markdown_for_tts(clean_action_text(text)).strip()
    if not has_readable_tts_text(cleaned):
        return ""
    return cleaned


_READABLE_TTS_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


def has_readable_tts_text(text: str) -> bool:
    """火山等 TTS 需要至少一字/字母/数字；纯引号标点会触发 3011 No readable text。"""
    return bool(_READABLE_TTS_RE.search(text or ""))


def has_unclosed_parenthesis(text: str) -> bool:
    """buffer 中是否存在未闭合的中英文括号。"""
    depth = 0
    for char in text:
        if char in ("(", "（"):
            depth += 1
        elif char in (")", "）"):
            depth = max(0, depth - 1)
    return depth > 0
