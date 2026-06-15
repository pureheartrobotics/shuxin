"""Voice demo support for ChuXin.

This package intentionally lives outside the core Agent loop. It adapts audio
inputs and outputs to the existing text-first Agent API.
"""

from shuxin.voice.config import DeviceConfig, DeviceConfigProvider, VoiceConfig
from shuxin.voice.service import VoiceService
from shuxin.voice.session import VoiceSessionRunner
from shuxin.voice.transport import DeviceSession

__all__ = [
    "DeviceConfig",
    "DeviceConfigProvider",
    "DeviceSession",
    "VoiceConfig",
    "VoiceSessionRunner",
    "VoiceService",
]
