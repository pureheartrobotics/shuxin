# 舒心语音闭环与硬件接口架构

本文档说明当前语音 demo 的边界：我们参考小智项目的成熟服务端形态，但不复制它的产品核心。舒心自己的核心仍然是 Agent 主循环、人格、记忆、插件和陪伴编排。

## 1. 架构边界

可以参考小智的部分：

- WebSocket 硬件连接模型。
- `hello / listen / abort / ping` 这类设备控制消息。
- 设备上行二进制音频帧。
- 服务端下发 STT/TTS 状态消息。
- TTS 音频帧按节奏下发。
- `device_id / client_id / per-device config` 的设备配置思路。

舒心自己保留的部分：

- `Agent` 主循环。
- `SOUL.md` 和 personality。
- memory/plugin/companion 编排。
- 每轮对话的语义处理。
- 未来多产品、多角色、多设备的配置策略。

暂时不复制的部分：

- 完整连接管理。
- VAD。
- MQTT。
- OTA。
- manager-api。
- 生产级并发和流式 Opus 帧调度。

## 2. 当前无硬件闭环

当前实现先保证没有硬件也能跑通完整链路：

```text
机器人初始化
  -> welcome_text
  -> TTS
  -> outputs/session/init.mp3
  -> 输入用户音频文件路径
  -> STT
  -> 用户文字
  -> ShuXin Agent
  -> 回复文字
  -> TTS
  -> outputs/session/reply-001.mp3
  -> transcript.txt
```

运行入口：

```bash
python -m shuxin.voice.cli session \
  --device-id demo-device-001 \
  --out-dir outputs/session
```

会话启动后会先生成：

- `outputs/session/init.mp3`
- `outputs/session/transcript.txt`

每轮输入一个音频文件路径，例如：

```text
samples/demo.wav
exit
```

每轮会生成：

- `outputs/session/reply-001.mp3`
- `outputs/session/reply-002.mp3`
- `outputs/session/transcript.txt`

## 3. 当前代码分层

语音 demo 的代码在 `src/shuxin/voice/` 下：

- `config.py`：设备级配置，后续可以替换成远程设备配置服务。
- `providers.py`：STT/TTS provider 抽象与实现。
- `service.py`：语音服务门面，保留原有 `stt / tts / chat-audio` 单点能力。
- `transport.py`：硬件输入输出抽象，目前用文件模拟麦克风和扬声器。
- `session.py`：无硬件语音闭环，会话内复用同一个 Agent。
- `cli.py`：命令行入口。

当前默认 provider：

- STT：本地 FunASR `models/SenseVoiceSmall`。
- TTS：EdgeTTS。

同时保留 API provider 的接口位置，后续可以把 `ProviderConfig.type` 切到 `api` 后实现远程服务调用。

## 4. Transport 预留接口

当前接口：

```text
AudioInputTransport
  read_user_audio_path() -> Path | None

AudioOutputTransport
  publish_audio(audio_path: Path) -> None

DeviceSession
  device_id
  client_id
  turn_index
  metadata
```

当前无硬件替代：

- `TerminalFileInputTransport`：用户在终端输入 `samples/*.wav`，模拟麦克风输入。
- `FileAudioOutputTransport`：把 TTS 结果写到 `outputs/session/*.mp3`，模拟扬声器输出。

未来接硬件时，优先替换 transport：

- 文件输入替换成 WebSocket 上行音频帧。
- 文件输出替换成 WebSocket/Opus 音频帧下发。
- `DeviceSession` 继续保存 `device_id`、`client_id`、会话状态和 Agent 配置。

不要为了接硬件重写舒心 Agent/STT/TTS 主链路。

## 5. 未来硬件协议形态

未来 WebSocket 硬件接口可以参考小智的消息形态。

设备上行文本消息：

```json
{"type":"hello","device_id":"demo-device-001","client_id":"client-001"}
```

```json
{"type":"listen","state":"start"}
```

```json
{"type":"listen","state":"stop"}
```

```json
{"type":"abort"}
```

```json
{"type":"ping"}
```

设备上行二进制消息：

```text
audio frame bytes
```

服务端下行文本消息：

```json
{"type":"stt","text":"你好，舒心"}
```

```json
{"type":"tts","state":"start"}
```

```json
{"type":"tts","state":"sentence_start","text":"你好，我在。"}
```

```json
{"type":"tts","state":"stop"}
```

服务端下行二进制消息：

```text
tts audio frame bytes
```

## 6. 多设备配置方向

当前 `data/devices.yaml` 已经按设备 ID 保存配置：

- 每个设备可以有自己的 LLM provider/model/base_url/api_key。
- 每个设备可以有自己的 STT provider/model_dir/api_url/api_key。
- 每个设备可以有自己的 TTS provider/voice/api_url/api_key。

这满足 demo 阶段需求。未来如果产品量变多，可以把本地 YAML 换成数据库或远程配置服务，但调用方仍然只按 `device_id` 获取配置。

## 7. 成功标准

当前阶段成功标准：

- `stt samples/demo.wav` 可用。
- `tts "你好"` 可用。
- `chat-audio samples/demo.wav` 可用。
- `session` 可以生成 `init.mp3`、`reply-001.mp3` 和 `transcript.txt`。
- Docker 常驻容器可以通过 `scripts/redeploy_docker.sh` 重启。

后续硬件阶段成功标准：

- 只新增 WebSocket transport。
- 复用现有 `VoiceSessionRunner` 或其会话编排思想。
- 不替换舒心 Agent 核心。
