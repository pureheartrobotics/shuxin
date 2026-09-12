"""Agent records for voice TTS and persona injection."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

AGENT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
DEFAULT_AGENT_ID = "shuxin"
AGENT_CACHE_TTL_SECONDS = 30.0

_agent_cache: dict[str, tuple[float, AgentRecord]] = {}


@dataclass(frozen=True)
class AgentRecord:
    agent_id: str
    display_name: str = ""
    voice_type: str = ""
    cluster: str = "volcano_icl"
    speed_ratio: float = 1.0
    encoding: str = "mp3"
    uid: str = ""
    soul_path: str = ""
    initial_state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

    @classmethod
    def from_row(cls, row: Any) -> AgentRecord:
        initial_state = row["initial_state"]
        metadata = row["metadata"]
        if isinstance(initial_state, str):
            import json

            initial_state = json.loads(initial_state) if initial_state else {}
        if isinstance(metadata, str):
            import json

            metadata = json.loads(metadata) if metadata else {}
        return cls(
            agent_id=str(row["agent_id"]),
            display_name=str(row["display_name"] or ""),
            voice_type=str(row["voice_type"] or ""),
            cluster=str(row["cluster"] or "volcano_icl"),
            speed_ratio=float(row["speed_ratio"] or 1.0),
            encoding=str(row["encoding"] or "mp3"),
            uid=str(row["uid"] or row["agent_id"]),
            soul_path=str(row["soul_path"] or ""),
            initial_state=dict(initial_state or {}),
            metadata=dict(metadata or {}),
            enabled=bool(row["enabled"]),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "voice_type": _mask_voice_type(self.voice_type),
            "voice_type_configured": bool(self.voice_type.strip()),
            "cluster": self.cluster,
            "speed_ratio": self.speed_ratio,
            "encoding": self.encoding,
            "uid": self.uid,
            "soul_path": self.soul_path,
            "initial_state": self.initial_state,
            "metadata": self.metadata,
            "enabled": self.enabled,
        }

    def to_admin_dict(self) -> dict[str, Any]:
        data = self.to_public_dict()
        data["voice_type"] = self.voice_type
        return data


def _mask_voice_type(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}...{text[-4:]}"


def cache_agent(record: AgentRecord) -> None:
    _agent_cache[record.agent_id] = (time.monotonic(), record)


def get_cached_agent(agent_id: str) -> AgentRecord | None:
    entry = _agent_cache.get(agent_id)
    if entry is None:
        return None
    cached_at, record = entry
    if time.monotonic() - cached_at > AGENT_CACHE_TTL_SECONDS:
        _agent_cache.pop(agent_id, None)
        return None
    return record


def invalidate_agent_cache(agent_id: str | None = None) -> None:
    if agent_id:
        _agent_cache.pop(agent_id, None)
    else:
        _agent_cache.clear()
