# 语音 Demo 最小可测试单元

本文档用于在没有硬件设备的情况下，独立验证当前语音 demo 是否可用。测试目标是确认：

- CLI 入口可用。
- Docker 配置可解析。
- TTS 可以把文字合成为音频文件。
- 在准备 FunASR 模型和样本音频后，STT 可以把语音识别为文字。
- 在准备 LLM 配置后，可以跑通 `语音 -> 文本 -> Agent 回复 -> 回复语音`。
- 在准备 Web 依赖和准实时模型后，可以用浏览器麦克风测试 WebSocket 语音对话。
- 在 Docker Postgres 模式下，可以测试后台设备绑定、小程序绑定接口和硬件身份鉴权。
- 打包和导入脚本可用于完整迁移 demo 环境（含 Postgres/Qdrant；不含 `.env` 与镜像）。

当前 demo 不测试真实量产硬件、WebSocket 流式打断、OTA、MQTT 和生产级并发。

语音闭环和硬件接口设计见：[舒心语音闭环与硬件接口架构](VOICE_ARCHITECTURE.md)。

硬件接入总览（三码、鉴权、STT/TTS 不由固件直连）：[硬件 STT/TTS 调用与鉴权接入指南](VOICE_HARDWARE_INTEGRATION.md)。

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
  src/shuxin/voice/cli.py \
  src/shuxin/voice/server.py

bash -n scripts/export_pack.sh
bash -n scripts/import_deploy.sh
bash -n scripts/download_voice_models.sh
docker compose config
```

验收标准：

- 所有命令正常结束。
- `docker compose config` 能输出 compose 配置。

Docker 内命令、依赖分层与新包批准流程见 [`VOICE_DOCKER_WORKFLOW.md`](VOICE_DOCKER_WORKFLOW.md)。

## 4. Docker 构建测试

```bash
docker compose build
```

构建完成后，在容器内测试 CLI：

```bash
docker compose run --rm shuxin-voice-demo \
  python -m shuxin.voice.cli --help
```

如果使用常驻服务，启动或重启：

```bash
bash scripts/redeploy_docker.sh
```

Qdrant 宿主机端口：本地默认 **6335**（`.env` 中 `QDRANT_HTTP_PORT`，避免与本机 6333 冲突）。生产部署见 [`DEPLOY_SERVER.md`](DEPLOY_SERVER.md)。

若 `redeploy` 报 `shuxin-qdrant is unhealthy`，且 `docker inspect shuxin-qdrant` 健康日志含 `wget: not found`：更新 `docker-compose.yml` 后执行 `docker compose -p shuxin up -d qdrant` 重建容器，再重跑 redeploy。

默认 Web 测试台端口：

```text
http://localhost:8765/voice-demo
```

验收标准：

- 镜像构建成功。
- 容器里能看到 CLI help。
- 常驻容器启动后，浏览器能打开 Web 测试台页面。

如果构建失败，优先检查网络、pip 镜像源和 `requirements-voice-heavy.txt` / `requirements-voice-app.txt` 里的依赖下载。

## 5. TTS 最小测试

生产 TTS 使用**火山语音复刻**（`volcengine-clone`）。需在 `.env` 配置 `VOLCENGINE_TTS_API_KEY` 与 `VOLCENGINE_TTS_VOICE_TYPE`，修改后执行 `bash scripts/redeploy_docker.sh`。

Docker 方式：

```bash
docker exec shuxin-voice-demo-pg env PYTHONPATH=/app/src \
  python -m shuxin.voice.cli tts "你好，我是舒心" -o /tmp/volc-demo.mp3
docker cp shuxin-voice-demo-pg:/tmp/volc-demo.mp3 ./outputs/volc-demo.mp3
```

本机方式（需已 export 火山 env）：

```bash
PYTHONPATH=src python3 -m shuxin.voice.cli tts "你好，我是舒心" --out outputs/volc-demo.mp3
```

验收标准：

- 生成 `outputs/volc-demo.mp3`（或上述路径）。
- 音频文件可以播放，音色为火山复刻。

常见失败原因：

- `voice_type` / `api_key` ValueError：容器未透传 `.env` → 运行 `bash scripts/redeploy_docker.sh`。
- 网络/API 错误：检查火山密钥与 `VOLCENGINE_TTS_API_URL`。
- EdgeTTS 相关错误：说明设备 `tts_config.type` 仍为 `local` → 后台「全部应用火山 TTS」或迁移 `004_devices_tts_volcengine_default.sql`。

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
- `FunASR is not installed`：本机没有安装语音 demo 依赖，改用 Docker 或安装 `requirements-voice-stack.txt`。
- 识别结果为空：检查音频是否有人声、格式是否被 FunASR 支持。

## 7. 完整 chat-audio 测试

只有在 TTS、STT、LLM 配置都通过后，再测试完整链路：

```bash
docker compose run --rm shuxin-voice-demo \
  python -m shuxin.voice.cli chat-audio samples/demo.wav \
  --device-id demo-device-001 \
  --out outputs/reply.mp3
