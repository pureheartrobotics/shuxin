#!/usr/bin/env python3
"""Backfill DMX per-user API keys for users missing llm_config.api_key.

Usage (Docker)::

    docker exec shuxin-voice-demo-pg python /app/scripts/backfill_dmx_user_keys.py
    docker exec shuxin-voice-demo-pg python /app/scripts/backfill_dmx_user_keys.py --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys


async def _run(*, limit: int) -> int:
    from shuxin.voice.persistence.db import PostgresDatabase
    from shuxin.voice.persistence.postgres_repository import VoicePostgresRepository

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://shuxin:shuxin_dev_password@postgres:5432/shuxin",
    )
    db = PostgresDatabase(database_url)
    await db.connect()
    repo = VoicePostgresRepository(db.pool)
    rows = await db.pool.fetch(
        """
        SELECT user_id
        FROM users
        WHERE deleted_at IS NULL
          AND enabled = true
          AND (
            llm_config IS NULL
            OR coalesce(llm_config->>'api_key', '') = ''
          )
        ORDER BY updated_at DESC NULLS LAST
        LIMIT $1
        """,
        max(1, int(limit)),
    )
    print(f"candidates={len(rows)}")
    ok = 0
    fail = 0
    for row in rows:
        user_id = str(row["user_id"])
        try:
            await repo.ensure_user_dmx_llm(user_id)
            check = await db.pool.fetchval(
                "SELECT coalesce(llm_config->>'api_key', '') FROM users WHERE user_id = $1",
                user_id,
            )
            if str(check or "").strip():
                ok += 1
                print(f"ok {user_id}")
            else:
                fail += 1
                print(f"still_empty {user_id}")
        except Exception as exc:
            fail += 1
            print(f"fail {user_id}: {exc}")
    await db.close()
    print(f"done ok={ok} fail={fail}")
    return 0 if fail == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    return asyncio.run(_run(limit=args.limit))


if __name__ == "__main__":
    sys.exit(main())
