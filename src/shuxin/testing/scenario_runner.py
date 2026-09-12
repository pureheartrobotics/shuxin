"""YAML 场景加载与 E2E 执行辅助。"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from shuxin.testing.memory_assertions import (
    cleanup_scenario_user,
    load_user_profile,
    mem0_hits_contain,
    profile_contains,
    reply_contains_any,
    reply_contains_keywords,
    summary_contains,
)
from shuxin.testing.e2e_helpers import E2E_TEST_TOKEN, apply_demo_llm, mem0_search, merge_device_llm
from shuxin.testing.mbti_scorer import check_identity_mbti, score_mbti_fidelity
from shuxin.voice.persistence.memory_summary import force_summary_trigger, sync_summary_json, user_summary_json_path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_scenarios(path: Path, *, suite: str = "smoke") -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    scenarios = data.get("scenarios") or []
    if suite == "full":
        return list(scenarios)
    return [
        s
        for s in scenarios
        if "smoke" in (s.get("suite_tags") or []) or suite == "all"
    ]


def load_all_scenario_files(suite: str = "smoke") -> list[dict[str, Any]]:
    e2e_dir = repo_root() / "data" / "e2e"
    all_scenarios: list[dict[str, Any]] = []
    for name in ("memory_scenarios.yaml", "mbti_drift_scenarios.yaml"):
        path = e2e_dir / name
        if path.exists():
            all_scenarios.extend(load_scenarios(path, suite=suite))
    return all_scenarios


def simulate_summary_expiry(user_id: str) -> None:
    """清空 rolling_summary 模拟 7 日窗口过期，保留 user_profile。"""
    path = user_summary_json_path(user_id)
    if not path.exists():
        return
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data["rolling_summary"] = ""
    data["recent_topics"] = []
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def evaluate_assertions(
    scenario: dict[str, Any],
    *,
    last_reply: str,
    rolling_summary: str,
    mem0_hits: list[str],
    user_home: Path,
    identity_check: dict[str, Any],
    mbti_score: dict[str, Any],
) -> list[str]:
    """返回失败原因列表（空 = PASS）。"""
    failures: list[str] = []
    assert_cfg = scenario.get("assert") or {}

    missing_kw = reply_contains_keywords(last_reply, assert_cfg.get("reply_keywords") or [])
    if missing_kw:
        failures.append(f"reply missing keywords: {missing_kw}")

    must_not = assert_cfg.get("reply_must_not_keywords") or []
    for kw in must_not:
        if kw and kw in (last_reply or ""):
            failures.append(f"reply must not contain: {kw}")

    any_kw = assert_cfg.get("reply_keywords_any") or []
    if any_kw and not reply_contains_any(last_reply, any_kw):
        failures.append(f"reply missing any of: {any_kw}")

    co_min = int(assert_cfg.get("co_occurrence_min") or 0)
    if co_min > 0 and any_kw:
        hit_count = sum(1 for kw in any_kw if kw in (last_reply or ""))
        if hit_count < co_min:
            failures.append(f"co_occurrence {hit_count} < {co_min}")

    summary_kw = assert_cfg.get("rolling_summary_keywords") or []
    if summary_kw:
        missing = summary_contains(rolling_summary, summary_kw)
        if missing:
            failures.append(f"rolling_summary missing: {missing}")

    min_chars = int(assert_cfg.get("rolling_summary_min_chars") or 0)
    if min_chars and len((rolling_summary or "").strip()) < min_chars:
        failures.append(f"rolling_summary too short: {len(rolling_summary)} < {min_chars}")

    mem0_kw = assert_cfg.get("mem0_keywords") or []
    if mem0_kw:
        missing = mem0_hits_contain(mem0_hits, mem0_kw)
        if missing:
            failures.append(f"mem0 missing: {missing}")

    profile_expected = assert_cfg.get("user_profile_contains") or {}
    if profile_expected:
        profile = load_user_profile(user_home)
        missing = profile_contains(profile, profile_expected)
        if missing:
            failures.append(f"user_profile missing: {missing}")

    expected_mbti = assert_cfg.get("identity_mbti") or scenario.get("mbti") or ""
    if expected_mbti and not identity_check.get("pass", True):
        failures.append(
            f"identity drift: expected {identity_check.get('expected')} got {identity_check.get('actual')}"
        )

    min_hits = int(assert_cfg.get("mbti_min_hits") or 0)
    if min_hits > 0 and not mbti_score.get("pass", False):
        failures.append(f"mbti fidelity: {mbti_score.get('hit_count', 0)} hits < {min_hits}")

    return failures


async def run_scenario(
    scenario: dict[str, Any],
    *,
    repo: Any,
    service: Any,
    use_demo_llm: bool,
    client_id: str,
    mem0_grace_seconds: int = 5,
) -> dict[str, Any]:
    from shuxin.core.config import get_shuxin_home

    user_id = scenario["user_id"]
    device_id = scenario.get("device_id", "demo-device-002")
    mbti = scenario.get("mbti", "")

    await cleanup_scenario_user(user_id=user_id, repo=repo)

    report: dict[str, Any] = {
        "scenario_id": scenario.get("id", ""),
        "user_id": user_id,
        "device_id": device_id,
        "mbti": mbti,
        "timeline": [],
        "rolling_summary": "",
        "mem0_search_result": [],
        "identity_check": {},
        "mbti_score": {},
        "result": "FAIL",
        "failure_reason": "",
    }

    settings = await repo.authenticate_user(user_id, E2E_TEST_TOKEN)
    device = await repo.get_device(device_id)
    if use_demo_llm:
        apply_demo_llm(device)
    else:
        merge_device_llm(device, settings)

    user_home = get_shuxin_home() / "users" / settings.user_id
    user_home.mkdir(parents=True, exist_ok=True)
    session_id = f"e2e-{uuid.uuid4().hex[:12]}"
    await repo.ensure_session(
        session_id=session_id,
        user_id=settings.user_id,
        device_id=device_id,
        client_id=client_id,
    )

    last_reply = ""
    agent = None
    sessions = scenario.get("sessions") or []

    for session_idx, session in enumerate(sessions, start=1):
        wait = int(session.get("wait_seconds") or 0)
        if wait > 0:
            await asyncio.sleep(wait)

        if session.get("simulate_summary_expiry"):
            simulate_summary_expiry(settings.user_id)

        if agent is None:
            agent = service.create_agent(device, user_home=user_home)
            agent.context.metadata["channel"] = "voice"
            await asyncio.get_event_loop().run_in_executor(None, agent.initialize)

        for turn_idx, line in enumerate(session.get("turns") or [], start=1):
            started = time.perf_counter()
            reply = await asyncio.get_event_loop().run_in_executor(
                None, lambda text=line: agent.chat(text).strip()
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            last_reply = reply
            turn_record = {
                "session": session_idx,
                "turn": turn_idx,
                "user": line,
                "agent": reply,
                "elapsed_ms": elapsed_ms,
            }
            report["timeline"].append(turn_record)
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

        if session.get("force_summary", True):
            merge_result = await force_summary_trigger(repo, settings, device)
            report["timeline"].append(
                {"session": session_idx, "event": "force_summary", "result": merge_result}
            )
            summary = await repo.export_summary(settings)
            sync_summary_json(settings.user_id, summary)

        if session_idx < len(sessions):
            if agent is not None:
                agent.shutdown()
                agent = None
            await asyncio.sleep(mem0_grace_seconds)

    if agent is not None:
        identity_check = check_identity_mbti(agent, mbti)
        report["identity_check"] = identity_check
        agent.shutdown()
    else:
        report["identity_check"] = {"expected": mbti, "actual": "", "pass": False}

    summary = await repo.export_summary(settings)
    rolling = str(summary.get("rolling_summary") or "").strip()
    report["rolling_summary"] = rolling

    mem0_hits = await asyncio.get_event_loop().run_in_executor(
        None, lambda: mem0_search(user_id, last_reply or "用户")
    )
    report["mem0_search_result"] = mem0_hits

    mbti_score = score_mbti_fidelity(last_reply, mbti, min_hits=int((scenario.get("assert") or {}).get("mbti_min_hits") or 0))
    report["mbti_score"] = mbti_score

    failures = evaluate_assertions(
        scenario,
        last_reply=last_reply,
        rolling_summary=rolling,
        mem0_hits=mem0_hits,
        user_home=user_home,
        identity_check=report["identity_check"],
        mbti_score=mbti_score,
    )
    if failures:
        report["failure_reason"] = "; ".join(failures)
    else:
        report["result"] = "PASS"

    return report
