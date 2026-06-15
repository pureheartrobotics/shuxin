"""常驻用户画像 — 不受 rolling_summary 7 日窗口限制。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_NICKNAME_PATTERNS = (
    re.compile(r"我叫([^，。,.!！?？\s]{1,20})"),
    re.compile(r"以后叫我([^，。,.!！?？\s]{1,20})"),
    re.compile(r"我的名字是([^，。,.!！?？\s]{1,20})"),
)
_LOCATION_PATTERNS = (
    re.compile(r"我住在([^，。,.!！?？\s了]{2,20})"),
    re.compile(r"我住([^，。,.!！?？\s了]{2,20})"),
    re.compile(r"(?:^|[，,])住([^，。,.!！?？\s了]{2,20})"),
    re.compile(r"住在([^，。,.!！?？\s了]{2,20})"),
    re.compile(r"我搬到([^，。,.!！?？\s了]{2,20})"),
    re.compile(r"我现在在([^，。,.!！?？\s]{2,20})"),
    re.compile(r"我搞错了，其实住([^，。,.!！?？\s]{2,20})"),
)
_PREFERENCE_PATTERNS = (
    re.compile(r"我喜欢喝([^，。,.!！?？\s]{2,20})"),
    re.compile(r"喜欢喝([^，。,.!！?？\s]{2,20})"),
    re.compile(r"我喜欢([^，。,.!！?？\s]{2,20})"),
)
_PET_PATTERN = re.compile(
    r"养了一只([^，。,.!！?？\s]{1,10})叫([^，。,.!！?？\s]{1,10})"
)
_OCCUPATION_PATTERNS = (
    re.compile(r"我是([^，。,.!！?？\s]{2,20})(?:岗位|工作|职业)"),
    re.compile(r"我做([^，。,.!！?？\s]{2,20})"),
)


def profile_path(user_home: Path) -> Path:
    return user_home / "user_profile.json"


def empty_profile() -> dict[str, Any]:
    return {
        "nickname": "",
        "location": "",
        "preferences": [],
        "pets": [],
        "occupation": "",
        "updated_at": "",
    }


def load_profile(user_home: Path) -> dict[str, Any]:
    path = profile_path(user_home)
    if not path.exists():
        return empty_profile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        merged = empty_profile()
        if isinstance(data, dict):
            merged.update(data)
        return merged
    except (OSError, json.JSONDecodeError):
        return empty_profile()


def save_profile(user_home: Path, profile: dict[str, Any]) -> None:
    user_home.mkdir(parents=True, exist_ok=True)
    profile = dict(profile)
    profile["updated_at"] = datetime.now().isoformat(timespec="seconds")
    profile_path(user_home).write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_profile_facts(text: str) -> dict[str, Any]:
    """从用户输入识别常驻画像字段（规则层，不调用 LLM）。"""
    updates: dict[str, Any] = {}
    text = (text or "").strip()
    if not text:
        return updates

    for pattern in _NICKNAME_PATTERNS:
        match = pattern.search(text)
        if match:
            updates["nickname"] = match.group(1).strip()
            break

    for pattern in _LOCATION_PATTERNS:
        match = pattern.search(text)
        if match:
            updates["location"] = match.group(1).strip()
            break

    prefs: list[str] = []
    for pattern in _PREFERENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            pref = match.group(1).strip()
            if pref and pref not in prefs:
                prefs.append(pref)
    if prefs:
        updates["preferences"] = prefs

    pet_match = _PET_PATTERN.search(text)
    if pet_match:
        updates["pets"] = [{"type": pet_match.group(1).strip(), "name": pet_match.group(2).strip()}]

    for pattern in _OCCUPATION_PATTERNS:
        match = pattern.search(text)
        if match:
            updates["occupation"] = match.group(1).strip()
            break

    return updates


def merge_profile(existing: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or empty_profile())
    for key, value in updates.items():
        if key == "preferences" and isinstance(value, list):
            current = list(merged.get("preferences") or [])
            for item in value:
                if item not in current:
                    current.append(item)
            merged["preferences"] = current
        elif key == "pets" and isinstance(value, list):
            current = list(merged.get("pets") or [])
            for pet in value:
                if pet not in current:
                    current.append(pet)
            merged["pets"] = current
        elif value:
            merged[key] = value
    return merged


def update_profile_from_text(user_home: Path, text: str) -> dict[str, Any]:
    existing = load_profile(user_home)
    updates = extract_profile_facts(text)
    if not updates:
        return existing
    merged = merge_profile(existing, updates)
    save_profile(user_home, merged)
    return merged


def format_profile_context(profile: dict[str, Any]) -> str:
    """生成注入 Slot4 的常驻画像摘要。"""
    lines = ["## 用户常驻画像"]
    nickname = str(profile.get("nickname") or "").strip()
    location = str(profile.get("location") or "").strip()
    occupation = str(profile.get("occupation") or "").strip()
    prefs = profile.get("preferences") or []
    pets = profile.get("pets") or []

    if not any([nickname, location, occupation, prefs, pets]):
        lines.append("暂无常驻画像信息。")
        return "\n".join(lines)

    if nickname:
        lines.append(f"称呼: {nickname}")
    if location:
        lines.append(f"所在地: {location}")
    if occupation:
        lines.append(f"职业/身份: {occupation}")
    if prefs:
        lines.append(f"喜好: {'、'.join(str(p) for p in prefs[:8])}")
    if pets:
        pet_strs = []
        for pet in pets[:5]:
            if isinstance(pet, dict):
                pet_strs.append(f"{pet.get('name', '')}({pet.get('type', '')})")
            else:
                pet_strs.append(str(pet))
        lines.append(f"宠物: {'、'.join(pet_strs)}")
    return "\n".join(lines)
