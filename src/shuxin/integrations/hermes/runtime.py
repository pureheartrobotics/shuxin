"""把 Nous Hermes Agent 接到 Voice BFF。

语音会话不再走自研 ``shuxin.core.agent.Agent`` 主循环。Hermes 负责工具、
技能和多轮推理；本模块只提供 Voice 需要的鸭子类型（chat / chat_stream /
identity / context），并关掉终端类工具。
"""

from __future__ import annotations

import inspect
import logging
import os
import queue
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Iterator, List, Optional

from shuxin.core.config import Config
from shuxin.core.identity import IdentityEngine
from shuxin.core.soul import SoulEngine

logger = logging.getLogger("shuxin.hermes")

_HERMES_INIT_LOCK = threading.Lock()

DANGEROUS_TOOLSETS = (
    "terminal",
    "browser",
    "code_execution",
    "computer_use",
    "delegation",
    "cronjob",
    "file",
    "tts",
    "debugging",
)

VOICE_HINT = (
    "你正在通过语音和用户说话，对方听不见屏幕上的排版。"
    "用一两句到四句口语中文回复，不要用 markdown、列表或代码块。"
    "动作可用中文或英文括号，不要读出括号。"
    "你没有电脑终端。拍照、转头、走路由设备工具完成，不要假装已经执行。"
    "天气、附近地点、怎么走用 map_weather / map_search_places / map_directions，不要编气温或店名。"
)


def agent_runtime_name() -> str:
    return os.environ.get("SHUXIN_AGENT_RUNTIME", "hermes").strip().lower() or "hermes"


def create_voice_agent(config: Config) -> Any:
    """Voice 默认 Hermes；``SHUXIN_AGENT_RUNTIME=chuxin`` 才回退自研循环。"""
    name = agent_runtime_name()
    if name in {"chuxin", "legacy", "shuxin"}:
        from shuxin.core.agent import Agent

        logger.warning("voice agent runtime=chuxin (legacy)")
        return Agent(config)
    return HermesVoiceAgent(config)


def load_ai_agent_class() -> Any:
    errors: List[str] = []
    for spec in ("run_agent:AIAgent", "hermes_agent:AIAgent", "hermes_cli.run_agent:AIAgent"):
        module_name, attr = spec.split(":")
        try:
            module = __import__(module_name, fromlist=[attr])
            return getattr(module, attr)
        except Exception as exc:
            errors.append("%s (%s)" % (spec, exc))
    raise ImportError(
        "未安装 Hermes Agent。请在 Voice 镜像中 `pip install hermes-agent`，"
        "或把 NousResearch/hermes-agent 加到 PYTHONPATH。尝试: %s" % "; ".join(errors)
    )


