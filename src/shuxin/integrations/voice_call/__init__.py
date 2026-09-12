"""设备通话切面 — 信令、拨号意图、计费 stub。"""

from shuxin.integrations.voice_call.billing import CallBillingRecorder, NoopCallBillingRecorder

__all__ = ["CallBillingRecorder", "NoopCallBillingRecorder"]
