# ESP32 语音控车对接（MCP）

分支：`esp32`（从 `master` 拉出，**不含** RK3566）。  
RK3566 板端在 `feature/rk3566`，两条线分开跑。

目标：车上说话 → 云端听写成字 → **服务端立刻给 ESP32 发 MCP 开车**。不等 LLM 说完。网页 `/voice-demo` 不会动轮子。

---

## 1. 固件要做的

1. `hello` 必须带设备身份和 MCP 开关（`client_id` 可省略；不要用浏览器测试台那种不带 `features.mcp` 的 hello）：

```json
{
  "type": "hello",
  "device_code": "<device_id>",
  "device_secret": "<device_secret>",
  "client_id": "esp32-car",
  "features": { "mcp": true },
  "audio_params": {
    "format": "opus",
    "sample_rate": 16000,
    "channels": 1,
    "frame_duration": 60
  }
}
```

2. 收到 `type=mcp` 后按虾哥协议处理 JSON-RPC。后端顺序是：

```text
hello ok
  → MCP initialize          （等你回 result）
  → MCP tools/list          （等你回工具列表）
  → 用户说话命中口令
  → MCP tools/call          （开车）
  → duration 到了再 tools/call self.chassis.stop
```

3. `tools/list` 至少返回：

```text
self.chassis.go_forward
self.chassis.go_back
self.chassis.turn_left
self.chassis.turn_right
self.chassis.stop
```

工具不要参数（`PropertyList()` / `arguments: {}`）即可。后端会在 0.8～4 秒后自己发 `stop`。若你在 `inputSchema.properties` 里声明了 `duration` / `speed`，后端才会把这两个字段放进 `arguments`。

4. `stop` 必须立刻刹车。新的前进/转向会取消上一次定时停车。用户说「停」或上行 `abort`，后端也会马上 `self.chassis.stop`。

5. 不要在板子上存 LLM / ASR / TTS Key。

---

## 2. 软件会做什么

| 说 | MCP 工具 | 默认时长 |
|----|----------|----------|
| 前进 / 往前走 / 过来 | `self.chassis.go_forward` | 1.5s（「一点」0.8s） |
| 后退 / 往后 / 倒车 | `self.chassis.go_back` | 同上 |
| 左转 / 向左 | `self.chassis.turn_left` | 同上 |
| 右转 / 向右 | `self.chassis.turn_right` | 同上 |
| 停 / 停下 / 别动 | `self.chassis.stop` | 立刻 |
| 前进两秒 / 前进 2 秒 | 对应方向 | 最长 4s |

普通聊天（「你好初心」）不会开车。

`initialize` 若 2 秒没回包，后端会自行再发 `tools/list`（兼容只实现了 list 的固件）。口令若出现在工具列表之前，会排队，列表一到立刻下发。

---

## 3. 真机怎么跑

1. 部署 **`esp32` 分支** 的语音容器并重启（改 `.env` 后 `bash scripts/redeploy_docker.sh`）。确认：

```text
http://<电脑局域网IP>:8765/health
```

2. 向软件要已绑定设备的 `device_code` / `device_secret`（Admin「加载设备」）。板子和电脑同一局域网，**不要用 `127.0.0.1`**。

3. ESP32 连：

```text
ws://<电脑局域网IP>:8765/ws/voice
```

4. 后端日志应出现：

```text
device MCP initialized device=<id>
device MCP tools discovered device=<id> tools=[..., self.chassis.go_forward, ...]
```

5. 对着车说「往前走一点」。日志：

```text
chassis MCP call device=<id> tool=self.chassis.go_forward duration=0.80 text=...
```

串口应看到 `type=mcp` `method=tools/call`，轮子动，约 0.8 秒后收到 `self.chassis.stop`。

说「停下」应立刻刹车。

---

## 4. 常见问题

| 现象 | 原因 |
|------|------|
| 没有 `MCP initialize` | `hello` 缺少 `features.mcp=true`，或未带 `device_code`/`device_secret`，或工厂验收会话 |
| `initialize` 有、没有 `tools/list` | 固件没回 initialize 的 result；等 2 秒应仍会 list。一直没有就查固件是否处理 `type=mcp` |
| `chassis tool unavailable` | `tools/list` 的名字和上表不一致 |
| 有 STT 轮子不动 | 口令没匹配，或工具列表还没到且排队失败；看是否出现 `chassis motion queued` |
| 一直冲不停车 | 固件 `stop` 没真正断电；后端会发 stop，串口确认有没有收到 |
| 网页 voice-demo 有括弧动作 | 那是说话演戏，**不是电机** |

电机不转先查固件 MCP 和驱动板；接口问题看 `src/shuxin/voice/api/ws_mcp_chassis.py`。