```

如果容器已经常驻启动，推荐使用：

```bash
docker exec -it shuxin-voice-demo-pg \
  python -m shuxin.voice.cli chat-audio samples/demo.wav \
  --device-id demo-device-001 \
  --out outputs/reply.mp3
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
docker exec -it shuxin-voice-demo-pg \
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

## 9. WebSocket 准实时语音测试台

这个测试用浏览器模拟未来硬件：浏览器麦克风采集 16k mono PCM16，通过 WebSocket 发给服务端，服务端完成 STT、Agent 回复和 TTS 播放。

首次测试 streaming STT 前，下载模型到挂载目录：

```bash
docker exec -it shuxin-voice-demo-pg \
  bash scripts/download_voice_models.sh streaming-stt
```

如果希望先下载原有 SenseVoice 模型：

```bash
docker exec -it shuxin-voice-demo-pg \
  bash scripts/download_voice_models.sh sensevoice
```

启动或重启常驻服务：

```bash
bash scripts/redeploy_docker.sh
```

打开浏览器：

```text
http://localhost:8765/voice-demo
```

页面默认按真实硬件模式连接。多用户测试：

```text
1. 打开 http://localhost:8765/admin ，确认各用户已绑定设备。
2. 打开 http://localhost:8765/voice-demo ，填写 Admin Token（与 SHUXIN_ADMIN_TOKEN 相同）。
3. 点击「加载设备」，在下拉框选择「用户 · 设备」；会自动填入 device_code 与 device_secret。
4. 点击连接，再按住说话测试。
```

**设备密钥（Admin 可查看）**：批量制码前必须在 `.env` 配置 `SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY`（Fernet，生成命令见 `.env.example`），并 `bash scripts/redeploy_docker.sh` 重部署。未配置时 Admin 批量制码区会显示黄条且 API 直接报错，避免只写入 hash、无法查看明文。

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 写入 .env 后重部署，再在 Admin 批量制码；设备列表「查看」可复制 device_secret
```

历史假数据（制码时未配密钥）无法从 hash 恢复明文，需重新批量制码或 `POST /admin/api/devices/{device_id}/rotate-secret` 后重烧固件。

单设备手填示例（`demo-device-001` 已绑定 `demo-user`）：

```text
device_code: demo-device-001
device_secret: dev-device-secret
client_id: web-demo-test
```

测试步骤：

```text
1. 点击连接。
2. 按住“按住说话”。
3. 说一句中文。
4. 松手。
5. 等待页面显示 STT 文本、Agent 回复，并自动播放 TTS 音频。
```

如果要测试 streaming 配置，把页面里的 device id 改为：

```text
demo-device-streaming-001
```

验收标准：

- 页面连接状态显示已连接。
- 松手后页面显示识别文本。
- 页面显示舒心回复文本。
- 浏览器播放回复 mp3。
- 页面日志能看到 STT、Agent、TTS 状态消息和耗时。

当前边界：

- 第一版是准实时 turn-based，不是自动 VAD。
- 松手后才进入 final STT。
- TTS 第一版是整段 mp3 返回，不是流式 TTS。

## 9.1 后台绑定和硬件鉴权测试

前置概念与固件调用链见 [VOICE_HARDWARE_INTEGRATION.md](VOICE_HARDWARE_INTEGRATION.md)。

启动本地 Postgres 与 voice 服务：

```bash
docker compose up -d postgres shuxin-voice-demo
curl -s http://localhost:8765/health
```

打开后台：

```text
http://localhost:8765/admin
```

本地默认 token：

```text
dev-admin-token
```

用后台页面或 API 建立绑定：

```bash
curl -s -H 'X-Admin-Token: dev-admin-token' \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"demo-user","device_id":"demo-device-001"}' \
  http://localhost:8765/admin/api/bindings
```

查看绑定列表：

```bash
curl -s -H 'X-Admin-Token: dev-admin-token' \
  http://localhost:8765/admin/api/bindings
```

### 设备 STT（腾讯实时识别）

批量出厂设备（`SX-*` 等）入库时会写入 `stt_config.type = tencent-realtime`。服务启动时会执行迁移 `003_devices_stt_tencent_default.sql`，将**全部未删除设备**的 STT 设为腾讯实时识别；也可在后台「设备」Tab 点击 **全部应用腾讯 STT** 手动再执行一次。

容器需配置（见 `docker-compose.yml` / `.env`）：

- `TENCENT_ASR_APPID`
- `TENCENTCLOUD_SECRET_ID`
- `TENCENTCLOUD_SECRET_KEY`

验收 STT 类型：

```bash
docker exec shuxin-postgres psql -U shuxin -d shuxin -c \
  "SELECT device_id, stt_config->>'type' AS stt FROM devices WHERE deleted_at IS NULL LIMIT 5;"
```

或通过 API：

```bash
curl -s -X POST -H 'X-Admin-Token: dev-admin-token' \
  http://localhost:8765/admin/api/devices/apply-stt-defaults
