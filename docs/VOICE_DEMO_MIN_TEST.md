# 语音 Demo 最小可测试单元

本文档用于在没有硬件设备的情况下，独立验证当前语音 demo 是否可用。测试目标是确认：

- CLI 入口可用。
- Docker 配置可解析。
- TTS 可以把文字合成为音频文件。
- 在准备 FunASR 模型和样本音频后，STT 可以把语音识别为文字。
- 在准备 LLM 配置后，可以跑通 `语音 -> 文本 -> Agent 回复 -> 回复语音`。
- 打包和导入脚本可用于迁移 demo 环境。

当前 demo 不测试真实硬件、WebSocket 实时音频流、设备管理后台和生产级并发。

语音闭环和硬件接口设计见：[舒心语音闭环与硬件接口架构](VOICE_ARCHITECTURE.md)。

## 0. 进入项目目录

```bash
cd /home/peter/huada/project/Interesting/codex_agent/shuxin
```

## 1. 初始化本地配置

首次测试前复制示例配置：

```bash
cp .env.example .env
cp data/devices.yaml.example data/devices.yaml
```

如果只测试 `--help`、Docker 配置和 TTS，可以先不填写 LLM 配置。

如果要测试完整 `chat-audio` 或 `session`，需要编辑 `.env`：

```bash
DEMO_LLM_PROVIDER=openai-compatible
DEMO_LLM_MODEL=你的模型名
DEMO_LLM_BASE_URL=你的base_url
DEMO_LLM_API_KEY=你的api_key
```

## 2. 最小 CLI 入口测试

这个测试不依赖 FunASR 模型，也不依赖 EdgeTTS 网络请求：

```bash
PYTHONPATH=src python3 -m shuxin.voice.cli --help
```

验收标准：

- 能看到 `stt`、`tts`、`chat-audio`、`session` 四个子命令。
- 没有 `ImportError`。

## 3. 静态检查

```bash
python3 -m py_compile \
  src/shuxin/voice/__init__.py \
  src/shuxin/voice/config.py \
  src/shuxin/voice/providers.py \
  src/shuxin/voice/service.py \
  src/shuxin/voice/session.py \
  src/shuxin/voice/transport.py \
  src/shuxin/voice/cli.py

bash -n scripts/export_pack.sh
bash -n scripts/import_deploy.sh
docker compose config
```

验收标准：

- 所有命令正常结束。
- `docker compose config` 能输出 compose 配置。

## 4. Docker 构建测试

```bash
docker compose build
```

构建完成后，在容器内测试 CLI：

```bash
docker compose run --rm shuxin-voice-demo \
  python -m shuxin.voice.cli --help
```

验收标准：

- 镜像构建成功。
- 容器里能看到 CLI help。

如果构建失败，优先检查网络、pip 镜像源和 `requirements-voice-demo.txt` 里的依赖下载。

## 5. TTS 最小测试

TTS 使用 EdgeTTS，先测它，因为它不需要 FunASR 模型。

Docker 方式：

```bash
docker compose run --rm shuxin-voice-demo \
  python -m shuxin.voice.cli tts "你好，我是舒心001号 华人牌" \
  --out outputs/hello.mp3
```

本机方式：

```bash
PYTHONPATH=src python3 -m shuxin.voice.cli tts "你好，我是舒心001号 华人牌" --out outputs/hello.mp3
```

验收标准：

- 生成 `outputs/hello.mp3`。
- 音频文件可以播放。

常见失败原因：

- `edge-tts is not installed`：本机没有安装语音 demo 依赖，改用 Docker 或安装 `requirements-voice-demo.txt`。
- 网络错误：EdgeTTS 需要访问外部服务，检查服务器网络。

## 6. STT 最小测试

STT 使用本地 FunASR。测试前需要准备：

- 模型目录：`models/SenseVoiceSmall`
- 测试音频：`samples/demo.wav`

Docker 方式：

```bash
docker compose run --rm shuxin-voice-demo \
  python -m shuxin.voice.cli stt samples/demo.wav \
  --device-id demo-device-001
```

本机方式：

```bash
PYTHONPATH=src python3 -m shuxin.voice.cli stt samples/demo.wav --device-id demo-device-001
```

验收标准：

- 终端输出非空识别文本。

常见失败原因：

- `FunASR model directory not found`：`models/SenseVoiceSmall` 没有放好。
- `FunASR is not installed`：本机没有安装语音 demo 依赖，改用 Docker 或安装 `requirements-voice-demo.txt`。
- 识别结果为空：检查音频是否有人声、格式是否被 FunASR 支持。

## 7. 完整 chat-audio 测试

只有在 TTS、STT、LLM 配置都通过后，再测试完整链路：

