# 初心 / 舒心 — 服务器汇总（拆仓预备）

> 本文把「语音 / 设备 / 小程序后端」相关的**地址、边界、部署、协议入口**收成一份。  
> 用途：日常查入口；以及日后把 **shuxin 服务器**拆成独立仓库时的种子 README。  
> **不是**替代各专题文档——细节仍以链接目标为准。

---

## 1. 一句话定位

**舒心服务器** = 陪伴机器人的云端 BFF：设备鉴权、语音闭环（STT → Agent → TTS）、用户/设备/额度、微信与支付回调、Admin。

客户端（小程序、固件、Android 脸屏、其它机器人）通过 **HTTPS + WebSocket** 接入；**不**在固件里直连 STT/TTS/LLM 厂商。

---

## 2. 服务地址

| 环境 | HTTP API / 健康检查 | 语音 WebSocket | 说明 |
|------|---------------------|----------------|------|
| **生产** | `https://shuxinzzx.com.cn` · `/health` | `wss://shuxinzzx.com.cn/ws/voice` | 小程序默认 API：`scripts/wechat_miniprogram_dev.sh` 的 `DEFAULT_API_BASE` |
| **本地 Docker** | `http://localhost:8765/health` | `ws://localhost:8765/ws/voice` | 端口：`VOICE_DEMO_PORT`（默认 8765） |
| **局域网联调** | `http://<LAN_IP>:8765` | `ws://<LAN_IP>:8765/ws/voice` | 固件与小程序应对**同一台** Voice 服务 |

其它：

| 用途 | 地址 |
|------|------|
| 浏览器假硬件测试台 | `http://<host>:8765/voice-demo` |
| 后台 Admin | `http://<host>:8765/admin`（token：`SHUXIN_ADMIN_TOKEN`） |
| 静态 CDN（七牛） | `cdn.shuxinzzx.com.cn`（非语音主通道） |
| 百度 RTC 信令媒体 | `BAIDU_RTC_*`（媒体不经舒心转发） |

支付回调路径固定：`/api/payment/notify`（生产须 HTTPS 正式域名，勿留 trycloudflare）。

---

## 3. 建议拆仓时的代码边界

当前仍是 monorepo（`F:\shuxin`）。**服务器侧**建议纳入独立项目的目录：

| 路径 | 职责 |
|------|------|
| `src/shuxin/voice/` | Voice BFF：WebSocket、HTTP API、Admin、计费、设备绑定 |
| `src/shuxin/core/` | Agent / LLM / 记忆 / 插件调度（语音路径会调用） |
| `src/shuxin/plugins/companion/` | 陪伴人格注入（自尊、情感等） |
| `src/shuxin/integrations/` | 地图 MCP 等平台托管集成 |
| `docker-compose.yml` + `Dockerfile` | Postgres + Qdrant + voice 容器 |
| `requirements-voice-*.txt` | 语音镜像依赖分层 |
| `scripts/redeploy_docker.sh` 等 | 重部署 / 打包迁移 |
| `data/`（配置样例，不含密钥） | `devices.yaml.example`、`tts_profiles`、支付套餐样例 |
| `docs/` 下服务器相关文档 | 见 §7 |
| `tests/` 中 voice / payment / factory 等 | 服务端回归 |

**通常不放进「纯服务器仓」**（可另仓或子模块）：

- `apps/wechat-miniprogram/` — 微信客户端  
- `android-app/`、`esp32_*`、`RK3566*` — 车上脸屏 / 下位机固件  
- 本地刷机包、硬件资料、大体积镜像  

Agent CLI（`shuxin` 命令）可随 core 一起迁，或拆成「SDK / 库」被 voice 依赖。

---

## 4. Docker 服务拓扑

```text
客户端（固件 / 小程序 / voice-demo）
        │
        ▼
┌───────────────────────┐
│ shuxin-voice-demo-pg  │  :8765  ← FastAPI + WS
│  python -m shuxin.voice.server
└───────────┬───────────┘
            │
     ┌──────┴──────┐
     ▼             ▼
 postgres       qdrant
 (设备/用户/额度)  (Mem0 向量，本地宿主机常映射 6335→6333)
```

常用命令：

```bash
cp .env.example .env          # 填密钥；生产勿照搬本地
bash scripts/redeploy_docker.sh
curl -sf http://localhost:8765/health

# 生产建议
export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
bash scripts/redeploy_docker.sh
```

详细：[`VOICE_DOCKER_WORKFLOW.md`](VOICE_DOCKER_WORKFLOW.md)、[`DEPLOY_SERVER.md`](DEPLOY_SERVER.md)。

---

## 5. 对外能力一览

### 5.1 固件 / 其它机器人（主通道）

- 唯一运行时通道：`/ws/voice`
- 先发连接：`user_name` + `robot_code`（可带 `type: hello`；兼容 `device_code`；**不要** `device_secret`）
- 再 `listen` / 二进制音频；收 `agent/*`、`tts/*`、`stt/*` 等
- **不要**在设备上直调厂商 ASR/TTS API

速查：[`VOICE_HARDWARE_QUICKSTART.md`](VOICE_HARDWARE_QUICKSTART.md)  
协议：[`VOICE_HARDWARE_WS_PROTOCOL.md`](VOICE_HARDWARE_WS_PROTOCOL.md)

### 5.2 HTTP（小程序 / Admin / 支付）

固件一般不走业务 HTTP；小程序与运营台使用 `/api/...`、`/admin/...`。常见能力：

- 微信登录 / 用户 / 设备绑定与列表  
- 额度与微信支付回调  
- 工厂验收相关 API  
- Admin：用户、设备、制码、Agent/TTS、额度  

### 5.3 一轮语音（服务端内部）

