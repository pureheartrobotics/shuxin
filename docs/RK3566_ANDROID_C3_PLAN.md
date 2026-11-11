# RK3566 量产方案：Android 上位机 + ESP32-C3 电机下位机

状态：最终方案（2026-09-15）  
输入：硬件评审 `hardware_log/rk3566_android_motor_review_2026-09-14.md`  
适用：KICKPI K11C（RK3566）带屏语音车，TB6612 双电机

**板上操作系统是 Android，量产客户端是 APK，不是 Linux，也不是 Python。**  
`feature/rk3566` 里那套 Debian + Python + `drive.sh` 是第一版误把 K11C 当成 Linux 板写的，本文作废那条路径，不作为交付物。

---

## 1. 结论

量产形态固定为：

```text
舒心云端 Voice BFF
  │ 现网 /ws/voice（JSON + 裸 Opus）
  │ 鉴权、STT、陪伴 LLM、TTS、额度、工厂验收
  │ 口令命中后下发结构化开车命令（MCP tools/call）
  ▼
RK3566 K11C Android App
  │ UI / 触摸 / 绑定 / 录音播放 / Opus / WebSocket / MCP 执行
  │ 不生成 PWM，不直连电机电源
  │ 3.3 V TTL UART（K11C V1.2 UART7；V1.1 须电平转换）
  ▼
ESP32-C3 电机下位机
  │ UART 校验、PWM、TB6612、心跳超时、看门狗
  │ 不上网、不跑语音、不存云厂商密钥
  ▼
TB6612 → 左电机 / 右电机
```

三条硬规则：

1. **云端是唯一开车语义源。** 口令在服务端解析；Android 只执行，不再用 STT 文本正则作为主路径。
2. **C3 是唯一电机主人。** 失联 600 ms 必须停车；Android 崩溃、杀进程、断电都靠这一条。
3. **密钥不上板。** ASR / LLM / TTS Key 只在云端；板上只有 `device_code` / `device_secret`。

### 1.1 K11C 官方资料如何落到这辆车

