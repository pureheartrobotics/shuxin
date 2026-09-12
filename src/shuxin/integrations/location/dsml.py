"""DeepSeek DSML 工具调用解析与剥离。

部分 OpenAI 兼容代理（如 dmxapi + deepseek-v4-flash）将 tool call 写在
content 的 DSML 块中，而非标准 tool_calls 字段。
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import List

# ｜ = U+FF5C；模型输出可能是 <｜DSML｜ 或 <｜｜DSML｜｜
_DSML_MARKER = r"[<＜]?[｜|]+DSML[｜|]+"
_DSML_TOOL_CALLS_BLOCK = re.compile(
    rf"{_DSML_MARKER}tool_calls[^>]*>.*?</[｜|]+DSML[｜|]+tool_calls>",
    re.DOTALL,
)
_DSML_INVOKE = re.compile(
    rf"{_DSML_MARKER}invoke\s+name=\"([^\"]+)\"[^>]*>(.*?)</[｜|]+DSML[｜|]+invoke>",
    re.DOTALL,
)
_DSML_PARAMETER = re.compile(
    rf"{_DSML_MARKER}parameter\s+name=\"([^\"]+)\"[^>]*>(.*?)</[｜|]+DSML[｜|]+parameter>",
    re.DOTALL,
)

DSML_TOOL_CALLS_OPEN = "｜DSML｜tool_calls>"
DSML_TOOL_CALLS_CLOSE = "</｜DSML｜tool_calls>"


@dataclass
class DsmlToolCall:
    id: str
    name: str
    arguments: str


def strip_dsml_blocks(text: str) -> str:
    """移除 content 中的完整 DSML tool_calls 块。"""
    if not text:
        return ""
    cleaned = _DSML_TOOL_CALLS_BLOCK.sub("", text)
    # 兜底：剥离未闭合或残缺块起始之后的文本
    idx = cleaned.find(DSML_TOOL_CALLS_OPEN)
    if idx == -1:
        idx = cleaned.find("DSML｜tool_calls>")
    if idx != -1:
        cleaned = cleaned[:idx]
    return cleaned.rstrip()


def _parse_invoke_arguments(invoke_body: str) -> dict:
    args: dict = {}
    for match in _DSML_PARAMETER.finditer(invoke_body):
        key = match.group(1).strip()
        value = match.group(2).strip()
        if key == "is_chinese_mainland":
            args[key] = value.lower() in ("true", "1", "yes")
        else:
            args[key] = value
    # 保留 DSML 原始参数；map_weather 等在 agent tool loop 中归一化
    return args


def extract_dsml_tool_calls(content: str) -> List[DsmlToolCall]:
    """从 assistant content 提取 DSML 工具调用。"""
    if not content or "DSML" not in content:
        return []

    calls: List[DsmlToolCall] = []
    for match in _DSML_INVOKE.finditer(content):
        name = match.group(1).strip()
        if not name:
            continue
        args = _parse_invoke_arguments(match.group(2))
        calls.append(
            DsmlToolCall(
                id=f"dsml_{uuid.uuid4().hex[:12]}",
                name=name,
                arguments=json.dumps(args, ensure_ascii=False),
            )
        )
    return calls


class DsmlStreamFilter:
    """流式状态机：剥离 DSML tool_calls 块（支持跨 chunk）。"""

    def __init__(self) -> None:
        self._in_dsml = False
        self._buf = ""

    @staticmethod
    def _partial_suffix(text: str, tag: str) -> int:
        max_keep = min(len(text), len(tag) - 1)
        for keep in range(max_keep, 0, -1):
            if text.endswith(tag[:keep]):
                return keep
        return 0

    def _find_open(self, text: str) -> int:
        for marker in (DSML_TOOL_CALLS_OPEN, "DSML｜tool_calls>"):
            pos = text.find(marker)
            if pos != -1:
                return pos
        # 可能正在输入 "<｜｜DSML" 前缀
        for marker in ("<｜｜DSML", "<｜DSML", "DSML｜tool_calls"):
            pos = text.find(marker)
            if pos != -1:
                return pos
        return -1

    def feed(self, text: str) -> str:
        """Feed a chunk; return speakable text (may be empty)."""
        self._buf += text
        out_parts: list[str] = []
        while True:
            if self._in_dsml:
                end = self._buf.find(DSML_TOOL_CALLS_CLOSE)
                if end == -1:
                    keep = self._partial_suffix(self._buf, DSML_TOOL_CALLS_CLOSE)
                    self._buf = self._buf[len(self._buf) - keep :]
                    break
                self._buf = self._buf[end + len(DSML_TOOL_CALLS_CLOSE) :]
                self._in_dsml = False
            else:
                start = self._find_open(self._buf)
                if start == -1:
                    keep = self._partial_suffix(self._buf, DSML_TOOL_CALLS_OPEN)
                    out_parts.append(self._buf[: len(self._buf) - keep])
                    self._buf = self._buf[len(self._buf) - keep :]
                    break
                out_parts.append(self._buf[:start])
                self._buf = self._buf[start:]
                # 跳到开标签结束
                close_bracket = self._buf.find(">")
                if close_bracket == -1:
                    break
                self._buf = self._buf[close_bracket + 1 :]
                self._in_dsml = True
        return "".join(out_parts)