def _filter_kwargs(fn: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return kwargs
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return kwargs
    return {key: value for key, value in kwargs.items() if key in signature.parameters}


@dataclass
class _AgentContext:
    turn_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class _SilentPlugins:
    def invoke_hook(self, *_args: Any, **_kwargs: Any) -> list:
        return []


@dataclass
class _LlmFacade:
    """给摄像头认图等路径提供 api_key / base_url / model。"""

    api_key: str = ""
    base_url: str = ""
    model: str = ""

    @property
    def provider(self) -> "_LlmFacade":
        return self


def _delta_text(delta: Any) -> str:
    if delta is None:
        return ""
    if isinstance(delta, str):
        return delta
    if isinstance(delta, dict):
        return str(delta.get("text") or delta.get("delta") or "")
    return str(delta)


class HermesVoiceAgent:
    """对 Voice WebSocket / VoiceService 暴露与初心 Agent 相近的表面。"""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config.load()
        self.context = _AgentContext()
        self.soul = SoulEngine()
        self.identity = IdentityEngine()
        self.llm = _LlmFacade()
        self.plugins = _SilentPlugins()
        self.tool_loop_callbacks = None
        self._system_prompt = ""
        self._initialized = False
        self._lock = threading.Lock()
        self._hermes: Any = None
        self._history: List[Any] = []
        self._hermes_home = Path(self.config.shuxin_home) / "hermes"
        self.robot_bridge = None
        self.memory = None

    def initialize(self) -> None:
        if self._initialized:
            return
        self.soul.load(self.config.soul.soul_path)
        self.identity.set_mbti(self.soul.profile.mbti)
        self.identity.profile.name = self.soul.profile.name
        self.identity.profile.species = self.soul.profile.species
        self._build_system_prompt()

        api_key = (self.config.llm.api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("Hermes 需要 LLM api_key（设备/用户配置或 OPENAI_API_KEY）")
        from shuxin.core.llm import _normalize_openai_base_url

        base_url = _normalize_openai_base_url(self.config.llm.base_url or "") or None
        self.llm = _LlmFacade(
            api_key=api_key,
            base_url=base_url or "",
            model=self.config.llm.model or "",
        )

        self._hermes_home.mkdir(parents=True, exist_ok=True)
        from shuxin.integrations.hermes.companion_hooks import install_companion_hooks
        from shuxin.integrations.hermes.map_tools import register_map_tools
        from shuxin.integrations.hermes.robot_tools import register_robot_tools
        from shuxin.integrations.hermes.seed import seed_hermes_skills

        seed_hermes_skills(self._hermes_home)
        register_robot_tools()
        register_map_tools(self.config)
        install_companion_hooks()
        ai_agent = load_ai_agent_class()
        max_iterations = int(os.environ.get("SHUXIN_HERMES_MAX_ITERATIONS", "8"))
        max_tokens = int(getattr(self.config.llm, "max_tokens", 0) or 0) or None
        kwargs = _filter_kwargs(
            ai_agent.__init__,
            {
                "model": self.config.llm.model or "",
                "quiet_mode": True,
                "api_key": api_key,
                "base_url": base_url,
                "skip_context_files": True,
                "load_soul_identity": False,
                "disabled_toolsets": list(DANGEROUS_TOOLSETS),
                "ephemeral_system_prompt": self._system_prompt,
                "max_iterations": max_iterations,
                "max_tokens": max_tokens,
                "platform": "voice",
                "tool_start_callback": self._on_hermes_tool_start,
            },
        )
        with _HERMES_INIT_LOCK:
            with self._hermes_home_scope():
                self._hermes = ai_agent(**kwargs)
        self._initialized = True
        logger.info(
            "Hermes voice runtime ready model=%s base_url=%s iterations<=%s",
            self.config.llm.model,
            base_url or "",
            max_iterations,
        )

    def _build_system_prompt(self) -> None:
        parts = [
            self.soul.get_system_prompt_block(),
            self.identity.get_system_prompt_block(),
            VOICE_HINT,
        ]
        location = str(self.context.metadata.get("location_context") or "").strip()
        if location:
            parts.append(location)
        self._system_prompt = "\n\n".join(part for part in parts if part and part.strip())
        hermes = self._hermes
        if hermes is None:
            return
        if hasattr(hermes, "ephemeral_system_prompt"):
            hermes.ephemeral_system_prompt = self._system_prompt
        if hasattr(hermes, "_cached_system_prompt"):
            hermes._cached_system_prompt = None

    def get_system_prompt(self) -> str:
        return self._system_prompt

    def shutdown(self) -> None:
        self._hermes = None
        self._history = []
        self._initialized = False

    def _ensure_ready(self) -> None:
        if not self._initialized or self._hermes is None:
            self.initialize()

    def _on_hermes_tool_start(self, *_args: Any, **_kwargs: Any) -> None:
        self._notify_tool_start()

    def _notify_tool_start(self) -> None:
        callbacks = self.tool_loop_callbacks
        if callbacks is None:
            return
        starter: Optional[Callable[[str], None]] = getattr(callbacks, "on_tool_round_start", None)
        if starter:
            starter("hermes")

    @contextmanager
    def _hermes_home_scope(self) -> Iterator[None]:
        """按用户隔离 Hermes 家目录，避免改全局 OPENAI_* / HERMES_HOME 串会话。"""
        try:
            from hermes_constants import reset_hermes_home_override, set_hermes_home_override
        except ImportError:
            old = os.environ.get("HERMES_HOME")
            os.environ["HERMES_HOME"] = str(self._hermes_home)
            try:
                yield
            finally:
                if old is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = old
            return
        token = set_hermes_home_override(str(self._hermes_home))
        try:
            yield
        finally:
            reset_hermes_home_override(token)

    def _trim_history(self) -> None:
        limit = int(getattr(self.config, "max_history", 8) or 8)
        if limit <= 0 or not self._history:
            return
        user_indexes = [
            index
            for index, message in enumerate(self._history)
            if isinstance(message, dict) and message.get("role") == "user"
        ]
        if len(user_indexes) <= limit:
            return
        self._history = self._history[user_indexes[-limit] :]

    def chat(self, user_input: str) -> str:
        with self._lock:
            self.context.turn_count += 1
            self._ensure_ready()
            self._build_system_prompt()
            text = (user_input or "").strip()
            if not text:
                return ""
            with self._hermes_home_scope():
                reply = self._run_turn_bound(text)
            return (reply or "").strip()

    def chat_stream(self, user_input: str) -> Generator[str, None, None]:
        deltas: "queue.Queue[Optional[str]]" = queue.Queue()
        errors: List[BaseException] = []
        finals: List[str] = []

        def on_delta(delta: Any) -> None:
            text = _delta_text(delta)
            if text:
                deltas.put(text)

        def worker() -> None:
            try:
                with self._lock:
                    self.context.turn_count += 1
                    self._ensure_ready()
                    self._build_system_prompt()
                    text = (user_input or "").strip()
                    if not text:
                        return
                    with self._hermes_home_scope():
                        finals.append(self._run_turn_bound(text, stream_callback=on_delta))
            except BaseException as exc:
                errors.append(exc)
            finally:
                deltas.put(None)

        thread = threading.Thread(target=worker, daemon=True, name="hermes-voice-stream")
        thread.start()
        yielded = False
        while True:
            item = deltas.get()
            if item is None:
                break
            yielded = True
            yield item
        thread.join()
        if errors:
            raise errors[0]
        if not yielded and finals and finals[0]:
            yield finals[0]

    def _inject_map_facts(self, user_input: str) -> None:
        from shuxin.integrations.hermes.map_tools import prefetch_map_facts

        block = prefetch_map_facts(user_input)
        if not block:
            return
        self._system_prompt = "\n\n".join(
            part for part in (self._system_prompt, block) if part and part.strip()
        )
        hermes = self._hermes
        if hermes is None:
            return
        if hasattr(hermes, "ephemeral_system_prompt"):
            hermes.ephemeral_system_prompt = self._system_prompt
        if hasattr(hermes, "_cached_system_prompt"):
            hermes._cached_system_prompt = None

    def _run_turn_bound(self, user_input: str, stream_callback: Optional[Callable[..., Any]] = None) -> str:
        from shuxin.integrations.hermes.companion_hooks import bind_voice_agent, reset_voice_agent
        from shuxin.integrations.hermes.robot_tools import bind_robot_session, reset_robot_session

        token = bind_voice_agent(self)
        robot_token = bind_robot_session(self.robot_bridge)
        try:
            self._inject_map_facts(user_input)
            return self._run_turn(user_input, stream_callback=stream_callback)
        finally:
            reset_robot_session(robot_token)
            reset_voice_agent(token)

    def _run_turn(self, user_input: str, stream_callback: Optional[Callable[..., Any]] = None) -> str:
        hermes = self._hermes
        run_conversation = getattr(hermes, "run_conversation", None)
        if callable(run_conversation):
            kwargs = _filter_kwargs(
                run_conversation,
                {
                    "user_message": user_input,
                    "conversation_history": self._history or None,
                    "system_message": self._system_prompt,
                    "stream_callback": stream_callback,
                },
            )
            result = run_conversation(**kwargs)
            if isinstance(result, dict):
                messages = result.get("messages")
                if isinstance(messages, list) and messages:
                    self._history = messages
                    self._trim_history()
                return str(result.get("final_response") or "")
            return str(result or "")
        chat = getattr(hermes, "chat", None)
        if not callable(chat):
            raise RuntimeError("Hermes AIAgent 没有 chat / run_conversation")
        return str(chat(user_input) or "")