```

若 voice-demo 日志里 `stt/final` 的 `elapsed_ms` 达到上万毫秒，多半是仍在用本地 FunASR（`stt` 为空或 `local`）；应显示为 `tencent-realtime` 且凭证有效。

### 按用户 API 配置测试（推荐）

1. 打开 `http://localhost:8765/admin`，在「用户」Tab 找到目标用户，点击 **配置 LLM** 弹层填写 model、Base URL、API Key 并保存（API Key 留空表示不修改已有密钥）。
2. **微信小程序用户**（`user_id` 以 `wx_` 开头）由登录自动创建，默认无 LLM 配置；必须在后台为该 `wx_` 用户单独配置 LLM 后，voice-demo 对话才不会出现 `connect_error` 或降级文案。
3. 打开「设备」Tab：设备以**卡片**展示；外壳码**只读**可复制（印在壳上不可改）；备注用 **textarea** + **保存备注** / **清空**；已绑定卡片底部有 **解绑**（二次确认）。设备 Tab **无**删除、改外壳码、重置认领、换密钥按钮。
4. 打开「绑定」Tab：左右列可独立搜索、翻页；点选用户与未绑定设备后「绑定所选」。
5. 「当前绑定」表可 **解绑**（二次确认）；解绑后认领码自动恢复可扫码，用户记忆保留。
6. 打开 `http://localhost:8765/voice-demo`，填写 Admin Token →「加载设备」→ 选择条目；若「将使用 LLM」显示 key=未配置，请回后台配置后再连接。
7. 连接后「绑定用户」与 hello 一致；对话使用该用户 LLM，而非仅设备默认配置。

验收标准：

- 列表出现 `demo-user -> demo-device-001` 的 active binding（或你的 `wx_... -> SX-...` 绑定）。
- 设备卡片：外壳码只读可复制；备注可独立保存/清空（搜索框可按备注查找）。
- Admin 解绑后，小程序「我的设备」刷新后该设备消失（`POST /api/devices/my` 不再返回）；可重新扫码绑定。
- `/voice-demo` 使用对应 `device_code + device_secret` 连接后，hello 返回 `state: ok` 且 `user_id` 为绑定用户。
- 绑定用户已在后台配置 API Key 后，WebSocket 日志不应再因缺 key 出现 `agent/error` + `connect_error`（网络正常时）；若 key 错误则为 `auth_error`。

如果 WebSocket 返回 `invalid device secret`，确认容器环境变量已刷新；修改 compose 环境变量后需要重新创建服务：

```bash
docker compose up -d shuxin-voice-demo
```

## 9.2 微信小程序绑定测试

小程序源码在：

```text
apps/wechat-miniprogram
```

开发模式脚本：

```bash
export WECHAT_MINIPROGRAM_APPID="your-appid-or-touristappid"
scripts/wechat_miniprogram_dev.sh
```

脚本默认自动探测 WSL IP，并把小程序 API 编译为 `http://<WSL_IP>:8765`。如果要手动指定后端地址，再设置 `SHUXIN_API_BASE`。

生产构建：

```bash
scripts/wechat_miniprogram_build.sh
```

Windows 微信开发者工具导入：

```text
apps/wechat-miniprogram/dist/build/mp-weixin
```

日常联调推荐导入开发产物：

```text
apps/wechat-miniprogram/dist/dev/mp-weixin
```

`scripts/wechat_miniprogram_dev.sh` 会监听源码变化并持续更新 `dist/dev/mp-weixin`。如果导入的是 `dist/build/mp-weixin`，它只是执行 `scripts/wechat_miniprogram_build.sh` 时的快照；改完源码后必须重新构建，再在微信开发者工具里重新编译或刷新项目。**MBTI 绑定弹窗**（`MbtiRevealModal`）只在最新 `dist` 里；若绑定成功只有 toast、无 MBTI，先执行 `bash scripts/wechat_miniprogram_dev.sh build` 并重新导入 `dist/dev/mp-weixin`。

后台现在可以批量生成三码：外壳公开 `claim_code`、设备内部 `device_id` 和一次性 `device_secret`。本地最小验证可以调用：

```bash
curl -s -H 'X-Admin-Token: dev-admin-token' \
  -H 'Content-Type: application/json' \
  -d '{"device_prefix":"SX","device_start":1,"label_prefix":"CLM","label_batch":"A001","quantity":3}' \
  http://localhost:8765/admin/api/factory/devices/batch
```

把返回的 `claim_code` 填到小程序页面，点击绑定，再查看“我的设备”。如果要贴条形码或二维码，内容使用 `claim_code` 或返回的 `qr_payload`；`device_id + device_secret` 只用于设备烧录/设备鉴权，不要贴在外部。

验收标准：

