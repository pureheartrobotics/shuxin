"""RK3566 设备运行时配置。密钥只用于设备 hello，不写云厂商 Key。"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceRuntimeConfig:
    ws_url: str
    device_code: str
    device_secret: str
    client_id: str
    ping_interval_seconds: float = 20.0
    recv_timeout_seconds: float = 120.0
    uplink_sample_rate: int = 16000
    downlink_sample_rate: int = 24000
    frame_duration_ms: int = 60
    channels: int = 1

    @classmethod
    def from_env(
        cls,
        *,
        ws_url: str | None = None,
        device_code: str | None = None,
        device_secret: str | None = None,
        client_id: str | None = None,
    ) -> DeviceRuntimeConfig:
        return cls(
            ws_url=(ws_url or os.environ.get("SHUXIN_VOICE_WS_URL") or "ws://127.0.0.1:8765/ws/voice").strip(),
            device_code=(device_code or os.environ.get("SHUXIN_DEVICE_CODE") or "demo-device-001").strip(),
            device_secret=(
                device_secret
                or os.environ.get("SHUXIN_DEVICE_SECRET")
                or os.environ.get("SHUXIN_DEVICE_SHARED_SECRET")
                or ""
            ).strip(),
            client_id=(client_id or os.environ.get("SHUXIN_DEVICE_CLIENT_ID") or "rk3566-device").strip(),
        )
