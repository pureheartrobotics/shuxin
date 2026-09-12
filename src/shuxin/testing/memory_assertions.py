"""记忆与场景断言工具（单元测试 + E2E 共用）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Iterable


def reply_contains_keywords(reply: str, keywords: Iterable[str]) -> list[str]:
    """返回 reply 中未命中的关键词列表（空列表表示全部命中）。"""
    text = reply or ""
    return [kw for kw in keywords if kw and kw not in text]


def reply_contains_any(reply: str, keywords: Iterable[str]) -> bool:
    return any(kw in (reply or "") for kw in keywords if kw)


def mem0_hits_contain(hits: list[str], keywords: Iterable[str]) -> list[str]:
    joined = "\n".join(hits)
    return [kw for kw in keywords if kw and kw not in joined]


def summary_contains(summary: str, keywords: Iterable[str]) -> list[str]:
    text = summary or ""
    return [kw for kw in keywords if kw and kw not in text]


def profile_contains(profile: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """检查 user_profile.json 字段是否包含期望值（字符串子串匹配）。"""
    missing: list[str] = []
    for key, value in expected.items():
        actual = profile.get(key)
        if actual is None:
            missing.append(f"{key}=<{value}>")
            continue
        if isinstance(value, str):
            if value not in str(actual):
                missing.append(f"{key}={value}")
        elif isinstance(value, list):
            actual_list = actual if isinstance(actual, list) else [actual]
            for item in value:
                if not any(str(item) in str(x) for x in actual_list):
                    missing.append(f"{key} contains {item}")
        elif actual != value:
            missing.append(f"{key}={value}")
    return missing


def count_mem0_facts_in_summary(summary_text: str, fact_prefix: str = "fact-") -> int:
    return sum(1 for line in summary_text.splitlines() if fact_prefix in line)


def cleanup_local_user_state(user_home: Path) -> None:
    """删除用户本地 companion / summaries / memory / user_profile。"""
    for sub in ("companion", "summaries", "memory"):
        path = user_home / sub
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    profile = user_home / "user_profile.json"
    if profile.exists():
        profile.unlink()


def load_user_profile(user_home: Path) -> dict[str, Any]:
    path = user_home / "user_profile.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


async def cleanup_scenario_user(
    *,
    user_id: str,
    repo: Any | None = None,
    mem0_client: Any | None = None,
) -> None:
    """全量清洗场景用户：Qdrant(Mem0) + Postgres shared_memory + 本地文件。"""
    from shuxin.core.config import get_shuxin_home

    user_home = get_shuxin_home() / "users" / user_id

    if mem0_client is not None:
        try:
            mem0_client.delete_all(user_id=user_id)
        except TypeError:
            try:
                mem0_client.delete_all(filters={"user_id": user_id})
            except Exception:
                pass
        except Exception:
            pass
    elif _mem0_enabled():
        from shuxin.core.memory import MemoryManager

        mem = MemoryManager(data_dir=str(user_home / "memory"))
        if mem._mem0_client is not None:
            try:
                mem._mem0_client.delete_all(user_id=user_id)
            except TypeError:
                try:
                    mem._mem0_client.delete_all(filters={"user_id": user_id})
                except Exception:
                    pass
            except Exception:
                pass

    if repo is not None:
        pool = getattr(repo, "pool", None)
        if pool is not None:
            await pool.execute(
                "DELETE FROM shared_memory WHERE user_id = $1",
                user_id,
            )

    cleanup_local_user_state(user_home)


def _mem0_enabled() -> bool:
    import os

    raw = os.environ.get("SHUXIN_MEM0_ENABLED", "").strip().lower()
    return raw in ("1", "true", "yes", "on")
