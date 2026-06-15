"""LLM-as-Judge — 夜间对 E2E 对话质量打分（memory_recall / mbti_fidelity / personalization）。"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from shuxin.core.llm import LLMMessage, LLMProvider, PROVIDER_REGISTRY

logger = logging.getLogger("shuxin.testing.llm_judge")

JUDGE_DIMENSIONS = ("memory_recall", "mbti_fidelity", "personalization")


def _build_judge_prompt(scenario: dict[str, Any]) -> list[dict[str, str]]:
    turns_text = []
    for turn in scenario.get("turns", []):
        turns_text.append(f"用户: {turn.get('user', '')}")
        turns_text.append(f"初心: {turn.get('agent', '')}")
    system = (
        "你是 AI 陪伴产品质量评审员。根据对话记录，对以下三个维度各打 1-5 分：\n"
        "1. memory_recall — 是否准确回忆用户先前分享的信息\n"
        "2. mbti_fidelity — 回复风格是否符合指定 MBTI 人格（不被用户带偏）\n"
        "3. personalization — 是否体现对用户的个性化理解（多 fact 共现）\n\n"
        "只输出 JSON，格式："
        '{"memory_recall": 4, "mbti_fidelity": 3, "personalization": 5, "reason": "简短说明"}'
    )
    user = (
        f"场景: {scenario.get('id', '')}\n"
        f"目标 MBTI: {scenario.get('mbti', '')}\n"
        f"期望关键词: {scenario.get('assert_keywords', [])}\n\n"
        f"对话记录:\n" + "\n".join(turns_text)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_judge_response(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # 尝试从 markdown code block 提取
    if "```" in text:
        inner = text.split("```")[1]
        if inner.startswith("json"):
            inner = inner[4:]
        try:
            data = json.loads(inner.strip())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {"memory_recall": 0, "mbti_fidelity": 0, "personalization": 0, "reason": "parse_failed"}


def judge_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """对单个场景对话调用 LLM 判分。无 API key 时返回 skip。"""
    api_key = (
        os.environ.get("DEMO_LLM_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )
    if not api_key:
        return {"skipped": True, "reason": "no_api_key"}

    provider_type = os.environ.get("DEMO_LLM_PROVIDER", "openai").strip() or "openai"
    provider_info = PROVIDER_REGISTRY.get(provider_type, PROVIDER_REGISTRY["openai"])
    base_url = (
        os.environ.get("DEMO_LLM_BASE_URL", "").strip()
        or os.environ.get("OPENAI_BASE_URL", "").strip()
    )
    model = (
        os.environ.get("DEMO_LLM_MODEL", "").strip()
        or os.environ.get("OPENAI_MODEL", "").strip()
        or provider_info.get("default_model", "gpt-4o-mini")
    )

    messages = _build_judge_prompt(scenario)
    provider = LLMProvider()
    try:
        provider.initialize(
            provider_type=provider_type,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        llm_messages = [
            LLMMessage(role=str(m["role"]), content=str(m["content"])) for m in messages
        ]
        response = provider.chat(llm_messages, max_tokens=256, temperature=0.2)
        scores = _parse_judge_response(response.content or "")
        scores["skipped"] = False
        return scores
    except Exception as exc:
        logger.warning("LLM judge failed: %s", exc)
        return {"skipped": True, "reason": str(exc)}


def judge_report(report: dict[str, Any]) -> dict[str, Any]:
    """对完整 E2E report 中每个 session 判分，写入 judge 字段。"""
    judged_sessions: list[dict[str, Any]] = []
    for session in report.get("sessions", []):
        scenario = {
            "id": session.get("scenario_id") or session.get("user_id", ""),
            "mbti": session.get("mbti", ""),
            "assert_keywords": session.get("assert_keywords", []),
            "turns": session.get("session_a_turns", [])
            + [{"user": session.get("session_b", {}).get("user", ""), "agent": session.get("session_b", {}).get("agent", "")}],
        }
        scores = judge_scenario(scenario)
        judged_sessions.append({"user_id": session.get("user_id"), "judge": scores})
    return {"sessions": judged_sessions}
