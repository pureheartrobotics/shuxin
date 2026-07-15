# Spec: 舒心纯 RTC 真人通话

## 当前锁定（必读）

| 路径 | 状态 | 说明 |
|------|------|------|
| **Web ↔ Web 真听声** | **当前主路径** | `/voice-demo` 双窗，媒体走百度 RTC，不经舒心 |
| Web ↔ 硬件 | 信令可用 | 振铃 / 接听 / `call/connected`；硬件无真媒体（ESP32-C3 无公开 `libbrtc.a`） |
| 硬件 ↔ 硬件真听声 | 未落地 | 需可链的芯片侧 Pure RTC 库（公开文档不对 C3） |

- 舒心 Agent 仅作 **拨号助手**（听懂「打电话给 xxx」→ 信令 → TTS「正在呼叫」）
- **AppKey 仅服务端**；浏览器 / 固件只收 token
- 切面接入，不破坏现有 AI 对话主链

验收主手册：[`RTC_WEB_CALL_LAB.md`](RTC_WEB_CALL_LAB.md)。硬件信令 lab：[`RTC_HARDWARE_CALLEE_LAB.md`](RTC_HARDWARE_CALLEE_LAB.md)。

## 服务器带宽误解澄清

**密钥/信令过舒心；声音不过舒心。**

```text
拨号/接听：  浏览器 ──小 JSON + token──→ 舒心服务器
通话中说话：  浏览器 A ←══ Opus ══→ 百度 RTC ←══ Opus ══→ 浏览器 B
              （用户网卡直连百度；舒心网卡看不见媒体码率）
挂断：       可选再过 call/end（KB 级）
```

| 阶段 | 过舒心？ | 对舒心的影响 |
|------|----------|--------------|
| 在线待命 | 轻量 WS + 心跳 | 连接数 / 内存 |
| 拨号 / 振铃 / 接听 | 是（KB 级） | 可忽略带宽 |
| 通话中实时说话 | **否** | 媒体在用户侧 + 百度 |
| 挂断 | 常再过一次小信令 | 可忽略 |

几十人同时 Web 通话：涨的是 **用户流量 + 百度 RTC 账单**，不是舒心出口被语音打满。  
真正吃舒心大带宽的是：**很多人同时跟机器人 STT/TTS**。

通话中两端 **保持 WS 不断开**（挂断 / 对端离线通知）= 连接保活，**不是**媒体中转。

## 配置指南（必读）

### 1. 百度 RTC 控制台

1. 登录 [百度智能云 RTC 控制台](https://console.bce.baidu.com/rtc/)
2. 创建应用，记录 **AppID**、**AppKey**（等同密钥，勿泄露）
3. Web 媒体使用官方 Web SDK（仓库已 vendoring `baidu.rtc.sdk.js`）
4. 固件真媒体（后置）：需芯片匹配的 FreeRTOS Pure RTC 包；[集成 FreeRtos SDK](https://cloud.baidu.com/doc/RTC/s/Rktjtwo3c) 面向 ASR3601，**不能直接用于 ESP32-C3**

Token 算法：[RTC 快速开始](https://cloud.baidu.com/doc/RTC/s/Qjxbh7jpu)

### 2. 舒心语音后端环境变量（`.env`）

```bash
SHUXIN_RTC_CALL_ENABLED=1
BAIDU_RTC_APP_ID=你的AppID
BAIDU_RTC_APP_KEY=你的AppKey
BAIDU_RTC_SERVER_URL=wss://rtc.exp.bcelive.com/janus
BAIDU_RTC_TOKEN_TTL_SECONDS=3600
SHUXIN_CALL_RING_TIMEOUT_SECONDS=30
```

改 `.env` 后：`bash scripts/redeploy_docker.sh --skip-build`  

未配置 AppID/AppKey 时通话自动禁用，不影响 AI 对话。

### 3. ESP32 固件（信令 / 铃声，非真媒体）

`CONFIG_SHUXIN_RTC_CALL_ENABLED=y`；缺 `libbrtc.a` 时仍为 stub（仅日志）。量产板为 **ESP32-C3**，公开乐鑫包多为 **S3**，本阶段不以硬件真听声为目标。

## 数据流（Web 主路径）

```text
① 两端 voice-demo 连接并保持 WS
② 主叫听「打电话给小明」→ STT → call_service
③ 舒心签发 token，推 call/outgoing / call/ring
④ 被叫接听 → call/connected（各自 token）
⑤ 两端 BRTC_Start → 百度房间 → 真人语音（不经舒心）
⑥ 任一侧挂断 → call/end + BRTC_Stop → Idle；WS 仍可保活
```

## 计费

预留 `CallBillingRecorder`，首版不扣费。见 `integrations/voice_call/billing.py`。

## 双浏览器真听音

见 **[`RTC_WEB_CALL_LAB.md`](RTC_WEB_CALL_LAB.md)**（seed、硬刷新、听声、挂断）。

本地 SDK 检查：

```bash
python3 scripts/check_brtc_web_sdk_load.py --base http://127.0.0.1:8765
```

## 硬件被叫（仅信令）

见 [`RTC_HARDWARE_CALLEE_LAB.md`](RTC_HARDWARE_CALLEE_LAB.md)。

## 验收

1. `pytest tests/test_brtc_token.py tests/test_voice_call_signaling.py tests/test_ws_send_json_guard.py`
2. Web↔Web：[`RTC_WEB_CALL_LAB.md`](RTC_WEB_CALL_LAB.md) 全流程 + 真听声 30s + 挂断
3. 回归：绑定向导、工厂验收、MBTI、地图 tool、配额门控不受影响