核对来源：[快速使用](https://doc.kickpi.cn/Products/Beginner-Guide/KICKPI-K11C/)、[硬件介绍](https://doc.kickpi.cn/Products/Introduction/KICKPI-K11C/)、[引脚电压](https://doc.kickpi.cn/Products/Peripherals-and-Interfaces/Pinout/)、[UART](https://doc.kickpi.cn/Products/Peripherals-and-Interfaces/UART/)、[Android SDK](https://doc.kickpi.cn/Products/SDK-Compilation/RK356x-RK3588/Android_SDK/)。

| 官方事实 | 对本车的含义 |
|---|---|
| eMMC 出厂预装 **Android**；网盘镜像含 Android 13 / Debian11 / Ubuntu20.04 | 量产烧 **Android**。Linux 镜像只给实验室，不进车 |
| Android **不能**从 TF 卡启动 | 量产系统必须写进 eMMC；TF 只能救急 Linux |
| Android 14 SDK **仍在维护**，且明确适配 K11C（`BoardConfig-rk3566-kickpi-k11c.mk`） | 长期改设备树 / 串口权限走 Android 14 SDK；网盘里的 Android 13 可作首版，改内核权限时升 14 |
| 扩展脚：GPIO×19、**UART×3**、**PWM×1**、ADC×1、I2C×1、I2S×1 | 双电机至少要 2 路 PWM + 方向脚，板上 PWM 不够，**必须 C3** |
| DEBUG 串口波特率 **1.5 Mbps**，专用于控制台 | **禁止**拿 DEBUG 口接 C3；电机走扩展 UART |
| V1.2 把扩展脚电源域改成 **3.3 V**；V1.1 不同 | 优先 V1.2 直连 C3。V1.1 的 UART7 按硬件评审按 1.8 V 处理，必须电平转换 |
| 板载麦克风 + 喇叭；耳机口 **仅输出** | 语音走板载麦/喇叭，Android `AudioRecord`/`AudioTrack`。不要用耳机当上车扬声器方案 |
| 显示：官方 **7″ LVDS 1024×600**（KickPi 开发板专用屏） | 刷 **V1.2 `multi-lcd`** 镜像（自动识别 MIPI/LVDS）。不要刷 `edp`。断电再插拔 LVDS |
| V1.2 扩展脚 **3.3 V** | UART7 Pin15/17 **直连** ESP32-C3，不要电平转换 |
| 供电 DC **12 V / ≥1.5 A** | 这只够 SoC+屏。电机 VM **独立电源**，共地不共 12 V 小电流口 |
| Wi-Fi/BT：VS6621SR80；千兆网；USB ADB | 量产连 `wss://shuxinzzx.com.cn/ws/voice`；调试用 ADB，不必 SSH |
| NPU 约 1 TOPS | 可做小模型，**不跑**陪伴大模型 |

本车已锁定：**K11C V1.2** + 官方 7″ LVDS。刷机文件：

```text
镜像：F:\shuxin\Android13.0\K11C_V1.2\update-rk3566-kickpi-k11c-v12-android-multi-lcd-2026073011.img
工具：F:\shuxin\RKDevTool_v3.30_for_window\RKDevTool_v3.30_for_window\RKDevTool.exe
```

接线：Wiki [引脚电压图 · K11C](https://doc.kickpi.cn/Products/Peripherals-and-Interfaces/Pinout/#kickpi-k11c)。**UART7 Pin15 RX / Pin17 TX / GND**，3.3 V 直连 C3。Pin25/27 是 DEBUG，禁止接电机。网盘 `RK3566-K11C` 只有系统镜像。

---

## 2. 第一版作废什么、量产保留什么

K11C 出厂镜像是 Android。第一版按 Linux 写客户端，所以对不上硬件，整段作废：

| 第一版 | 量产 |
|---|---|
| Python / pip / venv | Kotlin/Java APK + NDK |
| `arecord` / `aplay` | `AudioRecord` / `AudioTrack` |
| `drive.sh` 进程控电机 | Android `MotorLink` 常驻 UART |
| 环境变量里的 `device_secret` | Android Keystore |
| 板端 STT 正则开车 | 云端 MCP，Android 只执行 |
| RK3566 GPIO / PWM | 禁止；电机只在 C3 |

从云端协议里**只复用消息语义**，不复用 Python 代码：`/ws/voice`、hello 鉴权、Opus 16 kHz 上 / 24 kHz 下、口令表、MCP 工具名。网页 `/voice-demo` 仍然只聊天，不开车。Android 可保留 `mock` 构建，方便没插 C3 时联调 UI。

---

## 3. 开车命令：只走一条通道

### 3.1 主路径（量产）

与现网 ESP32 MCP 相同，只是执行端换成 Android：

```text
hello（features.mcp=true）
  → MCP initialize → tools/list
  → 用户说话 → 云端 STT
  → 命中口令 → tools/call self.chassis.*
  → Android 转 UART SET_MOTOR / STOP
  → duration 到了云端再 tools/call stop
  → C3 同时用 duration_ms 和心跳超时兜底
```

`hello` 示例：

```json
{
  "type": "hello",
  "device_code": "<device_id>",
  "device_secret": "<device_secret>",
  "client_id": "rk3566-k11c",
  "features": { "mcp": true },
  "audio_params": {
    "format": "opus",
    "sample_rate": 16000,
    "channels": 1,
    "frame_duration": 60
  }
}
```

工具名（Android `tools/list` 必须返回）：

```text
self.chassis.go_forward
self.chassis.go_back
self.chassis.turn_left
self.chassis.turn_right
self.chassis.stop
```

云端时长（Android 原样传给 C3，**不要再套一层 4 秒**）：

| 口令 | 默认 duration | 速度 |
|---|---|---|
| 前进 / 后退 / 左转 / 右转 | 1.5 s | 0.55 |
| 「一点 / 一下 / 稍微」 | 0.8 s | 0.55 |
| 「快」 / 「慢」 | 同上时长 | 0.85 / 0.35 |
| 「N 秒」（最长 4 s） | min(N, 4) | 同上 |
| 停 / 停下 / 别动 | 立刻 stop | 0 |

`spin`（转一圈 / 掉头）：默认原地右旋，时长至少 1.2 s，上限 4 s。左右轮极性只允许在 C3 板级配置里反相，Android 和云端不交换正负号。

### 3.2 明确不做

- 不新增第二套 `type: motion` 作为并行开车源。若 Android 实现 MCP 成本过高，可增加 **MCP 的扁平别名**（同一条服务端命令、同一个 `command_id`），禁止两套解析同时生效。
- Android **不得**再对 STT 文本做主路径正则。本地解析若以后要做低延迟优化，必须经过与云端相同的安全层，且默认关闭。
- LLM 回复里的括弧动作只给屏幕/表情，**禁止**映射成电机。

### 3.3 口令安全（云端实现）

以下句子不得开车，停优先：

- 否定：不要前进、不要后退、别往左、不能右转
- 疑问：可以前进吗、要不要倒车
- 转述：他说让我前进、刚才往左走了
- 同句既有停又有走：只执行 stop
- STT 低置信或重复 final：去重，不连发

「不要后退」在第一版会误触发后退，属 P0，由云端修复后再给真车。

---

## 4. Android 上位机

### 4.1 职责

- 绑定与身份：Keystore 加密保存 `device_secret`；未绑定进入绑定页，禁止空密钥重连。
- WebSocket：现网 JSON 文本 + 每消息一帧裸 Opus。
- 音频：`AudioRecord` → 16 kHz / 60 ms → Opus 立刻上行；下行 24 kHz Opus 边收边解边播。禁止整段录完再传、整段收齐再播。
- MCP：作为执行端，把 `tools/call` 变成 UART。
- UART：常驻 `MotorLink`，200 ms 心跳，STOP 抢占，急停按钮始终可点。
- 生命周期：前台 Service 维持音频 / WS / 串口；UI 卡顿不得卡住心跳线程。
- 工厂验收：处理 `factory_verify`，10 秒内回 `factory_verify_ack`。

生产构建禁止默认 `demo-device-001`。日志脱敏，不得打印完整 secret。

### 4.2 状态机

```text
STARTING → UNBOUND → IDLE → CONNECTING
                 ↘ LISTENING ⇄ SPEAKING
                 ↘ MOVING
                 ↘ FAULT / ERROR
```

进入 `ERROR`、用户退出、WS 断开、串口异常时调用 `MotorLink.emergencyStop()`。最终安全仍以 C3 600 ms 超时为准。

UART 未就绪、C3 故障未清除时，禁止下发 SET_MOTOR。

### 4.3 建议模块

```text
android-app/
├─ ui/                  界面、绑定、急停、状态
├─ binding/             身份与 Keystore
├─ network/             WebSocket 与重连
├─ audio/               AudioRecord / AudioTrack / Opus
├─ conversation/        会话状态机
├─ mcp/                 initialize / tools/list / tools/call
├─ motor/
│  ├─ MotorLink         UART 长连接与心跳
│  ├─ MotorFrameCodec   帧与 CRC
│  ├─ MotorController   STOP 抢占
│  └─ MotorStatus
└─ native/
   ├─ serial_port.cpp
   └─ opus_bridge.cpp
```

WebSocket ping（约 20 s）与电机心跳（200 ms）必须分开，前者不能代替后者。

ACK 只表示 C3 接受了命令，不表示轮子已经转。实际状态看 C3 的 STATUS / FAULT。

---

## 5. ESP32-C3 下位机

### 5.1 职责（只做这些）

- UART 收发、CRC / 长度 / 版本 / 序号校验
- 左右轮 PWM + TB6612 方向 / STBY
- 动作限时（`duration_ms`，最大 4000）
- 600 ms 无合法帧 → 安全停车
- 50 ms 短刹车、换向死区
- 状态 / 故障 / 复位原因回传
- 任务看门狗

不做：Wi-Fi、BLE、ASR、TTS、显示、绑定、云端。首版关掉无线。

复位后**不得**从 NVS 恢复上一次运动。必须重新等到合法心跳才允许 SET_MOTOR。

### 5.2 PWM

| 通道 | 用途 | 首版 |
|---|---|---|
| PWM0 | TB6612 PWMA 左轮 | 使用，约 10 kHz / ≥10 bit |
| PWM1 | TB6612 PWMB 右轮 | 使用 |
| PWM2 / PWM3 | 舵机或灯 | 预留，禁止并接到电机 PWM |

GPIO 一律集中在 `board_config.h`，原理图确认前全部 `GPIO_NUM_NC`，不得按猜测接线生产。

STBY 必须硬件下拉。上电顺序：方向 GPIO 与 PWM=0 → 再允许拉高 STBY。

### 5.3 左右轮映射

速度范围 `-100..100`。Android 把云端 speed（0.35 / 0.55 / 0.85）线性映射到该范围。

| 动作 | 左 | 右 |
|---|---:|---:|
| forward | +s | +s |
| backward | -s | -s |
| left | -s | +s |
| right | +s | -s |
| spin（默认右旋） | +s | -s |
| stop | 0 | 0 |

---

## 6. UART 协议

### 6.1 物理层

```text
115200 8N1 无流控
K11C V1.2 UART7：3.3 V TTL，可直连 C3
K11C V1.1 UART7：1.8 V，必须双向电平转换（推挽 UART，不是 I2C 开漏）
```

首选 K11C UART7：Pin 17 TX → C3 RX，Pin 15 RX → C3 TX，GND 共地。UART2 调试口不要占用。PCB 版本未确认前禁止焊接信号线。

只连 TX / RX / GND。电机 VM 不得从 K11C 或 C3 的 3.3 V / GPIO 取电。

### 6.2 帧（小端）

| 字段 | 长度 | 说明 |
|---|---:|---|
| Header | 2 | `AA 55` |
| Version | 1 | `01` |
| Type | 1 | 见下表 |
| Length | 1 | 负载 0..32 |
| Sequence | 1 | 0..255 回绕 |
| Payload | 0..32 | |
| CRC16 | 2 | 覆盖 Version→Payload |

CRC16-CCITT-FALSE：`poly=0x1021 init=0xFFFF refin=false refout=false xorout=0x0000`

| Type | 名称 | 方向 |
|---:|---|---|
| `0x01` | HEARTBEAT | RK → C3，每 200 ms |
| `0x10` | SET_MOTOR | RK → C3 |
| `0x11` | STOP | RK → C3，最高优先级，不排队 |
| `0x20` | QUERY_STATUS | RK → C3 |
| `0x80` | ACK | C3 → RK |
| `0x81` | STATUS | C3 → RK，约 500 ms |
| `0xE0` | FAULT | C3 → RK |

SET_MOTOR 负载：`int8 left_speed`、`int8 right_speed`、`uint16 duration_ms`（0..4000）。非法速度、错误 CRC、截断帧、未知类型一律不驱动电机。

Android 与 C3 使用**同一组 CRC 测试向量**（单独文件交付，见第 11 节）。

---

## 7. 安全时序

```text
C3 上电
  → STBY 硬件下拉保持低
  → GPIO / PWM=0
  → UART + 看门狗
  → 连续合法心跳后才接受 SET_MOTOR

运动中
  → Android 200 ms 心跳
  → C3 校验 CRC 与截止时间
  → 600 ms 无合法帧，或 duration 到期，或收到 STOP
  → 短刹车 → PWM=0 → STBY=0 → FAULT（若为失联）
```

STOP 在任何状态下立即执行。故障停车不等 Android ACK。

电源树：

```text
电池/外部电源
├─ 稳压 → K11C
├─ 稳压 → ESP32-C3
└─ 电机额定电压 → TB6612 VM

三处逻辑地必须共地；大电流回路不得经过 SoC 数字地细线
```

首次测试：限流电源、车轮架空。堵转电流超出 TB6612 则换驱动器，不用软件限速掩盖。

---

## 8. 音频与现网协议（Android 必须实现）

| 方向 | 格式 |
|---|---|
| 上行 | 裸 Opus，16 kHz mono，60 ms，每 WS binary 一帧 |
| 下行 | 裸 Opus，24 kHz mono，60 ms |

另需：`listen` / `abort` / `ping`、流式 `agent/delta`、分句 `tts/sentence_*`（括弧给 UI，TTS 不读）、`factory_verify`。完整字段见 [`VOICE_HARDWARE_WS_PROTOCOL.md`](VOICE_HARDWARE_WS_PROTOCOL.md)、MCP 见 [`../MCP_CHASSIS_HANDOFF.md`](../MCP_CHASSIS_HANDOFF.md)。

录音权限拒绝、设备打不开串口，都要进入明确 `FAULT`，不得静默重连空转。

---

## 9. 分工

| 角色 | 交付 | 不负责 |
|---|---|---|
| 云端 / 后端 | `/ws/voice`、鉴权、口令安全、MCP、联调环境、否定句修复 | GPIO、APK、PWM |
| Android | APK、流式音频、Keystore、MCP→UART、急停 UI | 实时 PWM、云厂商 Key |
| ESP32 | C3 固件、协议、TB6612、失联停车 | 上网、语音、绑定 |
| 硬件 | K11C 版本与电平、接线、电源树、电流核算、EMC | 云端协议 |
| 测试 | CRC 向量、台架故障注入、整车与长稳 | — |

`apps/rk3566/` 的 Python 客户端不进入量产排期，不要求硬件在 Linux 镜像上联调。需要对照协议时，以后端现网和本文为准。

---

## 10. 阶段

**P0 — 不上车落地，可并行写协议代码**

1. ~~确认 K11C V1.1 / V1.2~~ **已锁定 V1.2**；屏为官方 7″ LVDS，镜像用 `v12-android-multi-lcd`。
2. 确认 C3 四路 PWM 板型号与原理图。
3. 确认电机额定 / 堵转电流与 TB6612 匹配。
4. 真机确认 UART：Android 13，屏 1024×600。`/dev/ttyS7` 存在且 `crw-rw-rw-`、SELinux label `serial_device`。**当前 `getenforce=Permissive`，关 SELinux 不算量产方案**，enforcing 下普通 APK 能否打开串口仍待测。
5. C3：上电 STBY 低 + 600 ms 失联停车 + CRC + STOP 抢占。
6. 云端：否定 / 疑问 / 转述不误触发。

**P1 — 能对话、能受控短动**

1. Android WS + 实时 Opus 上下行。**`android-app/` 已有 mock 构建**（Keystore 存密钥、MCP 回工具列表、电机走模拟、急停发 `abort`）。未插 C3 时不要打开真实串口。
2. 绑定与 Keystore。
3. MCP 接入，映射 UART。
4. C3 状态回传与 App 展示。
5. 屏幕急停。

**P2 — 优化**

斜坡、编码器、电流/欠压、舵机灯、OTA、工厂台。

顺序：C3 安全停车 → Android 手动前后左右停 → 再接语音。电机安全未过台架，不做整车语音联调。

---

## 11. 验收

台架（C3 单独）：

- 未接 RK 上电，STBY 保持低
- 随机 UART 字节不产生 PWM
- 停心跳后 600 ms 内停车
- duration 到期由 C3 自停
- 看门狗复位不误动作

整车：

- 架空确认方向后才能落地
- 前进 / 后退 / 左转 / 右转 / 停止各 100 次，无方向错误
- 「不要前进」「不要后退」不开车
- 说「停」打断当前动作
- 拔 UART、杀 App、断网、重启 RK3566，车均不持续跑
- SELinux enforcing 下 8 小时：心跳不断、音频队列不涨、串口线程不退
- 生产日志无完整 secret

判定量产方案就绪，须同时满足：

- APK 不依赖 Python / Bash / `arecord` / `aplay`
- 音频按帧实时上下行
- Android↔C3 固定 CRC 协议
- C3 独立 PWM 与 STBY
- RK 失联 600 ms 内停车
- 只有一条开车语义通道（云端 MCP）

---

## 12. 硬件仍须提供（无这些不定线束、不写死 GPIO）

1. ~~K11C PCB 丝印~~ **V1.2**；屏 **7″ LVDS**，刷 `multi-lcd` 不要刷 `edp`
2. ESP32-C3 四路 PWM 板商品型号、原理图或正反面清晰照片
3. TB6612 模块照片或规格
4. 电机铭牌：额定电压、堵转电流
5. 真机 `adb`：**Android 13**，`wm size=1024x600`，`getenforce=Permissive`。`/dev/ttyS7` 世界可读写（`u:object_r:serial_device:s0`）。内核与 enforcing 下 APK 开串口仍待补。
6. UART7 节点已见到 `/dev/ttyS7`；Pin 17 TX / Pin 15 RX / GND 待 C3 接线后 loopback 验证。UART9 暂不需要。

未齐之前：可并行写 Android 协议层、C3 通用协议、CRC 测试向量。不可定最终 GPIO，不可做量产线束。

---

## 13. 仓库与文档

| 路径 | 用途 |
|---|---|
| 本文 `docs/RK3566_ANDROID_C3_PLAN.md` | 量产合同（Android + C3） |
| `android-app/` | K11C 量产 APK（当前 mock 电机） |
| `protocol/motor_test_vectors.json` | UART CRC 向量（Android/C3 共用） |
| `MCP_CHASSIS_HANDOFF.md` | 云端 MCP 口令与工具名 |
| `docs/VOICE_HARDWARE_WS_PROTOCOL.md` | WS 与音频字段 |

ESP32-S3 样车继续走 Wi-Fi MCP 直连云端，与本方案并行，互不替换。量产带屏车只执行本文。
