#!/usr/bin/env python3
"""三层记忆 E2E：模拟 voice-demo 多轮对话 + 断线重连（无需麦克风）。

在 Docker voice 容器内执行（需 DATABASE_URL 与用户 LLM 已配置）：

    PYTHONPATH=src python scripts/test_voice_memory_e2e.py

可选 WebSocket 模式（需服务端开启 SHUXIN_VOICE_DEV_TEXT_TURN=1 并重启）：

    PYTHONPATH=src python scripts/test_voice_memory_e2e.py --ws ws://127.0.0.1:8765/ws/voice
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

# 会话 A 固定剧本（须含「面试」）
SESSION_A_LINES = [
    "我下周有个很重要的面试，有点紧张。",
    "面试是产品经理岗位。",
    "我最近每晚都在准备面试。",
    "面试公司是一家互联网公司。",
    "如果面试过了我想请你帮我庆祝。",
]

SESSION_B_LINE = "我上次跟你说的那件事，后来怎么样了？"
REPLY_KEYWORDS = ("面试", "产品经理", "准备", "紧张", "庆祝")
MERGE_WAIT_SECONDS = 12


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_src_path() -> None:
    root = _repo_root()
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _merge_device_llm(device, settings) -> None:
    from shuxin.voice.config import merge_llm_device_config

    if settings.llm_config:
        device.llm = merge_llm_device_config(device.llm, settings.llm_config)


async def _run_direct(
    *,
    user_id: str,
    device_id: str,
    client_id: str,
) -> int:
    _ensure_src_path()
    from shuxin.core.config import get_shuxin_home
    from shuxin.voice.db import PostgresDatabase
    from shuxin.voice.postgres_repository import VoicePostgresRepository
    from shuxin.voice.config import DeviceConfigProvider
    from shuxin.voice.service import VoiceService

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("ERROR: DATABASE_URL is required", file=sys.stderr)
        return 1

    db = PostgresDatabase(database_url)
    await db.connect()
    repo = VoicePostgresRepository(db.pool)
    try:
        settings = await repo.authenticate_user(user_id, "")
        device_provider = DeviceConfigProvider(
            os.environ.get("VOICE_DEVICE_CONFIG", "data/devices.yaml")
        )
        device = await repo.get_device(device_id)
        _merge_device_llm(device, settings)

        if not (device.llm.api_key or os.environ.get("OPENAI_API_KEY")):
            print(
                "ERROR: LLM api_key missing for user/device. Configure LLM in /admin first.",
                file=sys.stderr,
            )
            return 1

        user_home = get_shuxin_home() / "users" / settings.user_id
        user_home.mkdir(parents=True, exist_ok=True)
        service = VoiceService(device_provider)
        session_id = f"e2e-{uuid.uuid4().hex[:12]}"
        await repo.ensure_session(
            session_id=session_id,
            user_id=settings.user_id,
            device_id=device_id,
            client_id=client_id,
        )

        print(f"== Session A ({len(SESSION_A_LINES)} turns) user={user_id} session={session_id}")
        agent = service.create_agent(device, user_home=user_home)
        agent.context.metadata["channel"] = "voice"
        await asyncio.get_event_loop().run_in_executor(None, agent.initialize)

        for index, line in enumerate(SESSION_A_LINES, start=1):
            started = time.perf_counter()
            reply = await asyncio.get_event_loop().run_in_executor(
                None, lambda text=line: agent.chat(text).strip()
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            print(f"  [{index}] user: {line}")
            print(f"      agent ({elapsed_ms}ms): {reply[:120]}{'...' if len(reply) > 120 else ''}")
            await repo.record_turn(
                user_settings=settings,
                device_id=device_id,
                client_id=client_id,
                session_id=session_id,
                turn_id=uuid.uuid4().hex,
                user_text=line,
                reply_text=reply,
                input_audio=None,
                reply_audio=None,
                timings={"total_elapsed_ms": elapsed_ms, "agent_ms": elapsed_ms},
            )

        agent.shutdown()

        print(f"== Waiting {MERGE_WAIT_SECONDS}s for async summary merge...")
        await asyncio.sleep(2)
        merge_result = await repo.maybe_merge_rolling_summary(
            settings, device, force=True
        )
        print(f"   merge: {merge_result}")
        await asyncio.sleep(max(0, MERGE_WAIT_SECONDS - 2))

        summary = await repo.export_summary(settings)
        print("== Checkpoints after Session A")
        print(
            json.dumps(
                {
                    "turn_count": summary.get("turn_count"),
                    "turns_since_summary": summary.get("turns_since_summary"),
                    "recent_topics": summary.get("recent_topics"),
                    "rolling_summary": (summary.get("rolling_summary") or "")[:200],
                    "summary_updated_at": summary.get("summary_updated_at"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        rolling = str(summary.get("rolling_summary") or "").strip()
        if not rolling:
            print(
                "FAIL: rolling_summary is empty (LLM merge failed or no API key).",
                file=sys.stderr,
            )
            return 1

        print("== Session B (new Agent, simulate reconnect)")
        agent_b = service.create_agent(device, user_home=user_home)
        agent_b.context.metadata["channel"] = "voice"
        await asyncio.get_event_loop().run_in_executor(None, agent_b.initialize)
        reply_b = await asyncio.get_event_loop().run_in_executor(
            None, lambda: agent_b.chat(SESSION_B_LINE).strip()
        )
        agent_b.shutdown()
        print(f"  user: {SESSION_B_LINE}")
        print(f"  agent: {reply_b}")

        if not any(keyword in reply_b for keyword in REPLY_KEYWORDS):
            print(
                f"FAIL: reply does not mention expected topic keywords {REPLY_KEYWORDS}",
                file=sys.stderr,
            )
            return 1

        print("PASS: three-tier memory E2E (direct mode)")
        return 0
    finally:
        await db.close()


async def _run_ws(
    *,
    ws_url: str,
    device_code: str,
    device_secret: str,
    user_id: str,
    admin_export_base: str,
) -> int:
    _ensure_src_path()
    try:
        import websockets
    except ImportError:
        print("ERROR: websockets package required for --ws mode", file=sys.stderr)
        return 1

    if os.environ.get("SHUXIN_VOICE_DEV_TEXT_TURN") != "1":
        print(
            "ERROR: set SHUXIN_VOICE_DEV_TEXT_TURN=1 and restart voice server for --ws mode",
            file=sys.stderr,
        )
        return 1

    session_id = f"e2e-ws-{uuid.uuid4().hex[:12]}"
    replies_a: list[str] = []

    async def one_session(turns: list[str]) -> None:
        async with websockets.connect(ws_url) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "hello",
                        "device_code": device_code,
                        "device_secret": device_secret,
                        "client_id": "e2e-script",
                        "session_id": session_id,
                    },
                    ensure_ascii=False,
                )
            )
            while True:
                raw = await ws.recv()
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                if msg.get("type") == "hello" and msg.get("state") == "ok":
                    break
                if msg.get("type") == "error":
                    raise RuntimeError(msg.get("message"))

            for line in turns:
                await ws.send(
                    json.dumps({"type": "text_turn", "text": line}, ensure_ascii=False)
                )
                reply_text = ""
                while True:
                    raw = await ws.recv()
                    if isinstance(raw, bytes):
                        continue
                    msg = json.loads(raw)
                    if msg.get("type") == "agent" and msg.get("state") == "reply":
                        reply_text = str(msg.get("text") or "")
                        break
                    if msg.get("type") == "error":
                        raise RuntimeError(msg.get("message"))
                replies_a.append(reply_text)
                print(f"  agent: {reply_text[:120]}")

    print(f"== Session A via WebSocket ({ws_url})")
    await one_session(SESSION_A_LINES)
    print(f"== Waiting {MERGE_WAIT_SECONDS}s...")
    await asyncio.sleep(MERGE_WAIT_SECONDS)

    import urllib.request

    export_url = (
        f"{admin_export_base.rstrip('/')}/voice/export?user_id={user_id}"
    )
    req = urllib.request.Request(
        export_url,
        headers={"X-Admin-Token": os.environ.get("SHUXIN_ADMIN_TOKEN", "dev-admin-token")},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    summary = payload.get("shared_memory") or {}
    if not str(summary.get("rolling_summary") or "").strip():
        print("FAIL: rolling_summary empty after WS session A", file=sys.stderr)
        return 1

    print("== Session B via WebSocket")
    reply_b = ""
    async with websockets.connect(ws_url) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "device_code": device_code,
                    "device_secret": device_secret,
                    "client_id": "e2e-script-b",
                },
                ensure_ascii=False,
            )
        )
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("type") == "hello" and msg.get("state") == "ok":
                break
        await ws.send(
            json.dumps({"type": "text_turn", "text": SESSION_B_LINE}, ensure_ascii=False)
        )
        while True:
            msg = json.loads(await ws.recv())
            if isinstance(msg, str):
                msg = json.loads(msg)
            if msg.get("type") == "agent" and msg.get("state") == "reply":
                reply_b = str(msg.get("text") or "")
                break

    print(f"  agent: {reply_b}")
    if not any(k in reply_b for k in REPLY_KEYWORDS):
        print("FAIL: Session B reply missing topic keywords", file=sys.stderr)
        return 1
    print("PASS: three-tier memory E2E (WebSocket mode)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ShuXin voice three-tier memory E2E")
    parser.add_argument("--user-id", default=os.environ.get("SHUXIN_E2E_USER_ID", "demo-user"))
    parser.add_argument(
        "--device-id", default=os.environ.get("SHUXIN_E2E_DEVICE_ID", "demo-device-001")
    )
    parser.add_argument("--client-id", default="e2e-memory-script")
    parser.add_argument("--ws", default="", help="WebSocket URL, e.g. ws://127.0.0.1:8765/ws/voice")
    parser.add_argument(
        "--export-base",
        default=os.environ.get("SHUXIN_E2E_HTTP_BASE", "http://127.0.0.1:8765"),
    )
    args = parser.parse_args()

    if args.ws:
        return asyncio.run(
            _run_ws(
                ws_url=args.ws,
                device_code=args.device_id,
                device_secret=os.environ.get("SHUXIN_DEVICE_SHARED_SECRET", "dev-device-secret"),
                user_id=args.user_id,
                admin_export_base=args.export_base,
            )
        )
    return asyncio.run(
        _run_direct(
            user_id=args.user_id,
            device_id=args.device_id,
            client_id=args.client_id,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
