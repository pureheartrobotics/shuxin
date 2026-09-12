"""初心记忆系统

短期：会话消息列表（进程内）。
长期：Mem0 + Qdrant（``SHUXIN_MEM0_ENABLED=1``）或 legacy ``facts.json``。

Mem0 仅在 Docker 镜像内安装（``requirements-voice-app.txt``）；默认关闭时行为与旧版一致。
"""

from __future__ import annotations

import json
import logging
import os
os.environ["MEM0_TELEMETRY"] = "False"
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dataclasses import dataclass, field

import time

logger = logging.getLogger("shuxin.memory")

_MEM0_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="shuxin-mem0")
_MEM0_SEARCH_CACHE_TTL = 300  # 5 分钟内相同问题复用 embedding 结果，减少 TTFT

_SYNC_USER_PATTERNS = (
    re.compile(r"我叫([^，。,.!！?？]{1,20})"),
    re.compile(r"以后叫我([^，。,.!！?？]{1,20})"),
    re.compile(r"记住"),
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _user_id_from_data_dir(data_dir: Path) -> str:
    parts = data_dir.resolve().parts
    if "users" in parts:
        idx = parts.index("users")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return "default"


def _llm_credentials() -> tuple[str, str, str]:
    api_key = (
        os.environ.get("DEMO_LLM_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )
    base_url = (
        os.environ.get("DEMO_LLM_BASE_URL", "").strip()
        or os.environ.get("OPENAI_BASE_URL", "").strip()
    )
    model = (
        os.environ.get("DEMO_LLM_MODEL", "").strip()
        or os.environ.get("OPENAI_MODEL", "").strip()
        or "gpt-4o-mini"
    )
    return api_key, base_url, model


@dataclass
class MemoryEntry:
    """记忆条目 — 单条消息记录。"""
    role: str
    content: str
    timestamp: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FactMemory:
    """事实记忆 — legacy facts.json 条目。"""
    key: str
    value: str
    category: str = "general"
    confidence: float = 1.0
    created_at: str = ""
    updated_at: str = ""


class MemoryManager:
    """记忆管理器 — 短期记忆 + Mem0/Qdrant 或 facts.json 长期记忆。"""

    def __init__(self, data_dir: Optional[str] = None) -> None:
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path.home() / ".shuxin" / "memory"

        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("无法创建记忆目录 %s: %s", self.data_dir, e)

        self.short_term: List[MemoryEntry] = []
        self.max_short_term: int = 100
        self.facts: Dict[str, FactMemory] = {}
        self._lock = threading.Lock()

        self._user_id = _user_id_from_data_dir(self.data_dir)
        self._last_user_text: str = ""
        self._pending_user_text: str = ""
        self._mem0_client: Any = None
        self._mem0_init_attempted = False
        self._mem0_top_k = max(1, int(os.environ.get("SHUXIN_MEM0_SEARCH_TOP_K", "8") or "8"))
        # 搜索结果缓存：{query: (timestamp, results)}，减少重复 embedding API 调用
        self._mem0_search_cache: Dict[str, tuple] = {}
        self._mem0_cache_lock = threading.Lock()
        self._last_mem0_results: List[str] = []

        self._load_facts()
        if self._mem0_enabled():
            self._ensure_mem0()
            self._migrate_facts_to_mem0_once()

    @staticmethod
    def _mem0_enabled() -> bool:
        return _env_bool("SHUXIN_MEM0_ENABLED", default=False)

    def _build_mem0_config(self) -> Optional[Dict[str, Any]]:
        api_key, base_url, model = _llm_credentials()
        if not api_key:
            logger.warning("Mem0 未配置 API key（DEMO_LLM_API_KEY / OPENAI_API_KEY）")
            return None

        embed_model = os.environ.get("SHUXIN_EMBED_MODEL", "text-embedding-3-small").strip()
        embed_dims = int(os.environ.get("SHUXIN_EMBED_DIMS", "1536") or "1536")
        collection = os.environ.get("SHUXIN_QDRANT_COLLECTION", "shuxin_memories").strip()
        qdrant_host = os.environ.get("SHUXIN_QDRANT_HOST", "qdrant").strip()
        qdrant_port = int(os.environ.get("SHUXIN_QDRANT_PORT", "6333") or "6333")
        qdrant_api_key = os.environ.get("SHUXIN_QDRANT_API_KEY", "").strip()

        qdrant_config: Dict[str, Any] = {
            "collection_name": collection,
            "embedding_model_dims": embed_dims,
            "on_disk": True,
        }
        if qdrant_api_key:
            qdrant_config["url"] = f"http://{qdrant_host}:{qdrant_port}"
            qdrant_config["api_key"] = qdrant_api_key
        else:
            qdrant_config["host"] = qdrant_host
            qdrant_config["port"] = qdrant_port

        openai_llm: Dict[str, Any] = {"model": model, "api_key": api_key}
        openai_embed: Dict[str, Any] = {"model": embed_model, "api_key": api_key}
        if base_url:
            openai_llm["openai_base_url"] = base_url
            openai_embed["openai_base_url"] = base_url

        return {
            "vector_store": {"provider": "qdrant", "config": qdrant_config},
            "llm": {"provider": "openai", "config": openai_llm},
            "embedder": {"provider": "openai", "config": openai_embed},
        }

    def _ensure_mem0(self) -> None:
        if self._mem0_client is not None or self._mem0_init_attempted:
            return
        self._mem0_init_attempted = True
        config = self._build_mem0_config()
        if not config:
            return
        try:
            from mem0 import Memory

            self._mem0_client = Memory.from_config(config)
            logger.info(
                "Mem0 已连接 Qdrant collection=%s user_id=%s",
                config["vector_store"]["config"].get("collection_name"),
                self._user_id,
            )
        except ImportError:
            logger.warning("未安装 mem0ai，回退 facts.json（需在 Docker 镜像中安装 requirements-voice-app.txt）")
        except Exception as exc:
            logger.warning("Mem0 初始化失败，回退 facts.json: %s", exc)

    def _migrate_facts_to_mem0_once(self) -> None:
        if self._mem0_client is None or not self.facts:
            return
        marker = self.data_dir / ".mem0_facts_imported"
        if marker.exists():
            return
        for fact in self.facts.values():
            try:
                self._mem0_add_text(
                    f"{fact.key}: {fact.value}",
                    infer=False,
                    metadata={"category": fact.category, "fact_key": fact.key, "source": "facts.json"},
                )
            except Exception as exc:
                logger.warning("导入 fact %s 到 Mem0 失败: %s", fact.key, exc)
        try:
            marker.write_text(datetime.now().isoformat(), encoding="utf-8")
        except OSError:
            pass

    def _mem0_add_text(
        self,
        text: str,
        *,
        infer: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._mem0_client is None or not text.strip():
            return
        kwargs: Dict[str, Any] = {"user_id": self._user_id, "infer": infer}
        if metadata:
            kwargs["metadata"] = metadata
        self._mem0_client.add(text.strip(), **kwargs)

    def _enqueue_turn_add(self, user_text: str, assistant_text: str, *, sync: bool = False) -> None:
        if not user_text.strip() or not assistant_text.strip():
            return

        def _run() -> None:
            self._ensure_mem0()
            if self._mem0_client is None:
                return
            try:
                messages = [
                    {"role": "user", "content": user_text.strip()},
                    {"role": "assistant", "content": assistant_text.strip()},
                ]
                self._mem0_client.add(messages, user_id=self._user_id)
            except Exception as exc:
                logger.warning("Mem0 add 回合失败: %s", exc)

        if sync:
            _run()
        else:
            _MEM0_EXECUTOR.submit(_run)

    def _is_low_semantic_query(self, query: str) -> bool:
        q = query.strip()
        if len(q) < 5:
            # 涉及显式记忆设定的特殊前缀，不进行绕过
            if any(p.search(q) for p in _SYNC_USER_PATTERNS):
                return False
            return True
        # 长但无实际实体或语义意图的日常语气词
        fillers = {"我不知道", "你想说什么", "那当然啦", "原来是这样", "没有关系", "没关系啊", "没事的哈"}
        if q in fillers:
            return True
        return False

    def _should_sync_mem0_add(self, user_text: str) -> bool:
        text = user_text.strip()
        if not text:
            return False
        return any(p.search(text) for p in _SYNC_USER_PATTERNS)

    def _search_mem0(self, query: str) -> List[str]:
        self._ensure_mem0()
        if self._mem0_client is None:
            return []
        q = query.strip()
        if not q:
            return []

        # 低语义/短查询绕过：复用最近一次的有效检索结果，将首字延迟 (TTFT) 降低 1~2s 左右阻碍
        if self._is_low_semantic_query(q) and self._last_mem0_results:
            logger.debug("[Mem0-Bypass] 针对低语义/短查询 '%s' 复用上一次有效结果: %s", q, self._last_mem0_results)
            return self._last_mem0_results

        # 缓存命中：相同查询文本 5 分钟内直接复用结果，避免重复调 embedding API
        now = time.monotonic()
        with self._mem0_cache_lock:
            cached = self._mem0_search_cache.get(q)
            if cached is not None:
                ts, results = cached
                if now - ts < _MEM0_SEARCH_CACHE_TTL:
                    logger.debug("[Mem0] 缓存命中，跳过 embedding 请求")
                    self._last_mem0_results = results
                    return results
            # 清理过期缓存，防止无限增长
            if len(self._mem0_search_cache) > 32:
                expired = [k for k, (t, _) in self._mem0_search_cache.items()
                           if now - t >= _MEM0_SEARCH_CACHE_TTL]
                for k in expired:
                    self._mem0_search_cache.pop(k, None)

        t0 = time.monotonic()
        try:
            raw = self._mem0_client.search(
                q,
                filters={"user_id": self._user_id},
                top_k=self._mem0_top_k,
            )
        except Exception as exc:
            logger.warning("Mem0 search 失败: %s", exc)
            return []
        logger.debug("[Mem0] embedding+search 耗时 %.0fms", (time.monotonic() - t0) * 1000)

        items: List[Any] = []
        if isinstance(raw, dict):
            items = raw.get("results") or raw.get("memories") or []
        elif isinstance(raw, list):
            items = raw

        lines: List[str] = []
        for item in items:
            if isinstance(item, str) and item.strip():
                lines.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            text = (
                item.get("memory")
                or item.get("text")
                or item.get("content")
                or (item.get("metadata") or {}).get("text")
            )
            if text and str(text).strip():
                lines.append(str(text).strip())
        # 防御性截断：即使 Mem0 端忽略 top_k 也不会超注入上限
        results = lines[: self._mem0_top_k]

        # 写入缓存与上一次结果状态
        with self._mem0_cache_lock:
            self._mem0_search_cache[q] = (time.monotonic(), results)
        self._last_mem0_results = results
        return results

    def _recent_user_text(self) -> str:
        with self._lock:
            for entry in reversed(self.short_term):
                if entry.role == "user" and entry.content.strip():
                    return entry.content.strip()
        return ""

    def _legacy_facts_summary(self) -> str:
        if not self.facts:
            return "暂无关于用户的长期记忆。"
        lines = ["## 关于用户的记忆"]
        for fact in self.facts.values():
            lines.append(f"- {fact.key}: {fact.value}")
        return "\n".join(lines)

    # ---- 短期记忆 ----

    def add_message(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        entry = MemoryEntry(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            metadata=metadata or {},
        )
        with self._lock:
            self.short_term.append(entry)
            if len(self.short_term) > self.max_short_term:
                self.short_term = self.short_term[-self.max_short_term:]

        if role == "user":
            text = content.strip()
            self._last_user_text = text
            self._pending_user_text = text
            if self._mem0_enabled() and self._should_sync_mem0_add(text):
                self._ensure_mem0()
                self._mem0_add_text(text, infer=False, metadata={"source": "explicit_user"})
        elif role == "assistant" and self._mem0_enabled():
            user_text = self._pending_user_text
            self._pending_user_text = ""
            if user_text:
                self._enqueue_turn_add(
                    user_text,
                    content,
                    sync=self._should_sync_mem0_add(user_text),
                )

    def get_recent(self, n: int = 10) -> List[MemoryEntry]:
        with self._lock:
            return self.short_term[-n:]

    def get_history(self) -> List[MemoryEntry]:
        with self._lock:
            return list(self.short_term)

    def clear_short_term(self) -> None:
        with self._lock:
            self.short_term.clear()
        self._pending_user_text = ""

    # ---- 长期记忆 ----

    def add_fact(
        self,
        key: str,
        value: str,
        category: str = "general",
        confidence: float = 1.0,
    ) -> None:
        now = datetime.now().isoformat()
        with self._lock:
            if key in self.facts:
                self.facts[key].value = value
                self.facts[key].confidence = confidence
                self.facts[key].updated_at = now
            else:
                self.facts[key] = FactMemory(
                    key=key,
                    value=value,
                    category=category,
                    confidence=confidence,
                    created_at=now,
                    updated_at=now,
                )
        self._save_facts()
        if self._mem0_enabled():
            self._ensure_mem0()
            self._mem0_add_text(
                f"{key}: {value}",
                infer=False,
                metadata={"category": category, "fact_key": key},
            )

    def get_fact(self, key: str) -> Optional[str]:
        fact = self.facts.get(key)
        return fact.value if fact else None

    def get_facts_by_category(self, category: str) -> List[FactMemory]:
        return [f for f in self.facts.values() if f.category == category]

    def get_all_facts(self) -> List[FactMemory]:
        return list(self.facts.values())

    def get_facts_summary(self) -> str:
        if self._mem0_enabled():
            query = self._last_user_text or self._recent_user_text()
            if not query:
                hits = []
            else:
                from concurrent.futures import TimeoutError
                future = _MEM0_EXECUTOR.submit(self._search_mem0, query)
                try:
                    hits = future.result(timeout=0.8)
                except TimeoutError:
                    logger.warning("[Mem0-Timeout] 长期记忆检索超时(>800ms)，降级复用历史记忆以保证 TTFT 体验")
                    hits = self._last_mem0_results

            if hits:
                lines = ["## 关于用户的记忆（相关）"]
                for line in hits:
                    lines.append(f"- {line}")
                return "\n".join(lines)
            if self.facts:
                return self._legacy_facts_summary()
            return "暂无关于用户的长期记忆。"
        return self._legacy_facts_summary()

    def _load_facts(self) -> None:
        facts_file = self.data_dir / "facts.json"
        if not facts_file.exists():
            return
        try:
            data = json.loads(facts_file.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                logger.warning("事实记忆文件格式错误，期望 JSON 数组")
                return
            for item in data:
                if not isinstance(item, dict):
                    continue
                fact = FactMemory(**item)
                self.facts[fact.key] = fact
            logger.info("已加载 %d 条事实记忆", len(self.facts))
        except json.JSONDecodeError as e:
            logger.warning("事实记忆文件 JSON 解析失败: %s", e)
        except OSError as e:
            logger.warning("无法读取事实记忆文件: %s", e)
        except Exception as e:
            logger.warning("加载事实记忆失败: %s", e)

    def _save_facts(self) -> None:
        facts_file = self.data_dir / "facts.json"
        try:
            data = [
                {
                    "key": f.key,
                    "value": f.value,
                    "category": f.category,
                    "confidence": f.confidence,
                    "created_at": f.created_at,
                    "updated_at": f.updated_at,
                }
                for f in self.facts.values()
            ]
            facts_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("无法写入事实记忆文件: %s", e)
        except Exception as e:
            logger.warning("保存事实记忆失败: %s", e)

    def build_context(self, system_prompt: str, max_history: int = 20) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
        with self._lock:
            for entry in self.short_term[-max_history:]:
                messages.append({"role": entry.role, "content": entry.content})
        return messages
