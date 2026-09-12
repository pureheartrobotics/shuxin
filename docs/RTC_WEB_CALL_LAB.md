# Web ↔ Web 真人通话 Lab（当前主路径）

目标：两端都是浏览器 [`/voice-demo`](../src/shuxin/voice/static/demo.html)，接通后能互相说话。  
媒体：**浏览器 ↔ 百度 RTC ↔ 浏览器**，不经舒心服务器。舒心只做信令与 token。

规格总览与带宽口径：[`RTC_DEVICE_CALL_SPEC.md`](RTC_DEVICE_CALL_SPEC.md)。  
硬件振铃（无真媒体）：[`RTC_HARDWARE_CALLEE_LAB.md`](RTC_HARDWARE_CALLEE_LAB.md)。

## 角色

| 窗口 | 身份 | 操作 |
|------|------|------|
| A 主叫 | `rtc_lab_caller` · `SX-RTC-CALLER` | 说「打电话给小明」 |
| B 被叫 | `rtc_lab_callee` · `SX-RTC-CALLEE` | 接听 → 真听声 |

## 前提

1. `.env`：`SHUXIN_RTC_CALL_ENABLED=1`，已配 `BAIDU_RTC_APP_ID` / `BAIDU_RTC_APP_KEY`
2. Voice 已起：`bash scripts/redeploy_docker.sh --skip-build`
3. 必须用 **`http://127.0.0.1:8765/voice-demo`**（localhost 才能开麦；勿用局域网 IP 测听声）

## Seed

```bash
export SHUXIN_ADMIN_TOKEN=...   # 与 .env 一致

# 首次造用户/设备/通讯录（小明 → bob）
python3 scripts/seed_rtc_lab_two_peers.py --base http://127.0.0.1:8765 --token "$SHUXIN_ADMIN_TOKEN"

# 容器/进程重启后只需恢复内存舒心号（必做，否则显示「没有在线设备」类失败）
python3 scripts/seed_rtc_lab_two_peers.py --base http://127.0.0.1:8765 --handles-only --token "$SHUXIN_ADMIN_TOKEN"
```

## 操作步骤

1. **两窗**打开 `http://127.0.0.1:8765/voice-demo`
2. 填 Admin Token → 加载设备  
   - A：选 `rtc_lab_caller · SX-RTC-CALLER` → **连接**  
   - B：选 `rtc_lab_callee · SX-RTC-CALLEE` → **连接**  
3. 每窗顶部日志应有 `Baidu BRTC Web SDK loaded`  
   - 若是 `MISSING` / 接通后 `stub join` / 红条：**Ctrl+Shift+R** 硬刷新两端；看 Console CDN/local SDK 错误  
4. A 进入聆听，说「打电话给小明」  
5. B 出现来电 → **接听**（允许麦克风）  
6. 两端状态「通话中」；日志 `BRTC joined` + `In call …`  
7. **同机请戴耳机**防啸叫；互相对话应能听见  
8. 任一侧点 **挂断** → 本端 `BRTC left room`；对端收到 `call/end` 并离开房间；之后可继续 AI 对话  

通话中 **不要断 WS**（保持连接以便挂断信令）；语音仍不走舒心。

## 挂断行为（已实现）

| 动作 | 行为 |
|------|------|
| 本端点挂断 | `call/end` → 服务端通知对端 → 两端 `BRTC_Stop` / leave |
| 对端挂断 | 收到 `call/end` → leave 百度房间 → UI Idle |
| WS 断开 | `onWsClosed` → 本地 leave（避免幽灵房间） |

## 自检脚本

```bash
python3 scripts/check_brtc_web_sdk_load.py --base http://127.0.0.1:8765
pytest tests/test_brtc_token.py tests/test_voice_call_signaling.py tests/test_ws_send_json_guard.py -q
```

## 常见问题

- **bob 没有在线设备**：B 窗未连接，或容器重启后未 `--handles-only`
- **只有铃/接听无声音**：SDK stub（硬刷新）；或未用 127.0.0.1；或未允许麦
- **一边有声一边没有**：另一边未进房 / token 失败，对照两端是否都有 `BRTC joined`
- **把语音带宽算到舒心**：错误；媒体直连百度，见规格「服务器带宽误解澄清」
