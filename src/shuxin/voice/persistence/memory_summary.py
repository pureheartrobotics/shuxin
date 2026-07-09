"""Voice 中期记忆：规则 topics + 周期性 LLM 滚动摘要（7 日窗口）。"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from shuxin.core.config import Config, get_shuxin_home
from shuxin.core.llm import LLMMessage, LLMProvider, PROVIDER_REGISTRY
from shuxin.voice.config.config import DeviceConfig

logger = logging.getLogger("shuxin.voice.persistence.memory_summary")

SUMMARY_WINDOW_DAYS = 7
MAX_RECENT_TOPICS = 10
SUMMARY_EVERY_N_ENV = "SHUXIN_SUMMARY_EVERY_N"
SUMMARY_MODEL_ENV = "SHUXIN_SUMMARY_MODEL"
SUMMARY_MAX_TOKENS_ENV = "SHUXIN_SUMMARY_MAX_TOKENS"
DEFAULT_SUMMARY_EVERY_N = 5
DEFAULT_SUMMARY_MAX_TOKENS = 512

_TOPIC_PATTERNS = (
    re.compile(r"(?:关于|聊聊|说说)([^，。,.!！?？\s]{2,24})"),
    re.compile(r"(?:今天|最近|这几天)([^，。,.!！?？\s]{2,20})"),
    re.compile(r"(?:我想|我要)([^，。,.!！?？\s]{2,20})"),
)


def memory_field_defaults() -> dict[str, Any]:
    return {
        "rolling_summary": "",
        "summary_updated_at": "",
        "recent_topics": [],
        "turns_since_summary": 0,
        "summary_window_days": SUMMARY_WINDOW_DAYS,
    }


def merge_summary_with_stats(existing: dict[str, Any] | None, stats: dict[str, Any]) -> dict[str, Any]:
    """保留中期记忆字段，叠加本轮统计（turn_count、配额等）。"""
    merged = {**memory_field_defaults(), **(existing or {})}
    merged.update(stats)
    for key, value in memory_field_defaults().items():
        if key not in stats and key in (existing or {}):
            merged[key] = (existing or {}).get(key, value)
    return merged


def extract_topic_candidates(user_text: str) -> list[str]:
    text = (user_text or "").strip()
    if not text:
        return []
    topics: list[str] = []
    for pattern in _TOPIC_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip()
            if candidate and candidate not in topics:
                topics.append(candidate)
    if not topics and len(text) >= 6:
        snippet = text[:40].strip()
        if snippet:
            topics.append(snippet)
    return topics


def apply_turn_to_summary(summary: dict[str, Any], user_text: str) -> dict[str, Any]:
    """规则层更新 recent_topics 与 turns_since_summary。"""
    updated = dict(summary)
    updated["turns_since_summary"] = int(updated.get("turns_since_summary") or 0) + 1
    topics = list(updated.get("recent_topics") or [])
    for topic in extract_topic_candidates(user_text):
        if topic in topics:
            topics.remove(topic)
        topics.insert(0, topic)
    updated["recent_topics"] = topics[:MAX_RECENT_TOPICS]
    updated.setdefault("summary_window_days", SUMMARY_WINDOW_DAYS)
    return updated


def summary_every_n() -> int:
    raw = os.environ.get(SUMMARY_EVERY_N_ENV, str(DEFAULT_SUMMARY_EVERY_N))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SUMMARY_EVERY_N
    return max(1, value)


def summary_max_tokens() -> int:
    raw = os.environ.get(SUMMARY_MAX_TOKENS_ENV, str(DEFAULT_SUMMARY_MAX_TOKENS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SUMMARY_MAX_TOKENS
    return max(64, value)


def should_merge_summary(summary: dict[str, Any], *, force: bool = False) -> bool:
    if force:
        return True
    return int(summary.get("turns_since_summary") or 0) >= summary_every_n()


def user_summary_json_path(user_id: str) -> Path:
    return get_shuxin_home() / "users" / user_id / "summaries" / "shared_memory.json"


def sync_summary_json(user_id: str, summary: dict[str, Any]) -> None:
    """把 shared_memory 同步到用户 home，供陪伴插件 pre_llm_call 读取。"""
    path = user_summary_json_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def format_recent_turns(turns: Iterable[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in turns:
        user_text = str(item.get("user_text") or "").strip()
        reply_text = str(item.get("reply_text") or "").strip()
        if not user_text and not reply_text:
            continue
        lines.append(f"用户: {user_text}")
        if reply_text:
            lines.append(f"初心: {reply_text}")
    return "\n".join(lines)


def build_merge_messages(
    *,
    existing_summary: str,
    recent_topics: list[str],
    recent_turns: list[dict[str, Any]],
) -> list[dict[str, str]]:
    topics_text = "、".join(recent_topics[:5]) if recent_topics else "无"
    turns_text = format_recent_turns(recent_turns) or "无"
    system = (
        "你是初心的记忆整理助手。请把「已有 7 日概况」与「新增对话」合并成一段简洁中文摘要，"
        f"只保留最近 {SUMMARY_WINDOW_DAYS} 天内对用户陪伴有价值的信息（情绪、关系、近况、偏好、未完成话题）。"
        "不要编造；没有新信息则保留原摘要。控制在 400 字以内。"
        "姓名、城市、长期喜好等常驻信息已由 user_profile 单独保存，摘要侧重近期情绪与未完成话题。"
    )
    user = (
        f"【已有 7 日概况】\n{existing_summary or '（暂无）'}\n\n"
        f"【近期话题】\n{topics_text}\n\n"
        f"【新增对话片段】\n{turns_text}\n\n"
        "请输出合并后的 7 日概况正文，不要加标题或列表符号。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_summary_llm_config(device: DeviceConfig | None) -> Config:
    config = Config.load()
    if device is not None:
        if device.llm.provider:
            config.llm.provider = device.llm.provider
        if device.llm.model:
            config.llm.model = device.llm.model
        if device.llm.base_url:
            config.llm.base_url = device.llm.base_url
        if device.llm.api_key:
            config.llm.api_key = device.llm.api_key
    summary_model = os.environ.get(SUMMARY_MODEL_ENV, "").strip()
    if summary_model:
        config.llm.model = summary_model
    config.llm.max_tokens = summary_max_tokens()
    return config


def merge_summary_with_llm(
    *,
    device: DeviceConfig | None,
    existing_summary: str,
    recent_topics: list[str],
    recent_turns: list[dict[str, Any]],
) -> str:
    """同步调用 LLM 合并滚动摘要；在 asyncio.to_thread 中执行。"""
    messages = build_merge_messages(
        existing_summary=existing_summary,
        recent_topics=recent_topics,
        recent_turns=recent_turns,
    )
    config = build_summary_llm_config(device)
    provider_type = config.llm.provider or "openai"
    provider_info = PROVIDER_REGISTRY.get(provider_type, {})
    env_api_key = provider_info.get("env_api_key", "OPENAI_API_KEY")
    env_base_url = provider_info.get("env_base_url", "OPENAI_BASE_URL")
    api_key = config.llm.api_key or os.environ.get(env_api_key, "")
    if not api_key:
        logger.debug("skip rolling summary merge: no API key")
        return existing_summary

    provider = LLMProvider()
    try:
        provider.initialize(
            provider_type=provider_type,
            api_key=api_key,
            base_url=config.llm.base_url or os.environ.get(env_base_url, ""),
            model=config.llm.model or provider_info.get("default_model", ""),
        )
        llm_messages = [
            LLMMessage(role=str(item["role"]), content=str(item["content"]))
            for item in messages
        ]
        response = provider.chat(
            llm_messages,
            max_tokens=config.llm.max_tokens,
            temperature=0.3,
        )
        text = (response.content or "").strip()
        return text or existing_summary
    except Exception as exc:
        logger.warning("rolling summary LLM merge failed: %s", exc)
        return existing_summary


def finalize_summary_after_merge(summary: dict[str, Any], merged_text: str) -> dict[str, Any]:
    updated = dict(summary)
    updated["rolling_summary"] = merged_text.strip()
    updated["summary_updated_at"] = datetime.now().isoformat(timespec="seconds")
    updated["turns_since_summary"] = 0
    updated.setdefault("summary_window_days", SUMMARY_WINDOW_DAYS)
    return updated


async def force_summary_trigger(repo: Any, user_settings: Any, device: Any | None = None) -> dict[str, Any]:
    """E2E / 测试用：在 session 结束时强制触发 rolling_summary 合并。"""
    return await repo.maybe_merge_rolling_summary(user_settings, device, force=True)