- 小程序可以通过 `wx.login()` 获取 code。
- 小程序调用 `/api/wechat/login` 后获得舒心自定义 `session_token`，响应不包含微信 `session_key`。
- 本地 `SHUXIN_WECHAT_MOCK=1` 时，后端可以 mock openid 并用 `session_token` 完成绑定。
- 绑定后 `/api/devices/my` 使用 `session_token` 能返回该设备。
- 旧包即使把 `claim_code` 误放进 `device_code` 字段，后端也会兜底识别并完成绑定。
- 设备 WebSocket `hello` 使用正确 `device_id/device_code + device_secret` 才能通过鉴权。
- **MBTI 盲盒（§9.2.1）**：批量制码设备 `mbti_status=sealed`；绑定弹窗展示 MBTI；设备**首次**播报 `绑定成功。` + `reveal_script`（绑定瞬间若 WS 在线则即时推送，否则 hello 补播）；重连不重复开箱。
- 小程序**不提供用户解绑**；售后换绑走 Admin。后端 `/api/devices/unbind` 仍保留供管理端。

### 9.2.1 MBTI 盲盒绑定验收

1. Admin 批量制码（见上文 curl）→ 设备 `metadata.mbti_status=sealed`。
2. 小程序扫 `claim_code` 绑定 → 出现 **MbtiRevealModal**（`INFJ · 提倡者` + tagline）。
3. 关闭弹窗后设备列表行显示 MBTI 徽章。
4. 设备通电 WebSocket `hello`（已绑定且 `device_intro_played=false`）→ 听到「绑定成功。」+ 自我介绍 TTS；若绑定瞬间设备已在线，绑定 API 也会尝试即时推送同一段 TTS。再次 hello 不再播报。
5. `curl` 验证 bind 响应含 `mbti.is_first_reveal`；`sealed` 设备在 bind 前调用 `/api/devices/my` 不应看到 `mbti` 字段。

```bash
# bind 响应示例字段（Postgres 模式）
# mbti: { is_first_reveal, mbti, display_name, tagline }

PYTHONPATH=src pytest tests/test_ensure_runtime_after_mbti_prefetch.py \
  tests/test_mbti_miniprogram_bind.py tests/test_mbti_reveal.py \
  tests/test_device_intro_and_registry.py -q
```

常见失败原因：

- hello 后有 MBTI 自我介绍文字但无 `tts/start`、首轮对话报 `'NoneType' object has no attribute 'chat_stream'`：2026-06-08 前版本在 MBTI 路径预填 `device` 后未初始化 agent；升级至含 `_ensure_runtime` 修复的版本后应消失。
- 控制台提示 `wx.getSystemInfoSync is deprecated`：这是基础库兼容警告，通常不是本次绑定失败根因。
- 控制台提示关闭合法域名校验：这是开发者工具设置提示；本地 HTTP 联调时可以保留，但真机和上线必须配置 HTTPS 合法域名。
- `SystemError ... timeout`：通常是小程序请求的后端地址不可达。确认 Docker voice 服务已启动，`curl -s http://localhost:8765/health` 可用；小程序页面里也可以点“测试后端连接”。当前开发构建默认使用 `http://localhost:8765`，需要改地址时设置 `SHUXIN_API_BASE` 后重新编译。
- `scanCode:fail 解析二维码失败`：“相机扫码”只走微信原生相机扫码；上传图片请点“传图识别”，它会调用后端 `/api/barcodes/decode`。如果“传图识别”可返回 `claim_code`，说明后端和条码内容正常，原生相机扫不出时优先检查条码打印尺寸、留白、对焦和光线。

## 10. LLM 连通性自测（voice-demo 出现降级文案时）

STT 很快但 Agent 返回「模型连接有点慢…」时，说明 **LLM 调用失败**，不是模型推理慢。按顺序在本机执行（不要提交 `.env`）：

```bash
# 1) 容器能否访问 LLM API 域名（不测 API key；镜像内无 curl 时用 python）
docker exec shuxin-voice-demo-pg python -c "
import urllib.request, time
start=time.perf_counter()
try:
    r=urllib.request.urlopen('https://api.deepseek.com', timeout=10)
    print('status', r.status, 'time', round(time.perf_counter()-start, 2))
except Exception as e:
    print(type(e).__name__, round(time.perf_counter()-start, 2))
"

# 2) 环境变量是否注入容器（只看是否非空，不打印 key）
docker exec shuxin-voice-demo-pg sh -c 'test -n "$DEMO_LLM_API_KEY" && echo KEY=set || echo KEY=empty'
docker exec shuxin-voice-demo-pg sh -c 'echo MODEL=$DEMO_LLM_MODEL BASE=$DEMO_LLM_BASE_URL'

# 3) Postgres 用户配置是否含空 model/base_url（会间接退回错误模型）
docker exec shuxin-postgres psql -U shuxin -d shuxin -c \
  "SELECT user_id, llm_config FROM users WHERE user_id='demo-user';"
# 若 llm_config 为 {"model":"","base_url":""}，可清理：
docker exec shuxin-postgres psql -U shuxin -d shuxin -c \
  "UPDATE users SET llm_config='{}'::jsonb WHERE user_id='demo-user';"

# 4) 同容器最小 LLM 闭环
docker exec -it shuxin-voice-demo-pg \
  python -m shuxin.voice.cli chat-audio samples/demo.wav --device-id demo-device-001
```

