from __future__ import annotations

import json
import uuid
import logging
import asyncio
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

logger = logging.getLogger("shuxin.voice.postgres")

from shuxin.voice.persistence.base_repo import (
    BaseRepository,
    _dt,
    _json_obj,
    _user_outputs_root,
)
from shuxin.voice.persistence.users import UserSettings
from shuxin.voice.config.config import DeviceConfig
from shuxin.voice.audio.audio_files import compress_wav_to_mp3, purge_attachment_file, sha256_file
from shuxin.voice.persistence.memory_summary import (
    SUMMARY_WINDOW_DAYS,
    apply_turn_to_summary,
    finalize_summary_after_merge,
    merge_summary_with_llm,
    merge_summary_with_stats,
    memory_field_defaults,
    should_merge_summary,
    sync_summary_json,
)

COMPRESS_TARGET_RATIO = 0.8

def _extract_facts(text: str) -> list[tuple[str, str, str]]:
    """Extract key facts from text. Defaults to empty list for safety."""
    return []


class MemoryRepository(BaseRepository):
    """Session Memory and Audio Attachment Persistence Repository."""

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
        timings: dict[str, Any],
        warning: str = "",
        companion_id: str = "",
        channel: str = "",
    ) -> None:
        meta: dict[str, Any] = {"timings": timings, "warning": warning}
        cid = str(companion_id or "").strip()
        ch = str(channel or "").strip()
        if cid:
            meta["companion_id"] = cid
        if ch:
            meta["channel"] = ch
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO conversation_events (
                        event_id, user_id, device_id, session_id, turn_id, event_type,
                        user_text, reply_text, metadata
                    )
                    VALUES ($1, $2, $3, $4, $5, 'conversation_turn', $6, $7, $8::jsonb)
                    """,
                    uuid.uuid4().hex,
                    user_settings.user_id,
                    device_id,
                    session_id,
                    turn_id,
                    user_text,
                    reply_text,
                    json.dumps(meta, ensure_ascii=False),
                )
                for kind, path, media_type, compressed in [
                    ("input", input_audio, "audio/wav", False),
                    ("reply", reply_audio, "audio/mpeg", True),
                ]:
                    if path and path.exists():
                        await self._insert_attachment(
                            conn,
                            user_id=user_settings.user_id,
                            device_id=device_id,
                            session_id=session_id,
                            turn_id=turn_id,
                            kind=kind,
                            path=path,
                            media_type=media_type,
                            compressed=compressed,
                        )
                await self._upsert_facts_from_text(conn, user_settings.user_id, user_text)
                await self._refresh_shared_memory(
                    conn,
                    user_settings,
                    warning,
                    user_text=user_text,
                )

    async def list_companion_chat_history(
        self,
        *,
        user_id: str,
        companion_id: str,
        limit: int = 50,
        before: str = "",
    ) -> dict[str, Any]:
        """按 companion_id 拉取文字+语音回合，展平为气泡列表（时间正序）。"""
        cid = str(companion_id or "").strip()
        uid = str(user_id or "").strip()
        if not uid or not cid:
            return {"messages": [], "companion_id": cid}
        lim = max(1, min(int(limit or 50), 100))
        before_ts = str(before or "").strip() or None
        async with self.pool.acquire() as conn:
            if before_ts:
                rows = await conn.fetch(
                    """
                    SELECT user_text, reply_text, metadata, created_at
                    FROM conversation_events
                    WHERE user_id = $1
                      AND deleted_at IS NULL
                      AND event_type = 'conversation_turn'
                      AND metadata->>'companion_id' = $2
                      AND created_at < $3::timestamptz
                    ORDER BY created_at DESC
                    LIMIT $4
                    """,
                    uid,
                    cid,
                    before_ts,
                    lim,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT user_text, reply_text, metadata, created_at
                    FROM conversation_events
                    WHERE user_id = $1
                      AND deleted_at IS NULL
                      AND event_type = 'conversation_turn'
                      AND metadata->>'companion_id' = $2
                    ORDER BY created_at DESC
                    LIMIT $3
                    """,
                    uid,
                    cid,
                    lim,
                )
        messages: list[dict[str, Any]] = []
        turns: list[dict[str, Any]] = []
        for row in reversed(list(rows)):
            meta = _json_obj(row["metadata"])
            created = row["created_at"]
            created_s = (
                created.isoformat().replace("+00:00", "Z")
                if hasattr(created, "isoformat")
                else str(created or "")
            )
            channel = str(meta.get("channel") or "").strip()
            user_text = str(row["user_text"] or "").strip()
            reply_text = str(row["reply_text"] or "").strip()
            turns.append(
                {
                    "user_text": user_text,
                    "reply_text": reply_text,
                    "created_at": created_s,
                    "channel": channel,
                }
            )
            if user_text:
                messages.append(
                    {
                        "role": "user",
                        "text": user_text,
                        "created_at": created_s,
                        "channel": channel,
                    }
                )
            if reply_text:
                messages.append(
                    {
                        "role": "assistant",
                        "text": reply_text,
                        "created_at": created_s,
                        "channel": channel,
                    }
                )
        return {
            "companion_id": cid,
            "messages": messages,
            "turns": turns,
        }

    async def status(self, user_settings: UserSettings) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            used = await self._attachment_total_bytes(conn, user_settings.user_id)
            summary = await conn.fetchval(
                "SELECT summary FROM shared_memory WHERE user_id = $1",
                user_settings.user_id,
            )
        return {
            "user_id": user_settings.user_id,
            "audio_quota_bytes": user_settings.audio_quota_bytes,
            "audio_used_bytes": used,
            "over_quota": used > user_settings.audio_quota_bytes,
            "pending_jobs": 0,
            "warnings": [],
            "shared_memory": _json_obj(summary),
        }

    async def export_summary(self, user_settings: UserSettings) -> dict[str, Any]:
        summary = await self.pool.fetchval(
            "SELECT summary FROM shared_memory WHERE user_id = $1",
            user_settings.user_id,
        )
        return _json_obj(summary)

    async def maybe_merge_rolling_summary(
        self,
        user_settings: UserSettings,
        device: DeviceConfig | None,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        summary = await self.export_summary(user_settings)
        if not summary:
            summary = {"user_id": user_settings.user_id, **memory_field_defaults()}
        if not should_merge_summary(summary, force=force):
            return {"merged": False, "reason": "not_due"}
        recent_turns = await self._fetch_recent_turns(user_settings.user_id)
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
        updated = finalize_summary_after_merge(summary, merged_text)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await self._persist_summary(conn, user_settings.user_id, updated)
        sync_summary_json(user_settings.user_id, updated)
        return {"merged": True, "summary_updated_at": updated.get("summary_updated_at")}

    async def compress_if_needed(self, user_settings: UserSettings) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                used = await self._attachment_total_bytes(conn, user_settings.user_id)
                quota = user_settings.audio_quota_bytes
                if used <= quota:
                    return {"compressed": 0, "used_bytes": used, "over_quota": False}

                target = int(quota * COMPRESS_TARGET_RATIO)
                rows = await conn.fetch(
                    """
                    SELECT attachment_id, path, size_bytes
                    FROM audio_attachments
                    WHERE user_id = $1
                      AND deleted_at IS NULL
                      AND kind = 'input'
                      AND compressed = false
                    ORDER BY created_at ASC, attachment_id ASC
                    """,
                    user_settings.user_id,
                )
                compressed_count = 0
                for row in rows:
                    if used <= target:
                        break
                    path = Path(str(row["path"]))
                    if not path.exists():
                        await conn.execute(
                            "UPDATE audio_attachments SET deleted_at = now() WHERE attachment_id = $1",
                            row["attachment_id"],
                        )
                        continue
                    compressed_path = path.with_suffix(".mp3")
                    compress_wav_to_mp3(path, compressed_path)
                    old_size = int(row["size_bytes"] or path.stat().st_size)
                    path.unlink(missing_ok=True)
                    new_size = compressed_path.stat().st_size
                    await conn.execute(
                        """
                        UPDATE audio_attachments
                        SET path = $1,
                            media_type = 'audio/mpeg',
                            size_bytes = $2,
                            sha256 = $3,
                            compressed = true
                        WHERE attachment_id = $4
                        """,
                        str(compressed_path),
                        new_size,
                        sha256_file(compressed_path),
                        row["attachment_id"],
                    )
                    used = used - old_size + new_size
                    compressed_count += 1
                return {
                    "compressed": compressed_count,
                    "used_bytes": used,
                    "over_quota": used > quota,
                }

    async def purge_expired_audio_attachments(self, *, retention_hours: int) -> dict[str, int]:
        if retention_hours <= 0:
            return {"purged": 0, "bytes_freed": 0}
        purged = 0
        bytes_freed = 0
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT attachment_id, path, size_bytes, user_id
                    FROM audio_attachments
                    WHERE deleted_at IS NULL
                      AND created_at < now() - make_interval(hours => $1)
                    ORDER BY created_at ASC, attachment_id ASC
                    """,
                    retention_hours,
                )
                for row in rows:
                    path = Path(str(row["path"]))
                    stop_at = _user_outputs_root(path, str(row["user_id"]))
                    if path.exists():
                        bytes_freed += purge_attachment_file(path, stop_at=stop_at)
                    else:
                        bytes_freed += int(row["size_bytes"] or 0)
                    await conn.execute(
                        "UPDATE audio_attachments SET deleted_at = now() WHERE attachment_id = $1",
                        row["attachment_id"],
                    )
                    purged += 1
        return {"purged": purged, "bytes_freed": bytes_freed}

    async def _insert_attachment(
        self,
        conn,
        *,
        user_id: str,
        device_id: str,
        session_id: str,
        turn_id: str,
        kind: str,
        path: Path,
        media_type: str,
        compressed: bool,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO audio_attachments (
                attachment_id, user_id, device_id, session_id, turn_id, kind,
                path, media_type, size_bytes, sha256, compressed
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            uuid.uuid4().hex,
            user_id,
            device_id,
            session_id,
            turn_id,
            kind,
            str(path),
            media_type,
            path.stat().st_size,
            sha256_file(path),
            compressed,
        )

    async def _attachment_total_bytes(self, conn, user_id: str) -> int:
        value = await conn.fetchval(
            """
            SELECT COALESCE(SUM(size_bytes), 0)
            FROM audio_attachments
            WHERE user_id = $1 AND deleted_at IS NULL
            """,
            user_id,
        )
        return int(value or 0)

    async def _load_summary(self, conn, user_id: str) -> dict[str, Any]:
        row = await conn.fetchval(
            "SELECT summary FROM shared_memory WHERE user_id = $1",
            user_id,
        )
        loaded = _json_obj(row)
        if loaded:
            return loaded
        return {"user_id": user_id, **memory_field_defaults()}

    async def _persist_summary(self, conn, user_id: str, summary: dict[str, Any]) -> None:
        await conn.execute(
            """
            INSERT INTO shared_memory (user_id, summary, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (user_id) DO UPDATE SET
                summary = excluded.summary,
                updated_at = now()
            """,
            user_id,
            json.dumps(summary, ensure_ascii=False),
        )

    async def _fetch_recent_turns(self, user_id: str, *, limit: int = 15) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            SELECT user_text, reply_text, created_at
            FROM conversation_events
            WHERE user_id = $1
              AND deleted_at IS NULL
              AND created_at >= now() - make_interval(days => $2)
            ORDER BY created_at DESC
            LIMIT $3
            """,
            user_id,
            SUMMARY_WINDOW_DAYS,
            limit,
        )
        items = [
            {
                "user_text": row["user_text"],
                "reply_text": row["reply_text"],
                "created_at": _dt(row["created_at"]),
            }
            for row in rows
        ]
        return list(reversed(items))

    async def _refresh_shared_memory(
        self,
        conn,
        user_settings: UserSettings,
        warning: str,
        *,
        user_text: str = "",
    ) -> None:
        event_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM conversation_events
            WHERE user_id = $1 AND deleted_at IS NULL
            """,
            user_settings.user_id,
        )
        used = await self._attachment_total_bytes(conn, user_settings.user_id)
        existing = await self._load_summary(conn, user_settings.user_id)
        stats = {
            "user_id": user_settings.user_id,
            "turn_count": int(event_count or 0),
            "last_interaction_at": datetime.now(timezone.utc).isoformat(),
            "audio_quota_bytes": user_settings.audio_quota_bytes,
            "audio_used_bytes": used,
            "over_quota": used > user_settings.audio_quota_bytes,
            "last_warning": warning,
            "milestones": existing.get("milestones") or [],
        }
        summary = merge_summary_with_stats(existing, stats)
        if user_text.strip():
            summary = apply_turn_to_summary(summary, user_text)
        await self._persist_summary(conn, user_settings.user_id, summary)
        sync_summary_json(user_settings.user_id, summary)

    async def _upsert_facts_from_text(self, conn, user_id: str, text: str) -> None:
        for fact_key, fact_value, category in _extract_facts(text):
            existing = await conn.fetchval(
                """
                SELECT fact_id
                FROM user_facts
                WHERE user_id = $1 AND fact_key = $2 AND deleted_at IS NULL
                LIMIT 1
                """,
                user_id,
                fact_key,
            )
            if existing:
                await conn.execute(
                    """
                    UPDATE user_facts
                    SET fact_value = $1, category = $2, confidence = 1.0, updated_at = now()
                    WHERE fact_id = $3
                    """,
                    fact_value,
                    category,
                    existing,
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO user_facts (
                        fact_id, user_id, fact_key, fact_value, category, confidence
                    )
                    VALUES ($1, $2, $3, $4, $5, 1.0)
                    """,
                    uuid.uuid4().hex,
                    user_id,
                    fact_key,
                    fact_value,
                    category,
                )
