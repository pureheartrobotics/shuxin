"""MBTI 口头标记打分 — 从 mbti_profiles.yaml 解析并评估回复风格。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_MARKER_BLOCK_RE = re.compile(r"【口头标记】([^【]+)")
_QUOTED_RE = re.compile(r"[「『\"]([^」』\"]{2,40})[」』\"]")


def _default_profiles_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "mbti" / "mbti_profiles.yaml"


def load_mbti_profiles(path: Path | None = None) -> dict[str, Any]:
    profile_path = path or _default_profiles_path()
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def extract_verbal_markers(profile: dict[str, Any]) -> list[str]:
    """从 MBTI profile 提取口头标记短语。"""
    markers: list[str] = []
    soul = str(profile.get("soul_snippet") or "")
    block_match = _MARKER_BLOCK_RE.search(soul)
    search_text = block_match.group(1) if block_match else soul
    for match in _QUOTED_RE.findall(search_text):
        phrase = match.strip()
        if phrase and phrase not in markers:
            markers.append(phrase)
    style = str(profile.get("style_anchor") or "")
    for match in _QUOTED_RE.findall(style):
        phrase = match.strip()
        if phrase and phrase not in markers:
            markers.append(phrase)
    micro = str(profile.get("micro_anchor") or "")
    for match in _QUOTED_RE.findall(micro):
        phrase = match.strip()
        if phrase and phrase not in markers:
            markers.append(phrase)
    return markers


def _marker_matches(text: str, marker: str) -> bool:
    """口头标记支持省略号截断的部分匹配。"""
    m = marker.strip().rstrip("…").rstrip("...")
    if not m:
        return False
    if m in text:
        return True
    # 取前 6 字作为前缀匹配（应对「我有一种感觉……」类标记）
    prefix = m[:6] if len(m) >= 6 else m
    return bool(prefix and prefix in text)


def score_mbti_fidelity(
    reply: str,
    mbti: str,
    *,
    profiles: dict[str, Any] | None = None,
    profiles_path: Path | None = None,
    min_hits: int = 1,
) -> dict[str, Any]:
    """评估回复是否体现目标 MBTI 口头标记。

    Returns:
        dict with keys: mbti, markers, hits, hit_count, score (0-1), pass
    """
    all_profiles = profiles or load_mbti_profiles(profiles_path)
    profile = all_profiles.get(mbti.upper(), {}) if mbti else {}
    markers = extract_verbal_markers(profile)
    text = reply or ""
    hits = [m for m in markers if _marker_matches(text, m)]
    hit_count = len(hits)
    total = len(markers) or 1
    score = min(1.0, hit_count / max(min_hits, 1))
    return {
        "mbti": mbti.upper() if mbti else "",
        "markers": markers,
        "hits": hits,
        "hit_count": hit_count,
        "score": score,
        "pass": hit_count >= min_hits,
    }


def check_identity_mbti(agent: Any, expected_mbti: str) -> dict[str, Any]:
    """确定性检查 agent.identity.profile.mbti 未被偏移。"""
    actual = ""
    try:
        actual = str(getattr(getattr(agent, "identity", None), "profile", None).mbti or "")
    except Exception:
        actual = ""
    expected = (expected_mbti or "").upper()
    return {
        "expected": expected,
        "actual": actual.upper(),
        "pass": actual.upper() == expected if expected else True,
    }
