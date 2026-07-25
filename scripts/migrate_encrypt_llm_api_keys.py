#!/usr/bin/env python3
"""Encrypt plaintext users.llm_config.api_key values (enc:v1: Fernet).

Requires SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY (same as device secrets).

Usage (Docker)::

    docker exec shuxin-voice-demo-pg python /app/scripts/migrate_encrypt_llm_api_keys.py
    docker exec shuxin-voice-demo-pg python /app/scripts/migrate_encrypt_llm_api_keys.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


async def _run(*, dry_run: bool, limit: int) -> int:
    from shuxin.voice.persistence.db import PostgresDatabase
    from shuxin.voice.persistence.device_secret_crypto import (
        LLM_API_KEY_ENC_PREFIX,
        is_encrypted_llm_api_key,
        require_device_secret_encryption,
        seal_llm_config_for_storage,
    )

    require_device_secret_encryption()

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://shuxin:shuxin_dev_password@postgres:5432/shuxin",
    )
    db = PostgresDatabase(database_url)
    await db.connect()
    rows = await db.pool.fetch(
        """
        SELECT user_id, llm_config
        FROM users
        WHERE deleted_at IS NULL
          AND coalesce(llm_config->>'api_key', '') <> ''
          AND llm_config->>'api_key' NOT LIKE $1
        ORDER BY updated_at DESC NULLS LAST
        LIMIT $2
        """,
        f"{LLM_API_KEY_ENC_PREFIX}%",
        max(1, int(limit)),
    )
    print(f"candidates={len(rows)} dry_run={dry_run}")
    ok = 0
    skip = 0
    fail = 0
    for row in rows:
        user_id = str(row["user_id"])
        raw = row["llm_config"]
        if isinstance(raw, str):
            try:
                llm_config = json.loads(raw)
            except json.JSONDecodeError:
                fail += 1
                print(f"fail {user_id}: invalid llm_config json")
                continue
        else:
            llm_config = dict(raw or {})
        api_key = str(llm_config.get("api_key") or "").strip()
        if not api_key or is_encrypted_llm_api_key(api_key):
            skip += 1
            continue
        try:
            sealed = seal_llm_config_for_storage(llm_config)
            sealed_key = str(sealed.get("api_key") or "")
            if not is_encrypted_llm_api_key(sealed_key):
                fail += 1
                print(f"fail {user_id}: seal did not produce enc:v1 prefix")
                continue
            if dry_run:
                ok += 1
                print(f"would_encrypt {user_id}")
                continue
            await db.pool.execute(
                """
                UPDATE users
                SET llm_config = $2::jsonb, updated_at = now()
                WHERE user_id = $1 AND deleted_at IS NULL
                """,
                user_id,
                json.dumps(sealed, ensure_ascii=False),
            )
            ok += 1
            print(f"ok {user_id}")
        except Exception as exc:
            fail += 1
            print(f"fail {user_id}: {exc}")
    await db.close()
    print(f"done ok={ok} skip={skip} fail={fail}")
    return 0 if fail == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    return asyncio.run(_run(dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    sys.exit(main())