```text
stt/final → agent/thinking → agent/delta → tts/sentence_* → agent/reply → tts/stop
```

失败时先下发 `agent/error`（含 `error_kind`）。架构见 [`VOICE_ARCHITECTURE.md`](VOICE_ARCHITECTURE.md)。

---

## 6. 环境变量（接入方 vs 运维）

### 6.1 另一个机器人项目最少需要知道的

| 项 | 值 |
|----|-----|
| WS URL | 生产 `wss://shuxinzzx.com.cn/ws/voice`；开发 `ws://<host>:8765/ws/voice` |
| 鉴权 | `user_name`（用户显示名）+ `robot_code`（机器人代号）；服务端自动建用户/设备并绑定 |
| 音频 | 上行常见 Opus 16 kHz；以 `hello` 协商为准 |
| 健康检查 | `GET /health` |

禁用用户或禁用设备会被拒绝；无需事先烧录 `device_secret`。

### 6.2 运维侧密钥类（勿提交 Git）

见仓库根目录 `.env.example`，生产重点包括：

- `DEMO_LLM_*` / `DMX_*` — LLM  
- `TENCENT_*` — 实时 ASR  
- `VOLCENGINE_TTS_*` — 火山复刻 TTS  
- `DATABASE_URL`、`SHUXIN_MEM0_*`、`QDRANT_*`  
- `SHUXIN_WECHAT_*`、`SHUXIN_WXPAY_*`  
- `SHUXIN_ADMIN_TOKEN`、`SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY`  
- `SHUXIN_DEVICE_SHARED_SECRET`  

上线核对清单：[`DEPLOY_SERVER.md`](DEPLOY_SERVER.md)。

---

## 7. 文档索引（服务器相关）

| 文档 | 何时读 |
|------|--------|
| **本文** `SHUXIN_SERVER.md` | 总入口 / 拆仓预备 |
| [`DEPLOY_SERVER.md`](DEPLOY_SERVER.md) | 生产部署检查 |
| [`VOICE_DOCKER_WORKFLOW.md`](VOICE_DOCKER_WORKFLOW.md) | Docker 构建与日常重部署 |
| [`VOICE_ARCHITECTURE.md`](VOICE_ARCHITECTURE.md) | 语音闭环与边界 |
| [`VOICE_DEMO_MIN_TEST.md`](VOICE_DEMO_MIN_TEST.md) | 无硬件冒烟、打包迁移 §12–14 |
| [`VOICE_HARDWARE_HANDBOOK.md`](VOICE_HARDWARE_HANDBOOK.md) | 硬件对接总手册 |
| [`VOICE_HARDWARE_QUICKSTART.md`](VOICE_HARDWARE_QUICKSTART.md) | 固件 1 页速查 |
| [`VOICE_HARDWARE_WS_PROTOCOL.md`](VOICE_HARDWARE_WS_PROTOCOL.md) | WS 字段协议 |
| [`VOICE_HARDWARE_INTEGRATION.md`](VOICE_HARDWARE_INTEGRATION.md) | 鉴权与云能力边界 |
| [`VOICE_HARDWARE_TTS_DOWNLINK.md`](VOICE_HARDWARE_TTS_DOWNLINK.md) | TTS Opus 下行 |
| [`VOICE_QUOTA_GATE_TEST.md`](VOICE_QUOTA_GATE_TEST.md) | 额度门控验收 |
| [`FACTORY_ACCEPTANCE_HANDOFF.md`](FACTORY_ACCEPTANCE_HANDOFF.md) | 出厂验收 |
| [`PAYMENT_DEV_SETUP.md`](PAYMENT_DEV_SETUP.md) | 支付联调 / 上线域名 |
| [`WECHAT_MINIPROGRAM.md`](WECHAT_MINIPROGRAM.md) | 小程序与后端域名合规 |
| [`RTC_DEVICE_CALL_SPEC.md`](RTC_DEVICE_CALL_SPEC.md) 等 | 真人通话（Pure RTC） |
| 根目录 [`AGENTS.md`](../AGENTS.md) | AI/协作约束与语音坑 |

根 [`README.md`](../README.md) 仍是**整个 monorepo** 简介；**服务器专题以本文 + 上表为准**。

---

## 8. 给「另一个机器人项目」的接入清单

1. 约定 `user_name`（谁在用）和 `robot_code`（哪台机器人，建议全局唯一）。  
2. 实现 WebSocket 客户端，连生产或联调 URL（§2）。  
3. 按 [`VOICE_HARDWARE_WS_PROTOCOL.md`](VOICE_HARDWARE_WS_PROTOCOL.md) 发 `user_name` + `robot_code` → 再上行音频 / `listen`。  
4. 用 `/health` 确认网络与 TLS；生产必须用 `wss`。  
5. 不要把 `.env` 里的云厂商密钥写进机器人固件——密钥留在舒心服务器。

控车 / MCP 等扩展见仓库内 `MCP_CHASSIS_HANDOFF.md`（若该机器人需要底盘指令）。

---

## 9. 拆成独立仓库时建议的第一步

1. 新建仓（例如 `shuxin-server`），按 §3 拷贝/subtree 相关目录。  
2. 把**本文**升为新仓根 `README.md`，专题文档继续放 `docs/`。  
3. 明确对外 semver：WS 协议与 `/health`、关键 `/api` 兼容策略。  
4. 生产域名与证书、compose、密钥轮换流程写进 `DEPLOY_SERVER.md`。  
5. 客户端仓只依赖「URL + 协议文档 + 设备密钥」，不依赖本仓源码树。

---

## 10. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-11-07 | 初版：从 monorepo 文档与脚本汇总，供拆仓与外接机器人使用 |
