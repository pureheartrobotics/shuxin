# Browser caller ↔ hardware callee (local LAN lab)

> **真听声请走 Web↔Web**：[`RTC_WEB_CALL_LAB.md`](RTC_WEB_CALL_LAB.md)。  
> 本文只验证硬件 **振铃 + 接听信令**；ESP32-C3 无公开 Pure RTC 库前，板子不会有双向说话。

PC LAN IP for this lab: **192.168.10.2**

| Role | Identity | Action |
|------|----------|--------|
| Browser | `rtc_lab_caller` / `SX-RTC-CALLER` | Say「打电话给小明」 |
| Hardware | `SX-000003` (factory) bound to `rtc_lab_callee` | Local ringtone → **LISTEN** = accept / again = hangup |

Firmware project: `E:\work\work\shuxin\yingjian\SHUXIN-esp32-2.0.3-button`

- `CONFIG_SHUXIN_RTC_CALL_ENABLED=y`
- `CONFIG_SHUXIN_WEBSOCKET_URL="ws://192.168.10.2:8765/ws/voice"`
- Incoming ring loops local `OGG_RTC_MODE_ON` (~3.5s)
- NVS 若仍存 `shuxinzzx.com.cn`，固件会忽略并回退到上面的编译默认 URL（需刷含此逻辑的固件）
- **RTC 常驻信令**：开机 WiFi/协议就绪后自动 `OpenAudioChannel` + hello，**无需先按聆听**即可被打进；空闲只保连接（心跳），不连续上传麦克风。对话仍靠聆听键 / 唤醒词。

**No real bidirectional media until `libbrtc.a` is installed.** Accept = signaling + ringtone stop.

## Idle 带宽 vs 对话 / 打电话

| 状态 | 做什么 | 带宽 |
|------|--------|------|
| 空闲常驻 | WS + hello 后在线，收 `call/ring` | 极低（心跳） |
| 对话 | 按聆听 / 唤醒词后 STT→LLM→TTS | 高（按说话时长） |
| 打电话 | 对话中说「打电话给小明」；媒体走百度 RTC | 舒心侧主要为信令 JSON |

## 「bob 当前没有在线设备」常见误判

- Admin「绑定」有行 ≠ 通话在线。在线 = 板子对**本机** Voice 完成 `hello state=ok`，且 `user_id=rtc_lab_callee` 登记进 `voice_session_registry`。
- 刷完 RTC 常驻固件后，串口应在开机后不久出现 `Connecting to ShuXin websocket`，**不要**再期望「先按聆听才连」。若一直连不上，才是 URL/防火墙/鉴权问题。
- 旧固件串口播「请输入控制码 / binding hint」：曾表示 **WS 通道未打开**（按键才连时代码误报），不要只当「Admin 没绑」。
- Admin 里 `SX-RTC-CALLEE`「在线」多半是浏览器 Tab，不是板子。

## Ops

### A. Start voice on PC

```bash
bash scripts/redeploy_docker.sh --skip-build
# Firewall: allow inbound TCP 8765 on 192.168.10.2
```

### B. Seed + bind (secret 已与 factory 头一致时不要乱 rotate)

```bash
export SHUXIN_ADMIN_TOKEN=...   # from .env
python3 scripts/seed_rtc_lab_two_peers.py --base http://127.0.0.1:8765
python3 scripts/bind_rtc_lab_hardware_callee.py --base http://127.0.0.1:8765 --sync-firmware-header
# 仅当 confirm secret 与固件不一致时才加 --rotate
# 容器重启后:
python3 scripts/seed_rtc_lab_two_peers.py --base http://127.0.0.1:8765 --handles-only
```

### C. Flash firmware (Windows ESP-IDF)

```text
cd E:\work\work\shuxin\yingjian\SHUXIN-esp32-2.0.3-button
idf.py build flash monitor
```

Monitor 必须**在未按聆听**时就看到类似：

```text
RTC mode: opening always-on signaling websocket
Connecting to ShuXin websocket server: ws://192.168.10.2:8765/ws/voice
```

以及 hello `state=ok`（服务端 user 为 `rtc_lab_callee`）。  
若仍出现 `Ignoring legacy cloud websocket url from NVS`，说明旧 URL 已被清掉并改用编译默认。

### D. Call test

1. Browser `http://127.0.0.1:8765/voice-demo` → connect **SX-RTC-CALLER** only  
2. Board online（见上，**勿先按聆听**）  
3. 「打电话给小明」→ 板子本地铃声 → **LISTEN** 接听  
4. 对照：第二浏览器窗连 `SX-RTC-CALLEE` 能振铃，则服务端正常、只差板子 WS/hello  

## 如何跟机器人说话 / 如何拨号

1. **对话**：待机时空闲 WS 在线；按 **LISTEN** 或说唤醒词 → 进入聆听 → 才上行语音（占带宽）。  
2. **打出电话**：进入对话后说「打电话给小明」；被叫需同样在线（常驻轻量 WS）。  
3. **接听**：来电本地铃声 → 再按 LISTEN。

## Buttons

- LISTEN (GPIO9): accept while ringing; end while in call; otherwise start/continue AI listening  
- RESET: hardware reset only  