WebSocket 日志里若出现 `{"type":"agent","state":"error","error_kind":"connect_timeout"}`，优先检查 Docker 出网/代理；`auth_error` 优先检查 key 和 model。

相关环境变量：

| 变量 | 默认 | 说明 |
|------|------|------|
| `SHUXIN_LLM_CONNECT_TIMEOUT_SECONDS` | 5 | 连接超时，避免 ~21s 空等 |
| `SHUXIN_LLM_TIMEOUT_SECONDS` | 60 | 读超时 |
| `SHUXIN_VOICE_MAX_HISTORY` | 8 | 语音会话历史轮数 |
| `SHUXIN_VOICE_MAX_TOKENS` | 384 | 语音回复 token 上限 |

## 11. 三层记忆与 voice-demo 验收

语音路径采用**短期原文 + 7 日滚动摘要 + 长期 facts/陪伴状态**（见 [VOICE_ARCHITECTURE.md §3.2](VOICE_ARCHITECTURE.md)）。单元测试 `tests/test_voice_memory_summary.py` 不经过 Web 测试台；本节用 **voice-demo + curl** 验收「断线重连后回复仍能关联上次主题」。

### 11.1 测试分层

| 层 | 命令/入口 | 证明什么 |
|----|-----------|----------|
| L0 单元 | `pytest tests/test_voice_memory_summary.py -q` | 字段、每 N 轮触发、JSON 同步 |
| L1 人工 | http://localhost:8765/voice-demo 固定剧本 | 重连后舒心回复关联上次主题 |
| L2 快照 | `GET /voice/export` | `rolling_summary`、`recent_topics` 客观写入 |

### 11.2 前置条件

与 §9 相同，并确认：

1. `curl -s http://localhost:8765/health` 中 `"storage":"postgres"`（Docker Compose + `DATABASE_URL`）。
2. http://localhost:8765/admin 中绑定用户（如 `demo-user`）已配置 **LLM**（model/base_url/api_key）。摘要合并与对话共用该 LLM；无 key 时 `rolling_summary` 不会更新。
3. voice-demo 填写 Admin Token（默认 `dev-admin-token`），加载设备并连接。

可选加速（少按几次麦克风即触发摘要）：

```bash
# docker-compose.yml 的 shuxin-voice-demo 环境变量
SHUXIN_SUMMARY_EVERY_N=2
```

相关变量：

| 变量 | 默认 | 说明 |
|------|------|------|
| `SHUXIN_SUMMARY_EVERY_N` | 5 | 每 N 轮异步 LLM 合并摘要 |
| `SHUXIN_SUMMARY_MODEL` | （空） | 摘要专用模型，空则用设备/用户 LLM |
| `SHUXIN_SUMMARY_MAX_TOKENS` | 256 | 摘要输出 token 上限 |

### 11.3 观测：curl 导出 shared_memory

将 `demo-user` 换成 voice-demo 连接后 hello 返回的 `user_id`：

```bash
curl -s -H "X-Admin-Token: dev-admin-token" \
  "http://localhost:8765/voice/export?user_id=demo-user" \
  | jq '.shared_memory | {turn_count, turns_since_summary, recent_topics, rolling_summary, summary_updated_at}'
```

### 11.4 固定剧本（会话 A → 断开 → 会话 B）

**会话 A**（同一 WebSocket，至少 5 轮）：连接 → 按住说话 → 中文一句 → 松手 → 等 STT、回复、TTS 完成。

建议台词（须反复出现主题词 **「面试」**）：

1. 「我下周有个很重要的面试，有点紧张。」
2. 「面试是产品经理岗位。」
3. 「我最近每晚都在准备面试。」
4. 「面试公司是一家互联网公司。」
5. 「如果面试过了我想请你帮我庆祝。」
6. （可选）「面试前我还想去剪个头发。」

**检查点 A1**（第 3 轮后）：执行 11.3 的 curl。期望 `turn_count >= 3`，`recent_topics` 非空；`rolling_summary` 可为空。

**检查点 A2**（第 5 轮后，等待 5～15 秒再 curl）：期望 `rolling_summary` 非空且语义含面试/产品经理/紧张等；`turns_since_summary` 归零或明显小于 N。

**断开**：voice-demo 点「断开」或关标签页（触发断线 `force=True` 摘要）。

**检查点 A3**（断开后 curl）：`rolling_summary` 仍存在。

**会话 B**（新连接）：重新打开 voice-demo 并连接（新 session，**不**恢复最近原文）。只说：

「我上次跟你说的那件事，后来怎么样了？」

**人工通过标准**：舒心回复中明确关联会话 A 的主题（如「面试」「产品经理」「准备」），而非像第一次见面。若完全泛化寒暄，判为失败。

更直白可再问：「我们之前说的面试怎么样了？」