```bash
docker compose run --rm shuxin-voice-demo \
  python -m shuxin.voice.cli chat-audio samples/demo.wav \
  --device-id demo-device-001 \
  --out outputs/reply.mp3


  **docker exec -it shuxin-voice-demo \
  python -m shuxin.voice.cli chat-audio samples/demo.wav \
  --device-id demo-device-001 \
  --out outputs/reply.mp3**
```

验收标准：

- 输出 `USER_TEXT=...`
- 输出 `AGENT_REPLY=...`
- 输出 `VOICE_OUTPUT=outputs/reply.mp3`
- `outputs/reply.mp3` 可以播放。

排查顺序：

- `USER_TEXT` 为空：先回到 STT 测试。
- `AGENT_REPLY` 报错：检查 `.env` 和 `data/devices.yaml` 的 LLM 配置。
- 回复音频没生成：先回到 TTS 测试。

## 8. 无硬件会话闭环测试

这个测试模拟真实机器人流程：初始化欢迎语、用户语音输入、STT、Agent 回复、TTS 输出和 transcript 记录。

如果容器已经通过 `scripts/redeploy_docker.sh` 常驻启动，推荐使用：

```bash
docker exec -it shuxin-voice-demo \
  python -m shuxin.voice.cli session \
  --device-id demo-device-001 \
  --out-dir outputs/session
```

如果只想临时启动一次容器，也可以使用：

```bash
docker compose run --rm shuxin-voice-demo \
  python -m shuxin.voice.cli session \
  --device-id demo-device-001 \
  --out-dir outputs/session
```

启动后输入：

```text
samples/demo.wav
exit
```

验收标准：

- 生成 `outputs/session/init.mp3`。
- 终端输出 `USER_TEXT=...`。
- 终端输出 `AGENT_REPLY=...`。
- 生成 `outputs/session/reply-001.mp3`。
- 生成 `outputs/session/transcript.txt`。

排查顺序：

- `init.mp3` 没生成：先回到 TTS 测试。
- `USER_TEXT` 为空或报错：先回到 STT 测试。
- `AGENT_REPLY` 报错：检查 `.env` 和 `data/devices.yaml` 的 LLM 配置。
- `reply-001.mp3` 没生成：先回到 TTS 测试。

## 9. 打包测试

```bash
bash scripts/export_pack.sh /tmp/shuxin_voice_export_test
```

验收标准：

- 生成类似文件：

```bash
/tmp/shuxin_voice_export_test/shuxin_voice_bundle_YYYYMMDD_HHMMSS.tar.gz
```

- 如果 `models/` 没有模型文件，会出现 warning，但不应该导致打包失败。

## 10. 导入部署测试

建议先导入到临时目录：

```bash
INSTALL_DIR=/tmp/shuxin-voice-demo-import \
bash scripts/import_deploy.sh /tmp/shuxin_voice_export_test/shuxin_voice_bundle_YYYYMMDD_HHMMSS.tar.gz
```

验收标准：

- bundle 解包成功。
- 自动创建 `.env` 和 `data/devices.yaml`。
- `docker compose build` 成功。
- 最后的容器 CLI smoke test 成功。

## 11. Docker 日常重部署

代码发生变化后，可以使用：

```bash
bash scripts/redeploy_docker.sh
```

这个命令默认是日常重启，不会重新安装 `torch`、`funasr`、`modelscope` 等大包。只有以下情况会触发 Docker build：

- 本地没有 `shuxin-voice-demo:latest` 镜像。
- `requirements-voice-demo.txt`、`requirements-voice-extra.txt` 或 `pyproject.toml` 的依赖 hash 变化。
- 显式执行 `bash scripts/redeploy_docker.sh --build`。

如果只想强制跳过 build，可以使用：

```bash
bash scripts/redeploy_docker.sh --no-build
```

验收标准：

- Docker Desktop 中 `shuxin-voice-demo` 显示 Running。
- 普通代码变更后，终端输出 `Code-only redeploy: skipping dependency build`。
- `models/`、`samples/`、`outputs/` 等挂载数据不会因为重部署丢失。

## 12. 最终通过标准

最小可测试单元通过标准：

- `PYTHONPATH=src python3 -m shuxin.voice.cli --help` 可用。
- `docker compose config` 可用。
- Docker 内 `python -m shuxin.voice.cli --help` 可用。
- `tts` 可以生成音频文件。
- 有模型和样本音频时，`stt` 可以输出文字。
- 有 LLM 配置时，`chat-audio` 可以输出识别文本、Agent 回复和回复音频。
- 有 LLM 配置时，`session` 可以输出初始化音频、回复音频和 transcript。
- `export_pack.sh` 可以打包。
- `import_deploy.sh` 可以在新目录恢复并跑通容器 smoke test。
