"""RK3566 设备端客户端（本分支新增）。

master / ESP32 固件路径保持不变。本包在板端对接现有云端
`ws://<host>:8765/ws/voice` 协议：设备不持有 LLM/ASR/TTS 厂商密钥。
"""

__version__ = "0.1.0"
