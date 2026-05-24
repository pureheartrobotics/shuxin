# 语音硬件 WebSocket 接口协议

本文档面向后续硬件接入方。当前协议用于无硬件 Web 测试台，也作为后续真实硬件的最小接入边界。

## 1. 服务地址

默认地址：

```text
ws://<host>:8765/ws/voice
```

本机测试：

```text
ws://localhost:8765/ws/voice
```

浏览器测试页：

```text
http://localhost:8765/voice-demo
```

## 2. 音频格式

上行音频帧格式：

```text
sample_rate: 16000 Hz
channels: 1
sample_format: PCM16
byte_order: little-endian
container: none
```

硬件不要发送 wav/mp3/opus 文件。`listen start` 后直接发送 PCM16 二进制帧，`listen stop` 表示一句话结束。

## 3. 设备上行文本消息

连接建立后先发送 `hello`：

```json
{"type":"hello","device_id":"demo-device-001","client_id":"device-001"}
```

开始录音：

```json
{"type":"listen","state":"start"}
```

结束录音：

```json
{"type":"listen","state":"stop"}
```

取消当前轮：

```json
{"type":"abort"}
```

心跳：

```json
{"type":"ping"}
```

## 4. 设备上行二进制消息

在 `listen start` 和 `listen stop` 之间发送音频二进制帧：

```text
<pcm16 audio frame bytes>
```

建议每帧 20ms 到 100ms。当前 demo 会把一轮音频暂存在内存中，收到 `listen stop` 后再进入 STT。

## 5. 服务端下行文本消息

服务端连接就绪：

```json
{"type":"hello","state":"ready","device_id":"demo-device-001"}
```

设备 hello 确认：

```json
{"type":"hello","state":"ok","device_id":"demo-device-001","client_id":"device-001"}
```

开始识别：

```json
{"type":"stt","state":"start"}
```

最终识别文本：

```json
{"type":"stt","state":"final","text":"你好，舒心","elapsed_ms":1234}
```

Agent 回复文本：

```json
{"type":"agent","state":"reply","text":"你好，我在。","elapsed_ms":1500}
```

开始语音合成：

```json
{"type":"tts","state":"start"}
```

结束语音合成：

```json
{"type":"tts","state":"stop","elapsed_ms":800,"total_elapsed_ms":3600}
```

错误：

```json
{"type":"error","message":"no audio received"}
```

心跳响应：

```json
{"type":"pong","ts":1710000000.0}
```

## 6. 服务端下行二进制消息

当前 demo 在 `tts start` 后发送完整 mp3 二进制：

```text
<mp3 audio bytes>
```

硬件第一版可以把该 mp3 缓存完整后播放。后续如需低延迟播放，再扩展为分句 TTS 或流式 TTS。

## 7. 当前边界

当前 demo 暂不支持：

- 自动 VAD。
- Opus 音频上行。
- 流式 TTS。
- 中途打断播放。
- MQTT。
- OTA。
- manager-api。

当前目标是先跑通准实时 turn-based 对话：用户说完一句，硬件发送 `listen stop`，服务端返回识别文本、Agent 回复和回复音频。
