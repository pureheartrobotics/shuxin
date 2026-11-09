"""通话计费预留接口（首版不实现扣费）。"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class CallBillingRecorder(Protocol):
    def on_call_connected(self, call_id: str, device_id: str) -> None: ...

    def on_call_ended(self, call_id: str, duration_sec: float) -> None: ...


class NoopCallBillingRecorder:
    """默认空实现，仅记录日志。"""

    def on_call_connected(self, call_id: str, device_id: str) -> None:
        logger.info("call billing stub: connected call_id=%s device_id=%s", call_id, device_id)

    def on_call_ended(self, call_id: str, duration_sec: float) -> None:
        logger.info(
            "call billing stub: ended call_id=%s duration_sec=%.1f",
            call_id,
            duration_sec,
        )
