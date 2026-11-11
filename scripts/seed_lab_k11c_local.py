"""Seed SX-000003/004 into local Docker Postgres so the K11C lab PIN can hello."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg

from shuxin.voice.persistence.base_repo import _hash_secret

CODES = ("SX-000003", "SX-000004")


async def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    secrets: dict[str, str] = {}
    for code in CODES:
        path = Path(f"/tmp/{code}.txt")
        if path.is_file():
            secrets[code] = path.read_text(encoding="utf-8").strip()
    if not secrets:
        raise SystemExit("no lab secrets at /tmp/SX-00000x.txt")

    conn = await asyncpg.connect(dsn)
    try:
        demo = await conn.fetchrow("SELECT * FROM devices WHERE device_id = 'demo-device-001'")
        if demo is None:
            raise SystemExit("demo-device-001 missing")
        for code, secret in secrets.items():
            digest = _hash_secret(secret)
            await conn.execute(
                """
                INSERT INTO devices (
                    device_id, auth_mode, device_secret_hash, status,
                    stt_config, tts_config, llm_config, enabled, note, metadata,
                    subscription_plan_id, subscription_minutes_limit,
                    subscription_minutes_used, subscription_expires_at,
                    fuel_minutes_balance, last_reset_month, daily_allowance_date,
                    daily_allowance_seconds_used
                )
                VALUES (
                    $1, 'per_device_secret', $2, 'bound',
                    $3, $4, $5, true, 'local docker k11c lab', $6,
                    $7, GREATEST($8, 9999), 0, $9,
                    GREATEST($10, 9999), $11, $12, 0
                )
                ON CONFLICT (device_id) DO UPDATE SET
                    auth_mode = EXCLUDED.auth_mode,
                    device_secret_hash = EXCLUDED.device_secret_hash,
                    status = 'bound',
                    enabled = true,
                    deleted_at = NULL,
                    stt_config = EXCLUDED.stt_config,
                    tts_config = EXCLUDED.tts_config,
                    llm_config = EXCLUDED.llm_config,
                    fuel_minutes_balance = EXCLUDED.fuel_minutes_balance,
                    subscription_minutes_limit = EXCLUDED.subscription_minutes_limit,
                    updated_at = now()
                """,
                code,
                digest,
                demo["stt_config"],
                demo["tts_config"],
                demo["llm_config"],
                demo["metadata"],
                demo["subscription_plan_id"],
                int(demo["subscription_minutes_limit"] or 0),
                demo["subscription_expires_at"],
                demo["fuel_minutes_balance"],
                demo["last_reset_month"],
                demo["daily_allowance_date"],
            )
            binding_id = f"lab-{code}-demo-user"
            await conn.execute(
                """
                INSERT INTO device_bindings (binding_id, user_id, device_id, status)
                VALUES ($1, 'demo-user', $2, 'active')
                ON CONFLICT (binding_id) DO UPDATE SET
                    status = 'active',
                    unbound_at = NULL
                """,
                binding_id,
                code,
            )
            print(f"seeded {code}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
