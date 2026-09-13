# ESP32 小车 MCP 底盘控制对接

分支：`feature/voice-auth-gate`

## 本地改动文件

| 文件 | 状态 | 作用 |
| --- | --- | --- |
| `src/shuxin/voice/api/ws_session.py` | 已修改 | 增加 ESP32 MCP 握手、工具发现和基于 STT 文本的底盘指令下发。 |
| `tests/test_voice_auth_gate.py` | 已修改 | 增加 MCP 工具发现后下发前进命令的回归测试。 |
| `MCP_CHASSIS_HANDOFF.md` | 新增 | 本对接说明。 |

## 后端行为

1. ESP32 WebSocket `hello` 包含 `features.mcp=true` 时，后端依次发送 MCP `initialize` 和 `tools/list`。
2. 后端接收并缓存 ESP32 返回的工具名称。
3. STT 最终文本命中底盘口令后，后端直接下发设备 MCP 工具，不依赖 LLM 决定是否调用。
4. 方向动作会在指定时间后自动调用 `self.chassis.stop`；新的方向或停止口令会取消前一个定时停止任务。

## 语音与 MCP 工具映射

| 语音示例 | 设备 MCP 工具 |
| --- | --- |
| 前进、往前走、向前走、过来 | `self.chassis.go_forward` |
| 后退、往后、向后、倒车 | `self.chassis.go_back` |
| 左转、向左、往左 | `self.chassis.turn_left` |
| 右转、向右、往右 | `self.chassis.turn_right` |
| 停止、停车、别动、取消 | `self.chassis.stop` |

动作默认持续 1.5 秒；“一点、一下、稍微”持续 0.8 秒；阿拉伯数字秒数（如“前进 2 秒”）最大限制为 4 秒。

## MCP 报文

后端发给 ESP32 的工具调用格式：

```json
{
  "type": "mcp",
  "payload": {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "self.chassis.go_forward",
      "arguments": {}
    }
  }
}
```

ESP32 固件应在 `tools/list` 返回以下工具：

```text
self.chassis.go_forward
self.chassis.go_back
self.chassis.turn_left
self.chassis.turn_right
self.chassis.stop
```

## 验收步骤

1. 提交并部署上述改动，重启实际运行语音服务的后端容器。
2. ESP32 重连后，确认后端日志包含：

```text
device MCP tools discovered device=<device-id> tools=[...]
```

3. 对小车说“小车前进”。确认后端日志包含：

```text
chassis MCP call device=<device-id> tool=self.chassis.go_forward text=小车前进
```

4. ESP32 串口应收到 `type=mcp`、`method=tools/call`，随后电机前进并在约 1.5 秒后停止。

## 注意事项

- 当前 ESP32/TB6612 底盘走 MCP 工具链；不要同时使用 `apps/rk3566/scripts/drive.sh` 的 RK3566 直控底盘路径。
- 本地尚未完成自动化测试：当前 Windows 环境没有可执行的 Python 解释器，部署环境应运行：

```bash
python -m pytest -q tests/test_voice_auth_gate.py
```