### 11.5 失败分流（仍用 curl，不必查库）

| 现象 | 可能原因 |
|------|----------|
| `rolling_summary` 始终为空 | 用户 LLM 未配置；摘要失败（容器日志 `rolling summary LLM merge failed`） |
| 有 `rolling_summary` 但 B 不记得 | 核对容器内 JSON 与 export 一致：`docker exec shuxin-voice-demo-pg cat /root/.shuxin/users/demo-user/summaries/shared_memory.json` |
| A 有摘要、B 仍不记得 | 换更直白追问；确认连接的是同一 `user_id` |

容器内路径以 `SHUXIN_HOME` 为准（常见 `/root/.shuxin`）。

### 11.6 自动化 E2E（无需麦克风）

在 Docker voice 容器内一键跑固定剧本（直连 Postgres + Agent，与 voice-demo 共用用户记忆目录）：

```bash
docker exec shuxin-voice-demo-pg \
  env PYTHONPATH=/app/src \
  python /app/scripts/test_voice_memory_e2e.py
```

通过标准：脚本输出 `PASS`，且 `rolling_summary` 非空、会话 B 回复含「面试」等关键词。

可选 WebSocket 模式（走真实 `/ws/voice`，需重启服务并开启开发开关）：

```bash
# docker-compose.yml 或 .env 增加后 redeploy：
# SHUXIN_VOICE_DEV_TEXT_TURN=1
# SHUXIN_VOICE_E2E_SKIP_TTS=1

docker exec shuxin-voice-demo-pg \
  env PYTHONPATH=/app/src SHUXIN_VOICE_DEV_TEXT_TURN=1 \
  python /app/scripts/test_voice_memory_e2e.py --ws ws://127.0.0.1:8765/ws/voice
```

### 11.7 与 pytest 的关系

发版前建议：

```bash
pytest tests/test_voice_memory_summary.py tests/test_voice_users_storage.py -q
```

通过 pytest **不能代替** §11.4 人工剧本；可用 `SHUXIN_RUN_VOICE_E2E=1 pytest tests/test_voice_memory_e2e.py` 在具备 `DATABASE_URL` 的环境跑 §11.6 自动化脚本。

## 12. 打包测试

```bash
bash scripts/export_pack.sh /tmp/shuxin_voice_export_test
```

脚本会先 `docker compose up -d postgres qdrant`（若 Docker 可用），再打包：

- `code.tar.gz` — 代码（不含 `.env`、不含 `models/`）
- `data.tar.gz` — `data/`（含 `shuxin_home`、devices 等；`devices.yaml.example` 除外）
- `models.tar.gz` / `samples.tar.gz` / `outputs.tar.gz` — 有内容才打
- `postgres.dump` — Postgres 逻辑备份（`pg_dump -Fc`）
- `qdrant_storage.tar.gz` — Qdrant named volume

验收标准：

- 生成类似文件：

```bash
/tmp/shuxin_voice_export_test/shuxin_voice_bundle_YYYYMMDD_HHMMSS.tar.gz
```

- `BUNDLE_INFO.txt` 中 `包含 Postgres: 是`、`包含 Qdrant: 是`（Docker 在跑时）。
- 如果 `models/` 没有模型文件，会出现警告，但不应该导致打包失败。
- Docker 未运行时仅打文件层，会警告并跳过数据库备份。

## 13. 导入部署测试

建议先导入到临时目录（默认安装到**当前目录**）：

```bash
mkdir -p /tmp/shuxin-voice-demo-import && cd /tmp/shuxin-voice-demo-import
bash /path/to/shuxin/scripts/import_deploy.sh /tmp/shuxin_voice_export_test/shuxin_voice_bundle_YYYYMMDD_HHMMSS.tar.gz
```

也可指定安装目录：`bash scripts/import_deploy.sh <bundle> /other/path`，或 `INSTALL_DIR=/other/path bash scripts/import_deploy.sh <bundle>`。

导入顺序：解包 → 恢复 bind mount → 从 `.env.example` 生成 `.env`（**不含密钥，需手动填**）→ `pg_restore` + Qdrant 卷 → `redeploy_docker.sh --build` 全栈启动。

验收标准：

- bundle 解包成功。
- 自动创建 `.env`（若不存在）和 `data/devices.yaml`（若 bundle 未带）。
- `docker compose build` 成功（由 redeploy 触发）。
- Postgres / Qdrant 数据已恢复（有 dump 时：`docker exec shuxin-postgres psql -U shuxin -d shuxin -c 'SELECT COUNT(*) FROM users;'` 与源环境一致）。
- `http://localhost:8765/health` 可达（或 import 脚本 health check 通过）。
- 填好 `.env` 中 `DEMO_LLM_API_KEY` 后，Web 测试台可对话。

## 14. Docker 日常重部署

代码发生变化后，可以使用：

```bash
bash scripts/redeploy_docker.sh
```

