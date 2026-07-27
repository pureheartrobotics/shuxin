from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from shuxin.voice.api.ws_session import _VoiceWebSocketSession
from shuxin.voice.service import VoiceService


class _WebSocket:
    client = None


class _Repo:
    pass


def _session(tmp_path: Path) -> _VoiceWebSocketSession:
    return _VoiceWebSocketSession(
        websocket=_WebSocket(),
        service=VoiceService(config_path=str(tmp_path / "missing.yaml")),
        repo=_Repo(),
        shuxin_home=tmp_path,
        default_device_id="soft-test",
        out_dir=tmp_path / "outputs",
    )


def test_shutdown_flushes_deferred_voice_memory_once(tmp_path: Path) -> None:
    session = _session(tmp_path)
    flush_calls: list[bool] = []
    shutdown_calls = 0

    class _Memory:
        def flush_deferred_mem0(self, *, force: bool = False) -> int:
            flush_calls.append(force)
            return 2

    class _Agent:
        memory = _Memory()

        def shutdown(self) -> None:
            nonlocal shutdown_calls
            shutdown_calls += 1

    async def _close_stt() -> None:
        return None

    session.agent = _Agent()
    session.stt_pipeline = SimpleNamespace(close=_close_stt)

    async def run() -> None:
        await session.shutdown(mark_offline=False)
        await session.shutdown(mark_offline=False)

    asyncio.run(run())
    assert flush_calls == [True]
    assert shutdown_calls == 1


def test_checkpoint_flushes_after_threshold_without_blocking_turn(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    flush_calls: list[bool] = []

    class _Memory:
        deferred_mem0_turn_count = 5
        mem0_checkpoint_turns = 5

        def flush_deferred_mem0(self, *, force: bool = False) -> int:
            flush_calls.append(force)
            return 5

    session.agent = SimpleNamespace(memory=_Memory())

    async def run() -> None:
        session._schedule_memory_checkpoint()
        session._schedule_memory_checkpoint()
        await asyncio.gather(*list(session._memory_flush_tasks))

    asyncio.run(run())
    assert flush_calls == [False]
