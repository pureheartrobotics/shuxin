# 语音 / TTS Docker 工作流

舒心语音相关开发与试听**默认只在 Docker 容器内执行**，不在宿主机 `pip install`。

## 原则

1. **仅 Docker**：构建、重部署、生成试听候选、跑 voice 服务，均通过 `bash scripts/redeploy_docker.sh` 或 `docker exec shuxin-voice-demo-pg ...`。
2. **新依赖须先批准**：新增或升级 Python 包（改 `requirements-voice-heavy.txt` / `requirements-voice-app.txt`）或 apt 包（改 `Dockerfile`）前，须说明用途与所在层，**征得维护者同意后再改**。
3. **两层 pip + 一个镜像**：全部依赖预装在 `shuxin-voice-demo:latest`；compose 里不同服务可共用同一镜像、不同 `command`。

## 依赖层（Docker tier）

| 层 ID | 文件 | 内容 | rebuild 量级 |
|-------|------|------|----------------|
| voice-heavy | `requirements-voice-heavy.txt` | numpy、pydub、soundfile、torch、funasr、modelscope | **重**（极少改） |
| voice-app | `requirements-voice-app.txt` | mem0、librosa、edge-tts、Agent 核心、FastAPI、websockets、Opus、设备绑定等 | 轻–中（日常改） |

Dockerfile 安装顺序：**heavy** → **app** → 应用代码。

`requirements-voice-stack.txt` = `-r heavy` + `-r app`，供本机一次性安装或文档引用。

`scripts/redeploy_docker.sh` 按上述两个文件 hash 决定是否 `docker compose build`；日志例如 `依赖 tier 变更: app(voice-app)`。改 app 层 **不会** 重下 torch。

### 新包写入哪一层？

| 能力 | 写入文件 | app 内 § 注释 |
|------|----------|----------------|
| TTS / Edge 音色 | `requirements-voice-app.txt` | voice-tts |
| ASR / 模型推理 | `requirements-voice-heavy.txt` | voice-asr |
| 音频读写 / pydub | `requirements-voice-heavy.txt` | voice-audio |
| FastAPI / Postgres | `requirements-voice-app.txt` | voice-server |
| 微信 / 腾讯 / WS / Opus 硬件联调 | `requirements-voice-app.txt` | voice-cloud |
| Mem0 / Qdrant 客户端 | `requirements-voice-app.txt` | voice-memory |
| Karen DSP / librosa | `requirements-voice-app.txt` | voice-fx |

本机一次性安装全部语音依赖：`pip install -r requirements-voice-stack.txt`。

## 常用命令

WSL / Docker Desktop 启动前，确认 daemon 已连接（`docker info | head -5` 只有 Client 段，不能说明已连上）：

```bash
docker info 2>&1 | grep -E "Server Version|Cannot connect"
```

```bash
# 日常重部署
bash scripts/redeploy_docker.sh

# 依赖层变更后
bash scripts/redeploy_docker.sh --build

curl -s http://localhost:8765/health

# 火山复刻 TTS 试听（.env 填 VOLCENGINE_TTS_* 后须 redeploy 才进容器）
bash scripts/redeploy_docker.sh
docker exec shuxin-voice-demo-pg sh -c 'test -n "$VOLCENGINE_TTS_VOICE_TYPE" && echo voice_type=ok'
docker exec shuxin-voice-demo-pg env PYTHONPATH=/app/src \
  python -m shuxin.voice.cli tts "你好，我是舒心。" --out outputs/volc-demo.mp3

# 临时绕过（未 redeploy 时）：exec 显式传入 env
# docker exec shuxin-voice-demo-pg env VOLCENGINE_TTS_API_KEY=... VOLCENGINE_TTS_VOICE_TYPE=... \
#   PYTHONPATH=/app/src python -m shuxin.voice.cli tts "你好" --out outputs/volc-demo.mp3

# Karen DSP v2 候选 16–19（Edge 试听脚本，非生产 TTS）
docker exec shuxin-voice-demo-pg env PYTHONPATH=/app/src \
  python /app/scripts/generate_voiceover_candidates.py --refine-only
```

输出：`outputs/voiceover-candidates/`。

## Karen DSP v2 候选（16–19）

| 文件 | 标签 |
|------|------|
| `16_karen_v2_mild.mp3` | R_v2_mild |
| `17_karen_v2_med.mp3` | S_v2_med |
| `18_karen_v2_bright.mp3` | T_v2_bright |
| `19_karen_v2_10like.mp3` | U_v2_10like |

试听：对比 `10`/`15` → `17` → `16` → `18` → `19`。实现：[`karen_dsp.py`](../src/shuxin/voice/karen_dsp.py)。

## 已批准依赖

| 包 | 版本 | 文件 | 用途 |
|----|------|------|------|
| librosa | 0.10.2 | `requirements-voice-app.txt` | Karen DSP 音调平坦化 |
| opuslib_next | 1.1.5 | `requirements-voice-app.txt` | 硬件 WebSocket Opus |

## 相关文档

- [`VOICE_DEMO_MIN_TEST.md`](VOICE_DEMO_MIN_TEST.md)
- [`VOICE_ARCHITECTURE.md`](VOICE_ARCHITECTURE.md)
- [`DEPLOY_SERVER.md`](DEPLOY_SERVER.md)