这个命令默认是日常重启，不会重新安装 `torch`、`funasr`、`modelscope` 等大包。只有以下情况会触发 Docker build：

- 本地没有 `shuxin-voice-demo:latest` 镜像。
- `requirements-voice-heavy.txt` 或 `requirements-voice-app.txt` 的依赖 hash 变化。
- 显式执行 `bash scripts/redeploy_docker.sh --build`。

日常小包（Opus、websockets、设备绑定等）写入 `requirements-voice-app.txt`，只会 rebuild app 层，不会重下 torch。

如果只想强制跳过 build，可以使用：

```bash
bash scripts/redeploy_docker.sh --no-build
```

验收标准：

- Docker Desktop 中 `shuxin-voice-demo-pg` 显示 Running。
- 普通代码变更后，终端输出「仅代码变更，跳过依赖层构建」。
- `models/`、`samples/`、`outputs/` 等挂载数据不会因为重部署丢失。

## 16. 火山 TTS + Agent 切换实时验收

本节验收 **Admin Agent API**、**用户绑定 Agent** 与 **WebSocket 全链路 TTS**。

### 16.1 环境与重部署

```bash
# .env（勿提交）
VOLCENGINE_TTS_API_KEY=...
VOLCENGINE_TTS_VOICE_TYPE=S_xxx

bash scripts/redeploy_docker.sh
curl -s http://localhost:8765/health
docker exec shuxin-voice-demo-pg sh -c 'test -n "$VOLCENGINE_TTS_API_KEY" && echo ok'
```

### 16.2 Admin API 试听（不经过 LLM）

```bash
export ADMIN_TOKEN=dev-admin-token   # 与 SHUXIN_ADMIN_TOKEN 一致

curl -s -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8765/admin/api/agents

curl -s -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"agent_id":"shuxin","text":"你好，试听火山复刻"}' \
  http://localhost:8765/admin/api/tts/preview
```

返回 JSON 含 `audio_url`，浏览器或 `curl -O` 下载播放。

### 16.3 用户切换 Agent

1. 打开 `http://localhost:8765/admin` → **Agent** Tab 确认 `shuxin` 存在且 `voice_type` 已填。
2. **用户** Tab 下拉为 `demo-user` 选择 Agent → 自动 `PATCH /admin/api/users/{id}`。
3. 或使用 curl：

```bash
curl -s -X PATCH -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"agent_id":"shuxin"}' \
  http://localhost:8765/admin/api/users/demo-user
```

### 16.4 WebSocket 准实时全链路

按 §9 流程；额外验收：

1. voice-demo「加载设备」条目应显示 `Agent=…` 与 masked 音色。
2. 对话完成后听到火山复刻音色（非 Edge 默认女声）。
3. **切换 Agent 后必须断开并重连** WebSocket，同一句台词应变为新音色。
4. 两台设备若 `metadata.mbti` 不同（批量制码随机写入），对话语气应不同、音色相同（同一 `users.agent_id`）。

### 16.5 故障对照

| 现象 | 排查 |
|------|------|
| hello 有 MBTI 文字无 TTS，首轮 `chat_stream` NoneType | 升级至 2026-06-08 后含 `_ensure_runtime` 修复的版本 |
| `voice_type` ValueError | compose 未透传 env → `redeploy_docker.sh` |
| TTS 成功但仍是旧音色 | 未重连 WS；或 `users.agent_id` 未更新 |
| 仍走 Edge/local | Postgres `tts_config.type=local` → 「全部应用火山 TTS」 |
| `agent/error connect_error` | 用户 LLM 未配 key（与 TTS 无关） |

## 17. Opus 硬件路径冒烟测试

硬件联调使用 **Opus wire format**（上行 16 kHz / 下行 24 kHz / 60 ms 帧），与浏览器 PCM/mp3 路径分离。

**全程在 Docker 容器内执行**（与 [`VOICE_DOCKER_WORKFLOW.md`](VOICE_DOCKER_WORKFLOW.md) 一致）。`opuslib_next` 写在 **`requirements-voice-app.txt`**（app tier，§ voice-cloud）；改 app 层 **不会** 重下 torch。

### 17.1 依赖与重部署

```bash
bash scripts/redeploy_docker.sh
# 预期：依赖 tier 变更: app(voice-app)（若 app 层有变更）
docker exec shuxin-voice-demo-pg python -c "import opuslib_next; print('ok')"
```

迁移环境时 `export_pack.sh` / `import_deploy.sh` + 上述 redeploy 会自动带上 Opus，无需手工 `pip install`。

### 17.1b 单元测试（容器内）

```bash
docker exec shuxin-voice-demo-pg pip install pytest
docker exec -w /app shuxin-voice-demo-pg env PYTHONPATH=src \
  python -m pytest tests/test_opus_codec.py -q
```

镜像已含 `opuslib_next` 时应 6 passed；旧镜像未 redeploy 时 opus 相关用例 skip。

### 17.2 参考客户端（无硬件）

