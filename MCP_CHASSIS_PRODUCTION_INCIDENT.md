# ESP32 小车 MCP 控制未下发：后端排障交接

## 结论摘要

2026-09-14 的实机日志表明，ESP32 已完成网络、设备认证和语音会话，ASR 也正确识别了“小车前进”“后退”；但车辆没有运动，且没有可见证据显示后端完成了 MCP 初始化、工具发现及 `tools/call` 下发。

当前不要优先排查 TB6612、电机供电或 GPIO。它们尚未进入本次故障的执行路径。请先确认线上 `wss://shuxinzzx.com.cn/ws/voice` 的实际部署版本及 MCP 会话条件。

## 实机信息

| 项目 | 值 |
| --- | --- |
| 固件版本 | `2.0.3`，编译于 `2026-09-14 09:34:10` |
| 板型 | `jc4827w543-tb6612` |
| 设备码 | `SX-000003` |
| 客户端 ID | `shuxin-core-c3-1.54-SX-000003` |
| WebSocket | `wss://shuxinzzx.com.cn/ws/voice` |
| 认证结果 | `hello state=ok`，已绑定用户 `o0GlJ3SpNJ17wQjAhPG3NzuEg-go` |
| 固件 MCP 能力 | `features.mcp=true`（固件实现固定发送） |
| 已注册底盘工具 | `self.chassis.go_forward`、`go_back`、`turn_left`、`turn_right`、`stop` |

固件出现的 `Using compile-time ShuXin identity fallback` 仅表示身份来自编译期配置而非 NVS；本次认证已成功，因此它不是 MCP 不下发的直接证据，也不是首要排查项。

## 复现证据（串口时间线）

```text
  551 ms  MCP: Add tool: self.chassis.go_forward
  551 ms  MCP: Add tool: self.chassis.go_back
  551 ms  MCP: Add tool: self.chassis.turn_left
  551 ms  MCP: Add tool: self.chassis.turn_right
  551 ms  MCP: Add tool: self.chassis.stop

19541 ms  WS: ShuXin hello device_code=SX-000003 ...
19711 ms  WS: Server hello state: ok
19711 ms  WS: Device ID: SX-000003
19711 ms  WS: Bound user ID: o0GlJ3SpNJ17wQjAhPG3NzuEg-go

22571 ms  ASR 最终文本：小车前进
26571 ms  收到普通 LLM/TTS 文本回复

43651 ms  ASR 最终文本：后退
47691 ms  收到普通 LLM/TTS 文本回复
```

在上述两个指令窗口中，车未运动。串口没有业务成功日志可直接证明后端是否发出 MCP 报文；因此后端容器日志是判定断点的唯一可靠依据。

## 协议预期

在 `hello state=ok` 后，线上服务应按以下顺序发包：

```text
后端 -> 设备  type=mcp, method=initialize
设备 -> 后端  JSON-RPC result（serverInfo）
后端 -> 设备  type=mcp, method=tools/list
设备 -> 后端  JSON-RPC result（tools，包含 self.chassis.go_forward 等）
用户说“小车前进”
后端 -> 设备  type=mcp, method=tools/call, name=self.chassis.go_forward
约 0.8 秒后
后端 -> 设备  type=mcp, method=tools/call, name=self.chassis.stop
```

## 本地后端代码的关键条件

当前仓库的 `src/shuxin/voice/api/ws_session.py` 在处理 `hello` 时只在下列条件均成立时启动 MCP：

```python
mcp_requested = isinstance(features, dict) and bool(features.get("mcp"))
mcp_ok = mcp_requested and self.hardware_session and not self.factory_acceptance
if mcp_ok:
    await self.mcp.start()
```

其中 `self.mcp.start()` 应立即发送 `initialize`。`hardware_session` 由 `device_code` 或 `device_secret` 是否存在决定；本次设备携带 `device_code=SX-000003`，并且以普通绑定会话成功认证，理论上应满足该条件。

`DeviceMcpBridge` 的后续行为为：

- 收到 `initialize` 返回值后，记录：`device MCP initialized device=SX-000003`；
- 发送 `tools/list`；
- 收到工具列表后，记录：`device MCP tools discovered ...`；
- 命中口令后，记录：`chassis MCP call device=SX-000003 tool=self.chassis.go_forward ...`。

相关实现：

- `src/shuxin/voice/api/ws_session.py`：`hello` 中的 `mcp_ok` 判定与 `self.mcp.start()`。
- `src/shuxin/voice/api/ws_mcp_chassis.py`：MCP 初始化、工具发现与底盘命令分派。
- `tests/test_esp32_mcp_chassis.py`：底盘指令解析及 MCP 调用行为的覆盖测试。

## 优先假设与可证伪检查

| 优先级 | 假设 | 预测/检查 |
| --- | --- | --- |
| 1 | 生产域名运行的是旧镜像、错误分支或未重新部署的容器 | 日志没有 `device MCP initialized`，且运行容器内文件/镜像不含 `DeviceMcpBridge.start()` 调用路径。 |
| 2 | 线上 `hello` 中 `features.mcp` 没被解析为真，或会话被标记为 factory acceptance | 在 `hello` 处理处打印 `features`、`mcp_requested`、`hardware_session`、`factory_acceptance`、`mcp_ok`，将看到至少一项不符合预期。 |
| 3 | `initialize` 已发出但发送路径/反向代理丢弃 `type=mcp` 文本帧 | 后端有“发送 initialize”的日志，但设备无对应响应；抓取 WebSocket 帧可确认该帧是否离开应用。 |

## 后端同事执行清单

1. 在问题复现时段查询 voice 服务日志，按设备码过滤：

   ```bash
   docker compose logs --since 15m <voice服务名> | grep 'SX-000003\|MCP\|chassis'
   ```

2. 核对是否出现以下日志，依此定位：

   ```text
   device MCP initialized device=SX-000003
   device MCP tools discovered device=SX-000003 tools=[...]
   chassis MCP call device=SX-000003 tool=self.chassis.go_forward ...
   ```

3. 若第一行缺失：确认线上容器的 Git SHA/镜像标签确实包含本仓库当前的 `ws_session.py` 与 `ws_mcp_chassis.py`；不要只核对宿主机工作区分支。

4. 若线上代码已正确部署，临时增加一条带唯一前缀的最小日志（例如 `[DEBUG-mcp-sx000003]`），记录 `features`、`mcp_requested`、`hardware_session`、`factory_acceptance`、`mcp_ok` 及 `initialize` 的发送结果。一次复现后删除该日志。

5. 若已发送 `initialize` 却收不到结果，抓取该单一 WebSocket 会话的文本帧，确认反向代理/WebSocket 中间件没有过滤 `type=mcp`。

## 验收标准

对 `SX-000003` 重启并连接后，必须依序观察到：

```text
device MCP initialized device=SX-000003
device MCP tools discovered device=SX-000003 tools=[..., self.chassis.go_forward, ...]
chassis MCP call device=SX-000003 tool=self.chassis.go_forward duration=0.80 text=小车前进
chassis MCP call device=SX-000003 tool=self.chassis.stop ...
```

同时车辆应前进约 0.8 秒后自动停止；“后退”“左转”“右转”“停止”均应按同一链路验证。
