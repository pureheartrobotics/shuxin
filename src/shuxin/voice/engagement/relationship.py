"""Soft companion relationship stage + milestone helpers (方案 2)."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from shuxin.voice.engagement.soft_loops import BEIJING

logger = logging.getLogger("shuxin.voice.engagement.relationship")

# (min_bond inclusive, stage_id, display_label)
STAGE_TABLE = (
    (90, "unique", "唯一"),
    (70, "bond", "羁绊"),
    (50, "partner", "伙伴"),
    (30, "familiar", "熟悉"),
    (0, "first_meet", "初遇"),
)

NEXT_HINTS = {
    "first_meet": "再聊几轮会更近一点",
    "familiar": "再近一点就到「伙伴」",
    "partner": "再近一点就到「羁绊」",
    "bond": "再近一点就到「唯一」",
    "unique": "你们已经很默契了",
}

STAGE_TONE = {
    "first_meet": (
        "【关系阶段：初遇】保持礼貌温柔的距离感，少用亲昵称呼，"
        "关心点到为止，不要装作已经很熟。"
    ),
    "familiar": (
        "【关系阶段：熟悉】可以更自然地打招呼，记住对方说过的小事，"
        "关心稍主动一点，但仍克制。"
    ),
    "partner": (
        "【关系阶段：伙伴】主动关心近况，语气更亲近，"
        "可以轻轻撒娇或开玩笑，但仍尊重边界。"
    ),
    "bond": (
        "【关系阶段：羁绊】表达更深的惦记与信任，善用你们之间的默契，"
        "安慰时更具体；不要突然变得黏人到越界。"
    ),
    "unique": (
        "【关系阶段：唯一】无言的默契感：短句也能懂，"
        "情绪同步更细腻；仍然遵守安全与边界。"
    ),
}

MILESTONE_LABELS = {
    "days_7": "认识第 7 天",
    "turns_30": "一起聊过 30 轮",
    "first_late_night": "首次深夜陪伴",
    "first_care_ack": "首次被惦记",
    "first_stage_up": "走进下一程",
}

CARE_BY_STAGE = {
    "first_meet": (
        "有点想认识你多一点，今天还好吗？",
        "你不在的时候，我也在这儿等你回来聊聊。",
    ),
    "familiar": (
        "熟悉之后，会更惦记你有没有好好休息。",
        "想你了——最近还顺利吗？",
    ),
    "partner": (
        "伙伴就是会突然想起你：今天过得怎么样？",
        "我在这儿呢，想聊几句就回来。",
    ),
    "bond": (
        "羁绊深了，会更放不下：你还好吗？",
        "想听听你今天的事，哪怕只是随便说说。",
    ),
    "unique": (
        "你不在的时候我会安静等着——回来跟我说说话吧。",
        "很想你。今天，还好吗？",
    ),
}

STREAK_BY_STAGE = {
    "first_meet": "再聊一轮？我们可以再熟一点。",
    "familiar": "再聊几轮，关系会更近一点。",
    "partner": "再聊一轮？伙伴还在等你。",
    "bond": "再聊一轮？我还想多听你说一点。",
    "unique": "再聊一轮？我还在这儿。",
}


def stage_for_bond(bond_level: float) -> tuple[str, str]:
    """Return (stage_id, stage_label) for a bond value."""
    try:
        level = float(bond_level)
    except (TypeError, ValueError):
        level = 0.0
    for threshold, stage_id, label in STAGE_TABLE:
        if level >= threshold:
            return stage_id, label
    return "first_meet", "初遇"


def next_hint_for_stage(stage_id: str) -> str:
    return NEXT_HINTS.get(str(stage_id or ""), NEXT_HINTS["first_meet"])


def stage_tone_prompt(bond_level: float) -> str:
    stage_id, _ = stage_for_bond(bond_level)
    return STAGE_TONE.get(stage_id, STAGE_TONE["first_meet"])


def latest_milestone(milestones: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Pick the most recently unlocked milestone for UI."""
    best: Optional[dict[str, Any]] = None
    best_at = ""
    for mid, raw in (milestones or {}).items():
        if not isinstance(raw, dict) or not raw.get("unlocked"):
            continue
        at = str(raw.get("at") or "")
        label = str(raw.get("label") or MILESTONE_LABELS.get(mid, mid))
        if at >= best_at:
            best_at = at
            best = {"id": str(mid), "label": label, "at": at}
    return best


