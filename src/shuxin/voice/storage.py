from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from shuxin.voice.memory_summary import (
    SUMMARY_WINDOW_DAYS,
    apply_turn_to_summary,
    finalize_summary_after_merge,
    merge_summary_with_llm,
    merge_summary_with_stats,
    memory_field_defaults,
    should_merge_summary,
    sync_summary_json,
)
from shuxin.voice.audio_files import purge_attachment_file
from shuxin.voice.config import DeviceConfig
from shuxin.voice.users import UserSettings, validate_user_id

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
COMPRESS_TARGET_RATIO = 0.8


@dataclass(frozen=True)
class VoiceTurnPaths:
    """一轮语音对话涉及的落盘路径。

    session_id 用来把同一次 WebSocket 会话的多轮语音归组，turn_id
    用来唯一定位单轮输入录音和回复音频。
    """

    session_id: str
    turn_id: str
    session_dir: Path
    input_wav: Path
    reply_mp3: Path


class UserVoiceStorage:
    """语音 Web 路径的用户级存储门面。

    每个 user_id 都有独立的初心 home、事件库、长期记忆、陪伴状态和
    音频附件目录。这样同一用户跨设备共享记忆，不同用户之间互不污染。
    """

    def __init__(self, shuxin_home: Path, outputs_root: Path, user_id: str) -> None:
        self.user_id = validate_user_id(user_id)
        self.user_root = shuxin_home / "users" / self.user_id
        self.outputs_root = outputs_root / "users" / self.user_id
        self.events_dir = self.user_root / "events"
        self.summaries_dir = self.user_root / "summaries"
        self.companion_dir = self.user_root / "companion"
        self.memory_dir = self.user_root / "memory"
        self.db_path = self.events_dir / "events.sqlite3"
        self._lock = asyncio.Lock()
        self._ensure_layout()
        self._init_db()

    def user_shuxin_home(self) -> Path:
        """返回该用户专属的 ChuXin home，用于初始化 Agent 和记忆目录。"""
        return self.user_root

    def companion_data_dir(self) -> Path:
        """返回陪伴插件的用户级持久化目录。"""
        return self.companion_dir

    def new_turn_paths(self, device_id: str, session_id: str | None = None) -> VoiceTurnPaths:
        """为新一轮语音交互生成安全的附件路径。"""
        safe_device = validate_path_part(device_id)
        selected_session = validate_path_part(session_id or uuid.uuid4().hex)
        turn_id = uuid.uuid4().hex
        session_dir = self.outputs_root / safe_device / selected_session
        session_dir.mkdir(parents=True, exist_ok=True)
        return VoiceTurnPaths(
            session_id=selected_session,
            turn_id=turn_id,
            session_dir=session_dir,
            input_wav=session_dir / f"input-{turn_id}.wav",
            reply_mp3=session_dir / f"reply-{turn_id}.mp3",
        )

    def write_input_wav(self, pcm: bytes, path: Path) -> None:
        """把浏览器/硬件上行的裸 PCM16 音频封装成 wav 文件。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(CHANNELS)
            wav.setsampwidth(SAMPLE_WIDTH)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm)

    async def record_turn(
        self,
        *,
        user_settings: UserSettings,
        device_id: str,
        client_id: str,
        session_id: str,
        turn_id: str,
        user_text: str,
        reply_text: str,
        input_audio: Path | None,
        reply_audio: Path | None,
        timings: dict[str, int],
        warning: str = "",
    ) -> None:
        """记录一轮对话事件、音频附件、简单事实和共享记忆摘要。"""
        async with self._lock:
            now = _now()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO events (
                        event_id, user_id, device_id, client_id, session_id, turn_id,
                        event_type, user_text, reply_text, metadata_json, created_at, deleted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        uuid.uuid4().hex,
                        self.user_id,
                        device_id,
                        client_id,
                        session_id,
                        turn_id,
                        "conversation_turn",
                        user_text,
                        reply_text,
                        json.dumps(
                            {"timings": timings, "warning": warning},
                            ensure_ascii=False,
                        ),
                        now,
                    ),
                )
                if input_audio and input_audio.exists():
                    self._insert_attachment(
                        conn,
                        turn_id=turn_id,
                        kind="input",
                        path=input_audio,
                        media_type="audio/wav",
                        compressed=False,
                    )
                if reply_audio and reply_audio.exists():
                    self._insert_attachment(
                        conn,
                        turn_id=turn_id,
                        kind="reply",
                        path=reply_audio,
                        media_type="audio/mpeg",
                        compressed=True,
                    )
                self._update_facts_from_text(user_text)
                self._update_summary_locked(
                    conn,
                    user_settings=user_settings,
                    warning=warning,
                    user_text=user_text,
                )

    async def status(self, user_settings: UserSettings) -> dict[str, Any]:
        """返回用户当前音频额度、已用空间、后台任务和告警摘要。"""
        async with self._lock:
            with self._connect() as conn:
                used = self._attachment_total_bytes(conn)
                warnings = [
                    row[0]
                    for row in conn.execute(
                        "SELECT message FROM warnings ORDER BY created_at DESC LIMIT 10"
                    )
                ]
                pending_jobs = conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE state IN ('pending', 'running')"
                ).fetchone()[0]
            return {
                "user_id": self.user_id,
                "audio_quota_bytes": user_settings.audio_quota_bytes,
                "audio_used_bytes": used,
                "over_quota": used > user_settings.audio_quota_bytes,
                "pending_jobs": pending_jobs,
                "warnings": warnings,
            }

    async def compress_if_needed(self, user_settings: UserSettings) -> dict[str, Any]:
        """如果超过用户音频额度，把旧输入 wav 压缩为 mp3。"""
        async with self._lock:
            return self._compress_if_needed_locked(user_settings)

    async def purge_expired_audio_attachments(self, *, retention_hours: int) -> dict[str, int]:
        """Delete audio files older than retention_hours and soft-delete attachment rows."""
        if retention_hours <= 0:
            return {"purged": 0, "bytes_freed": 0}
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=retention_hours)).replace(
            tzinfo=None
        ).isoformat(timespec="seconds")
        async with self._lock:
            return self._purge_expired_attachments_locked(cutoff)

    def export_summary(self) -> dict[str, Any]:
        """导出用户共享记忆摘要，供调试页或后台接口查看。"""
        summary_path = self.summaries_dir / "shared_memory.json"
        if not summary_path.exists():
            return {}
        return json.loads(summary_path.read_text(encoding="utf-8"))

    def _ensure_layout(self) -> None:
        """创建用户目录结构，并初始化人格成长和共享记忆文件。"""
        for directory in [
            self.user_root,
            self.outputs_root,
            self.events_dir,
            self.summaries_dir,
            self.companion_dir,
            self.memory_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)
        personality_path = self.companion_dir / "personality.json"
        if not personality_path.exists():
            personality_path.write_text(
                json.dumps(_initial_personality(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        summary_path = self.summaries_dir / "shared_memory.json"
        if not summary_path.exists():
            summary_path.write_text(
                json.dumps(_initial_summary(self.user_id), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _connect(self) -> sqlite3.Connection:
        """打开事件库连接，并启用 WAL 和外键约束。"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        """初始化事件、附件、告警和后台任务表。"""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    user_text TEXT NOT NULL DEFAULT '',
                    reply_text TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS attachments (
                    attachment_id TEXT PRIMARY KEY,
                    turn_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    compressed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS warnings (
                    warning_id TEXT PRIMARY KEY,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _insert_attachment(
        self,
        conn: sqlite3.Connection,
        *,
        turn_id: str,
        kind: str,
        path: Path,
        media_type: str,
        compressed: bool,
    ) -> None:
        """把音频文件作为附件登记到事件库，记录大小和哈希。"""
        conn.execute(
            """
            INSERT INTO attachments (
                attachment_id, turn_id, kind, path, media_type, size_bytes,
                sha256, compressed, created_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                uuid.uuid4().hex,
                turn_id,
                kind,
                str(path),
                media_type,
                path.stat().st_size,
                _sha256(path),
                1 if compressed else 0,
                _now(),
            ),
        )

    def _compress_if_needed_locked(self, user_settings: UserSettings) -> dict[str, Any]:
        """在持有锁时执行额度压缩。

        压缩策略保持保守: 只压缩最早的原始输入 wav，回复 mp3 不再二次处理；
        如果压缩后仍超额，写入 warning 并把 job 标记为 pending。
        """
        with self._connect() as conn:
            used = self._attachment_total_bytes(conn)
            quota = user_settings.audio_quota_bytes
            if used <= quota:
                return {"compressed": 0, "used_bytes": used, "over_quota": False}

            self._upsert_job(conn, "audio_compression", "running", {"used_bytes": used})
            compressed_count = 0
            target = int(quota * COMPRESS_TARGET_RATIO)

            rows = conn.execute(
                """
                SELECT attachment_id, path
                FROM attachments
                WHERE deleted_at IS NULL
                  AND kind = 'input'
                  AND compressed = 0
                ORDER BY created_at ASC
                """
            ).fetchall()
            for attachment_id, raw_path in rows:
                if used <= target:
                    break
                path = Path(raw_path)
                if not path.exists():
                    conn.execute(
                        "UPDATE attachments SET deleted_at = ? WHERE attachment_id = ?",
                        (_now(), attachment_id),
                    )
                    continue

                compressed_path = path.with_suffix(".mp3")
                _compress_wav_to_mp3(path, compressed_path)
                old_size = path.stat().st_size
                path.unlink(missing_ok=True)
                new_size = compressed_path.stat().st_size
                conn.execute(
                    """
                    UPDATE attachments
                    SET path = ?, media_type = ?, size_bytes = ?, sha256 = ?, compressed = 1
                    WHERE attachment_id = ?
                    """,
                    (
                        str(compressed_path),
                        "audio/mpeg",
                        new_size,
                        _sha256(compressed_path),
                        attachment_id,
                    ),
                )
                used = used - old_size + new_size
                compressed_count += 1

            over_quota = used > quota
            if over_quota:
                self._insert_warning(
                    conn,
                    f"user {self.user_id} audio attachments remain over quota after compression",
                )
            self._upsert_job(
                conn,
                "audio_compression",
                "pending" if over_quota else "done",
                {"used_bytes": used, "compressed": compressed_count},
            )
            return {
                "compressed": compressed_count,
                "used_bytes": used,
                "over_quota": over_quota,
            }

    def _purge_expired_attachments_locked(self, cutoff: str) -> dict[str, int]:
        purged = 0
        bytes_freed = 0
        now = _now()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT attachment_id, path, size_bytes
                FROM attachments
                WHERE deleted_at IS NULL
                  AND created_at < ?
                ORDER BY created_at ASC, attachment_id ASC
                """,
                (cutoff,),
            ).fetchall()
            for attachment_id, raw_path, size_bytes in rows:
                path = Path(str(raw_path))
                if path.exists():
                    bytes_freed += purge_attachment_file(path, stop_at=self.outputs_root)
                else:
                    bytes_freed += int(size_bytes or 0)
                conn.execute(
                    "UPDATE attachments SET deleted_at = ? WHERE attachment_id = ?",
                    (now, attachment_id),
                )
                purged += 1
        return {"purged": purged, "bytes_freed": bytes_freed}

    def _attachment_total_bytes(self, conn: sqlite3.Connection) -> int:
        """统计未删除附件的总字节数，用于额度判断。"""
        row = conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM attachments WHERE deleted_at IS NULL"
        ).fetchone()
        return int(row[0] or 0)

    def _load_summary_locked(self) -> dict[str, Any]:
        summary_path = self.summaries_dir / "shared_memory.json"
        if not summary_path.exists():
            return {**_initial_summary(self.user_id), **memory_field_defaults()}
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {**_initial_summary(self.user_id), **memory_field_defaults()}

    def _update_summary_locked(
        self,
        conn: sqlite3.Connection,
        *,
        user_settings: UserSettings,
        warning: str,
        user_text: str = "",
    ) -> None:
        """根据事件库当前状态刷新共享记忆摘要文件。"""
        event_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE deleted_at IS NULL"
        ).fetchone()[0]
        attachment_bytes = self._attachment_total_bytes(conn)
        existing = self._load_summary_locked()
        stats = {
            "user_id": self.user_id,
            "turn_count": int(event_count),
            "last_interaction_at": _now(),
            "audio_quota_bytes": user_settings.audio_quota_bytes,
            "audio_used_bytes": attachment_bytes,
            "over_quota": attachment_bytes > user_settings.audio_quota_bytes,
            "last_warning": warning,
            "milestones": existing.get("milestones") or [],
        }
        summary = merge_summary_with_stats(existing, stats)
        if user_text.strip():
            summary = apply_turn_to_summary(summary, user_text)
        self._write_summary_locked(summary)

    def _write_summary_locked(self, summary: dict[str, Any]) -> None:
        (self.summaries_dir / "shared_memory.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        sync_summary_json(self.user_id, summary)

    def _recent_turns_locked(
        self,
        conn: sqlite3.Connection,
        *,
        limit: int = 15,
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT user_text, reply_text, created_at
            FROM events
            WHERE deleted_at IS NULL
              AND datetime(created_at) >= datetime('now', ?)
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (f"-{SUMMARY_WINDOW_DAYS} days", limit),
        ).fetchall()
        return [
            {"user_text": row[0], "reply_text": row[1], "created_at": row[2]}
            for row in reversed(rows)
        ]

    async def maybe_merge_rolling_summary(
        self,
        device: DeviceConfig | None,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        async with self._lock:
            summary = self._load_summary_locked()
            if not should_merge_summary(summary, force=force):
                return {"merged": False, "reason": "not_due"}
            recent_turns = []
            with self._connect() as conn:
                recent_turns = self._recent_turns_locked(conn)
            loop = asyncio.get_event_loop()
            merged_text = await loop.run_in_executor(
                None,
                lambda: merge_summary_with_llm(
                    device=device,
                    existing_summary=str(summary.get("rolling_summary") or ""),
                    recent_topics=list(summary.get("recent_topics") or []),
                    recent_turns=recent_turns,
                ),
            )
            summary = finalize_summary_after_merge(summary, merged_text)
            self._write_summary_locked(summary)
            return {"merged": True, "summary_updated_at": summary.get("summary_updated_at")}

    def _insert_warning(self, conn: sqlite3.Connection, message: str) -> None:
        """记录需要后台或人工关注的存储告警。"""
        conn.execute(
            "INSERT INTO warnings (warning_id, message, created_at) VALUES (?, ?, ?)",
            (uuid.uuid4().hex, message, _now()),
        )

    def _update_facts_from_text(self, text: str) -> None:
        """从用户文本中抽取最小可用事实，写入该用户长期记忆。

        这里先用规则兜底常见偏好和称呼，后续可以替换为更完整的
        记忆抽取器，但文件格式继续复用 core.memory 的 facts.json。
        """
        updates: list[tuple[str, str, str]] = []
        for pattern, key_prefix, category in [
            (r"我喜欢([^，。,.!！?？]{1,30})", "喜欢", "preference"),
            (r"我不喜欢([^，。,.!！?？]{1,30})", "不喜欢", "preference"),
            (r"我叫([^，。,.!！?？]{1,20})", "名字", "general"),
            (r"以后叫我([^，。,.!！?？]{1,20})", "称呼", "general"),
        ]:
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                if value:
                    updates.append((key_prefix, value, category))
        if not updates:
            return

        facts_path = self.memory_dir / "facts.json"
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
            if not isinstance(facts, list):
                facts = []
        except (OSError, json.JSONDecodeError):
            facts = []

        by_key = {item.get("key"): item for item in facts if isinstance(item, dict)}
        now = _now()
        for key, value, category in updates:
            existing = by_key.get(key)
            if existing:
                existing["value"] = value
                existing["category"] = category
                existing["confidence"] = 1.0
                existing["updated_at"] = now
            else:
                by_key[key] = {
                    "key": key,
                    "value": value,
                    "category": category,
                    "confidence": 1.0,
                    "created_at": now,
                    "updated_at": now,
                }

        facts_path.write_text(
            json.dumps(list(by_key.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _upsert_job(
        self,
        conn: sqlite3.Connection,
        job_type: str,
        state: str,
        metadata: dict[str, Any],
    ) -> None:
        """创建或更新单用户后台任务状态。"""
        job_id = f"{self.user_id}:{job_type}"
        now = _now()
        conn.execute(
            """
            INSERT INTO jobs (job_id, job_type, state, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                state = excluded.state,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (job_id, job_type, state, json.dumps(metadata), now, now),
        )


