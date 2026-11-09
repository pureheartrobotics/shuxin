from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, AsyncGenerator

if TYPE_CHECKING:
    from shuxin.voice.api.ws_session import _VoiceWebSocketSession

logger = logging.getLogger("shuxin.voice.api.ws_llm")


class LlmStreamProcessor:
    """包装大模型（LLM）对话流输出的进程与管道管理。"""

    def __init__(self, session: _VoiceWebSocketSession) -> None:
        self.session = session

    async def stream_agent_chunks(self, text: str) -> AsyncGenerator[str, None]:
        """无阻塞地在后台线程中运行 Agent 同步流式生成器，并通过 asyncio.Queue 消费。"""
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        done = object()

        def worker() -> None:
            try:
                for chunk in self.session.agent.chat_stream(text):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, done)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            item = await queue.get()
            if item is done:
                break
            if isinstance(item, Exception):
                raise item
            yield str(item)