使用 [`data/test/activation.ogg`](../data/test/activation.ogg)（Ogg 封装 Opus）模拟固件上行；脚本会拆成 raw Opus 帧再发送（固件应直接发帧，不要发 Ogg 文件）。

前置：设备已绑定、用户 LLM 与 STT/TTS 凭证有效（同 §9 / §16）。

```bash
# 设备密钥与 compose 中 SHUXIN_DEVICE_SHARED_SECRET 一致（默认 dev-device-secret）
docker exec shuxin-voice-demo-pg python scripts/ws_opus_smoke_test.py \
  --url ws://127.0.0.1:8765/ws/voice \
  --device-code demo-device-001 \
  --device-secret dev-device-secret \
  --input /app/data/test/activation.ogg \
  --output /app/outputs/opus-smoke-reply.wav
```

验收：

- 终端打印 `hello ok` 且含 `audio_params.format=opus`
- 有 `stt/final` 文本、`agent/reply` 文本
- 下行收到多帧 Opus（非 mp3 魔数）
- `outputs/opus-smoke-reply.wav` 可播放

协议细节见 [`VOICE_HARDWARE_WS_PROTOCOL.md`](VOICE_HARDWARE_WS_PROTOCOL.md) §2 Opus。

### 17.3 故障对照

| 现象 | 排查 |
|------|------|
| `opus support requires opuslib_next` | `bash scripts/redeploy_docker.sh`（检查 `requirements-voice-app.txt`） |
| `invalid device secret` / 未绑定 | §9 设备绑定与 `SHUXIN_DEVICE_SHARED_SECRET` |
| 下行仍是 mp3 | `hello` 未带 `audio_params.format=opus` |
| `no stt/final` | 腾讯 STT 凭证或 `activation.ogg` 内容过短 |

## 18. 设备 Flash 提示音资产生成

固件 UI 固定文案（非 WebSocket 对话）使用预生成 Opus，源文件 [`data/device_assets/strings.zh-CN.json`](../data/device_assets/strings.zh-CN.json)。Flash 档为 **16 kHz / 16 kbps**（对齐 xiaozhi-esp32）；WebSocket 实时 TTS 仍为 24 kHz。

```bash
# 需 .env 中 VOLCENGINE_TTS_* 已配置且容器已 redeploy
docker exec shuxin-voice-demo-pg env PYTHONPATH=/app/src \
  python /app/scripts/generate_device_prompt_assets.py \
  --out /app/data/device_assets/zh-CN \
  --format both

# 体积抽查（zh-CN 48 条参考：目录 ~444KB，ogg ~216KB，opus.bin ~208KB；无 _tmp/）
du -sh data/device_assets/zh-CN
du -ch data/device_assets/zh-CN/*.ogg | tail -1
du -ch data/device_assets/zh-CN/*.opus.bin | tail -1
test ! -d data/device_assets/zh-CN/_tmp && echo "no _tmp OK"

# 听感抽查
ffplay data/device_assets/zh-CN/STANDBY.ogg
ffplay data/device_assets/zh-CN/CHECK_NEW_VERSION_FAILED.ogg
```

无 TTS 凭证时，可仅把已有 OGG 压到 Flash 档（需 Docker 内 `libopus`）：

```bash
docker run --rm -v "$(pwd)":/app -w /app -e PYTHONPATH=/app/src \
  --entrypoint python "$(docker inspect -f '{{.Config.Image}}' shuxin-voice-demo-pg)" \
  /app/scripts/generate_device_prompt_assets.py \
  --out /app/data/device_assets/zh-CN --format both --reencode-existing
```

验收：`manifest.json` 含 `profile: flash`、`sample_rate: 16000` 与全部 key；`CHECK_NEW_VERSION_FAILED` 播报「检查新版本失败，将在30 秒后重试！」；`FOUND_NEW_ASSETS` 为「发现新资源 2」。固件接入见 [`VOICE_HARDWARE_QUICKSTART.md`](VOICE_HARDWARE_QUICKSTART.md) §5。

## 15. 最终通过标准

最小可测试单元通过标准：

- `PYTHONPATH=src python3 -m shuxin.voice.cli --help` 可用。
- `docker compose config` 可用。
- Docker 内 `python -m shuxin.voice.cli --help` 可用。
- `tts` 可以生成音频文件。
- 有模型和样本音频时，`stt` 可以输出文字。
- 有 LLM 配置时，`chat-audio` 可以输出识别文本、Agent 回复和回复音频。
- 有 LLM 配置时，`session` 可以输出初始化音频、回复音频和 transcript。
- 有 LLM 配置和浏览器麦克风权限时，Web 测试台可以完成按住说话、松手识别、回复和播放。
- 按 §11 固定剧本验收时，重连后回复能关联 `rolling_summary` 中的主题，且 `/voice/export` 在第五轮后与断线后含非空 `rolling_summary`。
- `export_pack.sh` 可以打包（含 Postgres + Qdrant 时可完整迁移）。
- `import_deploy.sh` 可以在新目录恢复并跑通全栈（health + voice server）。