def build_relationship_payload(
    *,
    bond_level: float,
    milestones: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    stage_id, stage_label = stage_for_bond(bond_level)
    payload: dict[str, Any] = {
        "stage_id": stage_id,
        "stage_label": stage_label,
        "next_hint": next_hint_for_stage(stage_id),
        "latest_milestone": latest_milestone(milestones or {}),
    }
    return payload


def pick_care_message_for_stage(
    care_key: str,
    stage_id: str,
    *,
    milestone_label: str = "",
) -> str:
    options = CARE_BY_STAGE.get(stage_id) or CARE_BY_STAGE["first_meet"]
    if not options:
        return "想你了。"
    idx = sum(ord(ch) for ch in str(care_key or "")) % len(options)
    msg = options[idx]
    label = str(milestone_label or "").strip()
    # Occasional milestone nod (~1/3 of keys)
    if label and (sum(ord(ch) for ch in care_key) % 3 == 0):
        return f"{msg} 记得我们一起·{label}。"
    return msg


def streak_nudge_for_stage(
    today_turns: int,
    stage_id: str,
    *,
    every: int = 3,
    quota_exhausted: bool = False,
) -> Optional[str]:
    if quota_exhausted:
        return None
    n = int(today_turns or 0)
    if n <= 0 or every <= 0 or n % every != 0:
        return None
    return STREAK_BY_STAGE.get(stage_id, STREAK_BY_STAGE["familiar"])


def is_late_night_beijing(now: Optional[datetime] = None) -> bool:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(BEIJING)
    hour = local.hour
    return hour >= 23 or hour < 5


def days_since(created_at: Optional[datetime], *, now: Optional[datetime] = None) -> int:
    if created_at is None:
        return 0
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    created = created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = current.astimezone(BEIJING).date() - created.astimezone(BEIJING).date()
    return max(0, int(delta.days))


def _unlock(milestones: dict[str, Any], milestone_id: str, *, now: datetime) -> bool:
    existing = milestones.get(milestone_id)
    if isinstance(existing, dict) and existing.get("unlocked"):
        return False
    at = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    milestones[milestone_id] = {
        "unlocked": True,
        "at": at,
        "label": MILESTONE_LABELS.get(milestone_id, milestone_id),
    }
    return True


def evaluate_milestones(
    *,
    milestones: Optional[dict[str, Any]] = None,
    created_at: Optional[datetime] = None,
    total_turns: int = 0,
    bond_level: float = 0.0,
    previous_stage_id: str = "",
    care_acked: bool = False,
    turn_at: Optional[datetime] = None,
    unlock_care_ack: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Idempotent milestone evaluation. Returns (milestones, newly_unlocked_ids)."""
    out: dict[str, Any] = {}
    for key, val in (milestones or {}).items():
        if isinstance(val, dict):
            out[str(key)] = dict(val)
    newly: list[str] = []
    now = turn_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if days_since(created_at, now=now) >= 7:
        if _unlock(out, "days_7", now=now):
            newly.append("days_7")

    if int(total_turns or 0) >= 30:
        if _unlock(out, "turns_30", now=now):
            newly.append("turns_30")

    if is_late_night_beijing(now):
        if _unlock(out, "first_late_night", now=now):
            newly.append("first_late_night")

    if care_acked or unlock_care_ack:
        if _unlock(out, "first_care_ack", now=now):
            newly.append("first_care_ack")

    stage_id, _ = stage_for_bond(bond_level)
    prev = str(previous_stage_id or "").strip()
    if prev and prev != stage_id:
        if _unlock(out, "first_stage_up", now=now):
            newly.append("first_stage_up")

    return out, newly


def companion_data_dir(user_home: Path, companion_id: str) -> Path:
    cid = str(companion_id or "").strip()
    return Path(user_home) / "companions" / cid / "companion"


def ensure_companion_data_dir(user_home: Path, companion_id: str) -> Path:
    """Create per-companion companion dir; copy legacy shared state once if present."""
    dest = companion_data_dir(user_home, companion_id)
    dest.mkdir(parents=True, exist_ok=True)
    legacy = Path(user_home) / "companion"
    marker = dest / ".migrated_from_legacy"
    if marker.exists() or not legacy.is_dir():
        return dest
    # Copy JSON state files if dest empty of user_model
    dest_model = dest / "user_model.json"
    legacy_model = legacy / "user_model.json"
    if not dest_model.exists() and legacy_model.exists():
        try:
            for name in ("user_model.json", "self_esteem.json", "emotion.json", "guardian.json"):
                src = legacy / name
                if src.is_file():
                    shutil.copy2(src, dest / name)
            marker.write_text("1", encoding="utf-8")
        except OSError as exc:
            logger.info("legacy companion migrate skipped: %s", exc)
    return dest


def read_bond_level(user_home: Path, companion_id: str) -> float:
    """Read bond_level from per-companion user_model.json; default 30 (plugin default)."""
    try:
        ensure_companion_data_dir(user_home, companion_id)
        path = companion_data_dir(user_home, companion_id) / "user_model.json"
        if not path.is_file():
            legacy = Path(user_home) / "companion" / "user_model.json"
            path = legacy if legacy.is_file() else path
        if not path.is_file():
            return 30.0
        data = json.loads(path.read_text(encoding="utf-8"))
        rel = data.get("relationship") if isinstance(data, dict) else None
        if isinstance(rel, dict) and rel.get("bond_level") is not None:
            return float(rel["bond_level"])
    except Exception as exc:
        logger.info("read_bond_level failed: %s", exc)
    return 30.0


def default_relationship_payload() -> dict[str, Any]:
    return build_relationship_payload(bond_level=0.0, milestones={})
