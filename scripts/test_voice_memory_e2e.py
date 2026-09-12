#!/usr/bin/env python3
"""三层记忆 E2E：模拟 voice-demo 多轮对话 + 断线重连（无需麦克风）。

在 Docker voice 容器内执行（需 DATABASE_URL；默认使用 DEMO_LLM_* 公司 API）：

    PYTHONPATH=src python scripts/test_voice_memory_e2e.py

默认跑 e2e-user-alice / e2e-user-bob 双用户隔离测试，并写入 JSON + Markdown 报告。

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
E2E_TEST_TOKEN = "e2e-test-token"
MEM0_SESSION_GRACE_SECONDS = 5

E2E_USER_SPECS = [
    {"user_id": "e2e-user-alice", "device_id": "demo-device-002", "mbti": "INFJ"},
    {"user_id": "e2e-user-bob", "device_id": "demo-device-003", "mbti": "ENTP"},
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_src_path() -> None:
    root = _repo_root()
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _merge_device_llm(device, settings) -> None:
    from shuxin.testing.e2e_helpers import merge_device_llm

    merge_device_llm(device, settings)


def _apply_demo_llm(device) -> None:
    from shuxin.testing.e2e_helpers import apply_demo_llm

    apply_demo_llm(device)


def _mem0_search(user_id: str, query: str) -> list[str]:
    from shuxin.testing.e2e_helpers import mem0_search

    return mem0_search(user_id, query)


def _print_llm_source(device, *, use_demo_llm: bool) -> None:
    source = "DEMO_LLM env" if use_demo_llm else "device + user llm_config merge"
    key = device.llm.api_key or os.environ.get("OPENAI_API_KEY", "")
    print(
        f"LLM source: {source}  "
        f"model={device.llm.model or '(empty)'}  "
        f"base={device.llm.base_url or '(empty)'}  "
        f"key_len={len(key)}"
    )



async def _ensure_e2e_users(repo) -> None:
    """Create isolated E2E users, set device MBTI, and bind devices."""
    for spec in E2E_USER_SPECS:
        user_id = spec["user_id"]
        device_id = spec["device_id"]
        mbti = spec["mbti"]
        await repo.pool.execute(
            """
            INSERT INTO users (user_id, token, llm_config, enabled, metadata, updated_at)
            VALUES ($1, $2, '{}'::jsonb, true, $3::jsonb, now())
            ON CONFLICT (user_id) DO UPDATE SET
                token = EXCLUDED.token,
                llm_config = '{}'::jsonb,
                enabled = true,
                deleted_at = NULL,
                updated_at = now()
            """,
            user_id,
            E2E_TEST_TOKEN,
            json.dumps({"e2e": True}, ensure_ascii=False),
        )
        await repo.pool.execute(
            """
            UPDATE devices
            SET enabled = true,
                deleted_at = NULL,
                status = 'provisioned',
                metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
                    'mbti', $2::text,
                    'mbti_status', 'locked'
                ),
                updated_at = now()
            WHERE device_id = $1
            """,
            device_id,
            mbti,
        )
        await repo.admin_bind_device(user_id=user_id, device_id=device_id)
        print(f"  ensured user={user_id} device={device_id} mbti={mbti}")


def _device_spec_for_user(user_id: str) -> dict[str, str]:
    for spec in E2E_USER_SPECS:
        if spec["user_id"] == user_id:
            return spec
    return {"user_id": user_id, "device_id": "demo-device-001", "mbti": ""}


async def _run_user_session(
    *,
    repo,
    service,
    user_id: str,
    device_id: str,
    client_id: str,
    use_demo_llm: bool,
    mbti: str = "",
) -> dict[str, Any]:
    from shuxin.core.config import get_shuxin_home
    from shuxin.voice.config import DeviceConfigProvider

    session_report: dict[str, Any] = {
        "user_id": user_id,
        "device_id": device_id,
        "mbti": mbti,
        "session_id": "",
        "session_a_turns": [],
        "rolling_summary": "",
        "recent_topics": [],
        "turn_count": 0,
        "mem0_search_result": [],
        "session_b": {"user": SESSION_B_LINE, "agent": ""},
        "result": "FAIL",
        "failure_reason": "",
    }

    settings = await repo.authenticate_user(user_id, E2E_TEST_TOKEN if user_id != "demo-user" else "")
    device_provider = DeviceConfigProvider(
        os.environ.get("VOICE_DEVICE_CONFIG", "data/devices.yaml")
    )
    _ = device_provider  # service already created with provider
    device = await repo.get_device(device_id)
    if use_demo_llm:
        _apply_demo_llm(device)
    else:
        _merge_device_llm(device, settings)
    _print_llm_source(device, use_demo_llm=use_demo_llm)

    if not (device.llm.api_key or os.environ.get("OPENAI_API_KEY")):
        session_report["failure_reason"] = "LLM api_key missing"
        return session_report

    user_home = get_shuxin_home() / "users" / settings.user_id
    user_home.mkdir(parents=True, exist_ok=True)
    session_id = f"e2e-{uuid.uuid4().hex[:12]}"
    session_report["session_id"] = session_id
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
        turn = {"index": index, "user": line, "agent": reply, "elapsed_ms": elapsed_ms}
        session_report["session_a_turns"].append(turn)
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
    from shuxin.voice.memory_summary import force_summary_trigger

    merge_result = await force_summary_trigger(repo, settings, device)
    print(f"   merge: {merge_result}")
    await asyncio.sleep(max(0, MERGE_WAIT_SECONDS - 2))

    summary = await repo.export_summary(settings)
    rolling = str(summary.get("rolling_summary") or "").strip()
    session_report["rolling_summary"] = rolling
    session_report["recent_topics"] = summary.get("recent_topics") or []
    session_report["turn_count"] = summary.get("turn_count")

    print("== Checkpoints after Session A")
    print(
        json.dumps(
            {
                "turn_count": summary.get("turn_count"),
                "turns_since_summary": summary.get("turns_since_summary"),
                "recent_topics": summary.get("recent_topics"),
                "rolling_summary": rolling[:200],
                "summary_updated_at": summary.get("summary_updated_at"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if not rolling:
        session_report["failure_reason"] = "rolling_summary is empty"
        return session_report

    # Allow Mem0 async indexing before Session B
    await asyncio.sleep(MEM0_SESSION_GRACE_SECONDS)
    mem0_hits = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _mem0_search(user_id, SESSION_B_LINE)
    )
    session_report["mem0_search_result"] = mem0_hits

    print("== Session B (new Agent, simulate reconnect)")
    agent_b = service.create_agent(device, user_home=user_home)
    agent_b.context.metadata["channel"] = "voice"
    await asyncio.get_event_loop().run_in_executor(None, agent_b.initialize)
    reply_b = await asyncio.get_event_loop().run_in_executor(
        None, lambda: agent_b.chat(SESSION_B_LINE).strip()
    )
    agent_b.shutdown()
    session_report["session_b"]["agent"] = reply_b
    print(f"  user: {SESSION_B_LINE}")
    print(f"  agent: {reply_b}")

    if not any(keyword in reply_b for keyword in REPLY_KEYWORDS):
        session_report["failure_reason"] = (
            f"reply does not mention expected topic keywords {REPLY_KEYWORDS}"
        )
        return session_report

    session_report["result"] = "PASS"
    return session_report


def _write_reports(report_dir: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "report.json"
    md_path = report_dir / "report.md"

    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# 三层记忆 E2E 测试报告",
        "",
        f"- **run_id**: `{report.get('run_id', '')}`",
        f"- **时间**: {report.get('timestamp', '')}",
        f"- **suite**: {report.get('suite', 'legacy')}",
        f"- **LLM**: {report.get('llm_source', '')}",
        f"- **总体结果**: **{report.get('overall', 'FAIL')}**",
        "",
    ]

    for session in report.get("sessions", []):
        title = session.get("scenario_id") or session.get("user_id")
        lines += [
            f"## 场景 `{title}`",
            "",
            f"- user_id: `{session.get('user_id')}`",
            f"- device: `{session.get('device_id')}`",
            f"- mbti: `{session.get('mbti')}`",
            f"- 结果: **{session.get('result')}**",
        ]
        if session.get("session_id"):
            lines.append(f"- session_id: `{session.get('session_id')}`")
        if session.get("failure_reason"):
            lines.append(f"- 失败原因: {session['failure_reason']}")
        if session.get("identity_check"):
            ic = session["identity_check"]
            lines.append(
                f"- identity_check: {ic.get('actual')} (expected {ic.get('expected')})"
            )
        if session.get("mbti_score"):
            ms = session["mbti_score"]
            lines.append(f"- mbti_score: hits={ms.get('hit_count')} pass={ms.get('pass')}")
        if session.get("judge"):
            lines.append(f"- llm_judge: {json.dumps(session['judge'], ensure_ascii=False)}")
        lines.append("")

        timeline = session.get("timeline") or []
        if timeline:
            lines += ["### 对话时间线", ""]
            for item in timeline:
                if item.get("event") == "force_summary":
                    lines.append(f"- [session {item.get('session')}] force_summary: {item.get('result')}")
                    continue
                lines += [
                    f"**[S{item.get('session')} T{item.get('turn')}] 用户** ({item.get('elapsed_ms', 0)}ms)",
                    "",
                    item.get("user", ""),
                    "",
                    "**初心**",
                    "",
                    item.get("agent", ""),
                    "",
                ]
        else:
            lines += ["### Session A 对话", ""]
            for turn in session.get("session_a_turns", []):
                lines += [
                    f"**[{turn['index']}] 用户** ({turn['elapsed_ms']}ms)",
                    "",
                    turn["user"],
                    "",
                    "**初心**",
                    "",
                    turn["agent"],
                    "",
                ]
            lines += [
                "### Session B",
                "",
                f"**用户**: {session.get('session_b', {}).get('user', '')}",
                "",
                f"**初心**: {session.get('session_b', {}).get('agent', '')}",
                "",
            ]

        lines += [
            "### 中期记忆 (rolling_summary)",
            "",
            session.get("rolling_summary") or "（空）",
            "",
            "### Mem0 检索",
            "",
        ]
        mem0 = session.get("mem0_search_result") or []
        if mem0:
            lines += [f"- {line}" for line in mem0]
        else:
            lines.append("（无命中）")
        lines.append("")

    isolation = report.get("isolation_check")
    if isolation:
        lines += [
            "## 用户隔离检查",
            "",
            f"- Alice: `{isolation.get('alice_user_id')}`",
            f"- Bob: `{isolation.get('bob_user_id')}`",
            f"- 结果: **{isolation.get('result')}**",
            "",
        ]
        if isolation.get("leaked_to_bob"):
            lines.append("泄漏到 Bob 的记忆：")
            lines += [f"- {line}" for line in isolation["leaked_to_bob"]]
            lines.append("")
        if isolation.get("alice_mem0_after") is not None:
            lines.append(f"- Alice Mem0 命中数（跑完后）: {len(isolation.get('alice_mem0_after') or [])}")
            lines.append(f"- Bob Mem0 命中数（跑完后）: {len(isolation.get('bob_mem0_after') or [])}")
            lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


async def _run_suite(
    *,
    suite: str,
    client_id: str,
    use_demo_llm: bool,
    report_dir: Path | None,
    llm_judge: bool = False,
) -> int:
    _ensure_src_path()
    from shuxin.testing.e2e_helpers import ensure_scenario_user
    from shuxin.testing.llm_judge import judge_scenario
    from shuxin.testing.scenario_runner import load_all_scenario_files, run_scenario
    from shuxin.voice.config import DeviceConfigProvider
    from shuxin.voice.db import PostgresDatabase
    from shuxin.voice.postgres_repository import VoicePostgresRepository
    from shuxin.voice.service import VoiceService

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("ERROR: DATABASE_URL is required", file=sys.stderr)
        return 1

    scenarios = load_all_scenario_files(suite=suite)
    if not scenarios:
        print(f"ERROR: no scenarios for suite={suite}", file=sys.stderr)
        return 1

    run_id = f"e2e-{uuid.uuid4().hex[:12]}"
    report: dict[str, Any] = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "suite": suite,
        "llm_source": "DEMO_LLM env" if use_demo_llm else "device + user llm_config merge",
        "scenarios": [s.get("id") for s in scenarios],
        "sessions": [],
        "overall": "FAIL",
    }

    db = PostgresDatabase(database_url)
    await db.connect()
    repo = VoicePostgresRepository(db.pool)
    try:
        device_provider = DeviceConfigProvider(
            os.environ.get("VOICE_DEVICE_CONFIG", "data/devices.yaml")
        )
        service = VoiceService(device_provider)

        for scenario in scenarios:
            sid = scenario.get("id", "")
            print(f"== Scenario: {sid} user={scenario.get('user_id')}")
            await ensure_scenario_user(repo, scenario)
            session_report = await run_scenario(
                scenario,
                repo=repo,
                service=service,
                use_demo_llm=use_demo_llm,
                client_id=client_id,
                mem0_grace_seconds=MEM0_SESSION_GRACE_SECONDS,
            )
            if llm_judge:
                session_report["judge"] = judge_scenario(
                    {
                        "id": sid,
                        "mbti": scenario.get("mbti", ""),
                        "turns": [
                            t
                            for t in session_report.get("timeline", [])
                            if t.get("user")
                        ],
                    }
                )
            report["sessions"].append(session_report)
            if session_report["result"] != "PASS":
                print(
                    f"FAIL: scenario={sid} reason={session_report.get('failure_reason')}",
                    file=sys.stderr,
                )
                if report_dir:
                    out_json, out_md = _write_reports(report_dir / run_id, report)
                    print(f"Report written: {out_json}")
                    print(f"Report written: {out_md}")
                return 1
            print(f"PASS: scenario={sid}")

        report["overall"] = "PASS"
        print(f"PASS: suite={suite} ({len(scenarios)} scenarios)")
        if report_dir:
            out_json, out_md = _write_reports(report_dir / run_id, report)
            print(f"Report written: {out_json}")
            print(f"Report written: {out_md}")
        return 0
    finally:
        await db.close()


async def _run_direct(
    *,
    user_ids: list[str],
    client_id: str,
    use_demo_llm: bool,
    report_dir: Path | None,
    device_override: str = "",
) -> int:
    _ensure_src_path()
    from shuxin.voice.db import PostgresDatabase
    from shuxin.voice.postgres_repository import VoicePostgresRepository
    from shuxin.voice.config import DeviceConfigProvider
    from shuxin.voice.service import VoiceService

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("ERROR: DATABASE_URL is required", file=sys.stderr)
        return 1

    run_id = f"e2e-{uuid.uuid4().hex[:12]}"
    timestamp = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {
        "run_id": run_id,
        "timestamp": timestamp,
        "llm_source": "DEMO_LLM env" if use_demo_llm else "device + user llm_config merge",
        "users": user_ids,
        "sessions": [],
        "isolation_check": None,
        "overall": "FAIL",
    }

    db = PostgresDatabase(database_url)
    await db.connect()
    repo = VoicePostgresRepository(db.pool)
    try:
        print("== Ensuring E2E users")
        await _ensure_e2e_users(repo)

        device_provider = DeviceConfigProvider(
            os.environ.get("VOICE_DEVICE_CONFIG", "data/devices.yaml")
        )
        service = VoiceService(device_provider)

        for user_id in user_ids:
            spec = _device_spec_for_user(user_id)
            device_id = device_override or spec["device_id"]
            session_report = await _run_user_session(
                repo=repo,
                service=service,
                user_id=user_id,
                device_id=device_id,
                client_id=client_id,
                use_demo_llm=use_demo_llm,
                mbti=spec.get("mbti", ""),
            )
            report["sessions"].append(session_report)
            if session_report["result"] != "PASS":
                print(
                    f"FAIL: user={user_id} reason={session_report.get('failure_reason')}",
                    file=sys.stderr,
                )
                if report_dir:
                    out_json, out_md = _write_reports(report_dir / run_id, report)
                    print(f"Report written: {out_json}")
                    print(f"Report written: {out_md}")
                return 1

            # After alice, before bob: bob must not already have alice's interview memories
            alice_id = "e2e-user-alice"
            bob_id = "e2e-user-bob"
            if (
                user_id == alice_id
                and bob_id in user_ids[user_ids.index(user_id) + 1 :]
            ):
                pre_bob = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _mem0_search(bob_id, "面试 产品经理")
                )
                leaked = [line for line in pre_bob if "面试" in line or "产品经理" in line]
                isolation = {
                    "alice_user_id": alice_id,
                    "bob_user_id": bob_id,
                    "bob_mem0_before_bob_session": pre_bob,
                    "leaked_to_bob": leaked,
                    "result": "PASS" if not leaked else "FAIL",
                }
                report["isolation_check"] = isolation
                print(f"== Isolation (pre-bob): hits={len(pre_bob)} leaked={len(leaked)}")
                if leaked:
                    print("FAIL: Alice memories leaked to Bob before Bob's session", file=sys.stderr)
                    if report_dir:
                        out_json, out_md = _write_reports(report_dir / run_id, report)
                        print(f"Report written: {out_json}")
                        print(f"Report written: {out_md}")
                    return 1

        alice_id = "e2e-user-alice"
        bob_id = "e2e-user-bob"
        if alice_id in user_ids and bob_id in user_ids and report.get("isolation_check"):
            alice_mem = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _mem0_search(alice_id, "面试 产品经理")
            )
            bob_mem = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _mem0_search(bob_id, "面试 产品经理")
            )
            report["isolation_check"]["alice_mem0_after"] = alice_mem
            report["isolation_check"]["bob_mem0_after"] = bob_mem
            print(f"== Isolation (post-run): alice={len(alice_mem)} bob={len(bob_mem)}")

        report["overall"] = "PASS"
        print("PASS: three-tier memory E2E (direct mode)")

        if report_dir:
            out_json, out_md = _write_reports(report_dir / run_id, report)
            print(f"Report written: {out_json}")
            print(f"Report written: {out_md}")

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

    export_url = f"{admin_export_base.rstrip('/')}/voice/export?user_id={user_id}"
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
    parser = argparse.ArgumentParser(description="ChuXin voice three-tier memory E2E")
    parser.add_argument(
        "--user-id",
        default="",
        help="Single user override (default: run e2e-user-alice + e2e-user-bob)",
    )
    parser.add_argument(
        "--device-id",
        default="",
        help="Device for single --user-id mode (default: from E2E spec or demo-device-001)",
    )
    parser.add_argument("--client-id", default="e2e-memory-script")
    parser.add_argument("--ws", default="", help="WebSocket URL, e.g. ws://127.0.0.1:8765/ws/voice")
    parser.add_argument(
        "--export-base",
        default=os.environ.get("SHUXIN_E2E_HTTP_BASE", "http://127.0.0.1:8765"),
    )
    parser.add_argument(
        "--use-demo-llm",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use DEMO_LLM_* from env (default). Use --no-use-demo-llm to merge user llm_config.",
    )
    parser.add_argument(
        "--report-dir",
        default=os.environ.get("SHUXIN_E2E_REPORT_DIR", "scripts/e2e_reports"),
        help="Directory for JSON + Markdown reports (default: scripts/e2e_reports)",
    )
    parser.add_argument(
        "--suite",
        choices=["legacy", "smoke", "full"],
        default="legacy",
        help="legacy=alice/bob dual-user; smoke/full=YAML scenario suites",
    )
    parser.add_argument(
        "--llm-judge",
        action="store_true",
        help="Run LLM-as-judge scoring after each scenario (nightly CI)",
    )
    args = parser.parse_args()

    if args.ws:
        user_id = args.user_id or os.environ.get("SHUXIN_E2E_USER_ID", "demo-user")
        device_id = args.device_id or os.environ.get("SHUXIN_E2E_DEVICE_ID", "demo-device-001")
        return asyncio.run(
            _run_ws(
                ws_url=args.ws,
                device_code=device_id,
                device_secret=os.environ.get("SHUXIN_DEVICE_SHARED_SECRET", "dev-device-secret"),
                user_id=user_id,
                admin_export_base=args.export_base,
            )
        )

    if args.user_id:
        user_ids = [args.user_id]
    else:
        user_ids = [spec["user_id"] for spec in E2E_USER_SPECS]

    report_dir = Path(args.report_dir)
    if not report_dir.is_absolute():
        report_dir = _repo_root() / report_dir

    if args.suite in ("smoke", "full"):
        return asyncio.run(
            _run_suite(
                suite=args.suite,
                client_id=args.client_id,
                use_demo_llm=args.use_demo_llm,
                report_dir=report_dir,
                llm_judge=args.llm_judge,
            )
        )

    return asyncio.run(
        _run_direct(
            user_ids=user_ids,
            client_id=args.client_id,
            use_demo_llm=args.use_demo_llm,
            report_dir=report_dir,
            device_override=args.device_id,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