def validate_path_part(value: str) -> str:
    """复用 user_id 校验规则，避免 device/session 路径穿越。"""
    return validate_user_id(value or "default")


def _compress_wav_to_mp3(input_path: Path, output_path: Path) -> None:
    """调用 ffmpeg 把输入 wav 压缩成低码率 mono mp3。"""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for audio compression")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-b:a",
            "32k",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _sha256(path: Path) -> str:
    """计算附件哈希，方便后续校验或去重。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    """生成秒级 ISO 时间戳，保持 JSON 和 SQLite 中的时间格式一致。"""
    return datetime.now().isoformat(timespec="seconds")


def _initial_personality() -> dict[str, Any]:
    """生成用户初次见面时的人格成长初始状态。"""
    return {
        "traits": {
            "warmth": 0.6,
            "initiative": 0.35,
            "playfulness": 0.25,
            "assertiveness": 0.45,
            "curiosity": 0.5,
            "emotional_openness": 0.35,
            "formality": 0.55,
            "ritual_attachment": 0.2,
        },
        "stage": "初遇",
        "milestones": [],
        "shared_rituals": [],
        "nicknames": [],
        "inside_jokes": [],
    }


def _initial_summary(user_id: str) -> dict[str, Any]:
    """生成用户共享记忆摘要的初始结构。"""
    return {
        "user_id": user_id,
        "turn_count": 0,
        "last_interaction_at": "",
        "audio_quota_bytes": 0,
        "audio_used_bytes": 0,
        "over_quota": False,
        "last_warning": "",
        "milestones": [],
        **memory_field_defaults(),
    }
