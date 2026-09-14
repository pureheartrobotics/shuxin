# RK3566 Android 上位机与 ESP32-C3 四路 PWM 下位机 TB6612 双电机开发方案

## 1 项目目标

本方案用于把现有 ESP32-S3 语音小车工程迁移为 RK3566 Android 上位机和 ESP32-C3 电机下位机架构。

- RK3566 KICKPI K11C 运行 Android 应用，负责界面、触摸、录音、播放、Opus、WebSocket、设备绑定、业务状态机和电机命令生成。
- ESP32-C3 四路 PWM 开发板运行精简 ESP-IDF 固件，负责串口通信、PWM、GPIO、TB6612 双路电机驱动和安全停车。
- RK3566 与 ESP32-C3 使用 3.3 V TTL UART 通信。
- TB6612 驱动两台直流电机，左右电机可独立控制方向和速度。

> TB6612 只有 A、B 两个电机通道，正常使用 2 路 PWM。ESP32-C3 开发板的另外 2 路 PWM 作为舵机、灯光或后续扩展预留，不应并接到 TB6612 的 PWMA/PWMB。

## 2 总体架构

```text
舒心服务端
  │ WebSocket + JSON + Opus
  ▼
RK3566 K11C Android App
  ├─ UI 与触摸交互
  ├─ 设备绑定和身份存储
  ├─ AudioRecord / AudioTrack
  ├─ Opus 编解码
  ├─ WebSocket 客户端
  ├─ 对话状态机和 MCP 工具
  └─ UART 电机链路与心跳
             │ 3.3 V TTL UART
             ▼
ESP32-C3 四路 PWM 开发板
  ├─ UART 帧解析与 CRC 校验
  ├─ 左右轮速度换算
  ├─ 2 路 PWM + 5 路方向/使能 GPIO
  ├─ 心跳超时与命令限时停车
  └─ 硬件看门狗
             │
             ▼
TB6612 双路电机驱动
  ├─ A 通道 → 左电机
  └─ B 通道 → 右电机
```

这种划分将 Android/Linux 的非实时性与电机安全控制隔离。即使 Android 应用崩溃、串口断开或 RK3566 重启，ESP32-C3 也能独立执行超时停车。

## 3 现有 ESP32 工程迁移范围

现有工程路径：

```text
E:\Users\24303\Desktop\screen\SHUXIN-esp32-2.0.3-button-ble
```

当前活动配置是 ESP32-S3 和 `JC4827W543_TB6612`。已有功能包括舒心设备绑定、WebSocket、Opus 音频、触摸对话、LCD 状态显示以及 TB6612 小车控制。

| 原 ESP32 功能 | 新位置 | 迁移方式 |
|---|---|---|
| `claim_code`、`device_code`、`device_secret` | Android App | 使用加密存储重新实现 |
| WebSocket 协议 | Android App | 保留消息语义，使用 Android 网络库重写 |
| 录音和播放 | Android App | 改用 `AudioRecord` 和 `AudioTrack` |
| Opus 编解码 | Android App | 使用 NDK `libopus` 或可验证兼容的 Android 实现 |
| ESP LCD 和 LVGL | Android App | 改为 Android 原生界面 |
| 触摸触发对话 | Android App | Android 点击或触摸事件 |
| MCP `self.chassis.*` | Android App | MCP 调用转换成左右轮 UART 命令 |
| `Tb6612Chassis` | ESP32-C3 | 保留方向、PWM、短刹车和超时保护思路 |
| ESP NVS | 两端分别实现 | Android 加密存储；C3 使用 NVS 保存配置 |
| FreeRTOS 电机任务 | ESP32-C3 | 保留 ESP-IDF/FreeRTOS 实现 |

ESP-IDF 的 `gpio_set_level`、LEDC、FreeRTOS EventGroup、ESP LCD、I2S 和 NVS 代码不能直接编译进 Android APK。业务规则可以参考或抽取，硬件适配必须重写。

## 4 Android 上位机开发方案

### 4.1 推荐技术栈

- 语言：Kotlin。
- 最低 Android 版本：以 K11C 实际镜像版本为准。
- UI：Jetpack Compose；若厂商 SDK 较旧，可使用传统 XML View。
- 并发：Kotlin Coroutines、Flow。
- WebSocket：OkHttp WebSocket。
- JSON：Kotlin Serialization 或 Moshi。
- 音频：`AudioRecord`、`AudioTrack`。
- Opus：优先通过 Android NDK 封装 `libopus`，明确控制帧长和裸 Opus 包格式。
- 本地存储：普通配置使用 DataStore；设备密钥使用 Android Keystore 加密后保存。
- 串口：优先使用厂商串口 API；否则通过 JNI/NDK 打开 `/dev/tty*`。
- 日志：统一日志模块，生产版本不得输出 `device_secret` 或完整令牌。

### 4.2 建议工程结构

```text
app/src/main/java/com/shuxin/robot/
├─ app/
│  ├─ MainActivity.kt
│  └─ ShuxinApplication.kt
├─ ui/
│  ├─ MainScreen.kt
│  ├─ BindingScreen.kt
│  └─ RobotStateViewModel.kt
├─ binding/
│  ├─ DeviceIdentity.kt
│  ├─ IdentityRepository.kt
│  └─ SecureIdentityStore.kt
├─ network/
│  ├─ ShuxinWebSocket.kt
│  ├─ ProtocolMessage.kt
│  └─ ReconnectPolicy.kt
├─ audio/
│  ├─ AudioRecorder.kt
│  ├─ AudioPlayer.kt
│  ├─ OpusEncoder.kt
│  └─ OpusDecoder.kt
├─ conversation/
│  ├─ ConversationController.kt
│  └─ DeviceState.kt
├─ motor/
│  ├─ MotorCommand.kt
│  ├─ MotorLink.kt
│  ├─ MotorFrameCodec.kt
│  └─ MotorStatus.kt
├─ mcp/
│  └─ ChassisTools.kt
└─ diagnostics/
   └─ DiagnosticsRepository.kt

app/src/main/cpp/
├─ CMakeLists.txt
├─ opus_bridge.cpp
└─ serial_port.cpp
```

### 4.3 Android 核心状态机

建议采用单一状态源，避免 UI、音频和网络各自维护互相冲突的状态。

```text
STARTING
  → UNBOUND      未绑定，显示 claim_code 或二维码
  → IDLE         已绑定且网络可用
  → CONNECTING   正在建立 WebSocket
  → LISTENING    采集并上传音频
  → SPEAKING     接收并播放服务端音频
  → ERROR        可恢复故障
```

状态切换时统一控制录音、播放、按钮可用性、动画和 WebSocket。进入 `ERROR` 或应用退出时，应调用 `MotorLink.emergencyStop()`。

### 4.4 设备绑定和安全存储

设备身份建议包含：

```text
claim_code
device_code
device_secret
client_id
qr_payload
```

要求：

- 首次启动从预置配置、二维码或绑定接口获得身份。
- `device_secret` 不硬编码在公开源码或普通资源文件中。
- 使用 Android Keystore 生成不可导出的 AES 密钥，再加密保存敏感身份。
- 日志只显示脱敏后的设备编号。
- 恢复出厂设置时清除身份、令牌和缓存会话。

### 4.5 WebSocket 与音频

现有协议基线为裸 Opus 音频包：

- 上行：16 kHz、单声道、60 ms 每帧。
- WebSocket 每个二进制消息承载一个 Opus 包。
- 不在二进制消息外再封装 Ogg、WAV 或 MP3。
- 文本消息继续使用 JSON，保留 hello、会话和 MCP 相关语义。

Android 侧音频链路：

```text
麦克风
 → AudioRecord PCM16
 → 必要时重采样到 16 kHz
 → 每 960 个采样点组成 60 ms 单声道帧
 → Opus 编码
 → WebSocket 二进制消息

WebSocket 二进制消息
 → Opus 解码
 → 必要时重采样到实际输出采样率
 → AudioTrack 播放
```

需要通过服务端联调确认下行采样率、Opus application 模式和服务端 hello 参数。录音线程、编码线程和发送线程之间使用有界队列；网络阻塞时丢弃过期实时音频，不能无限堆积。

### 4.6 MCP 小车工具映射

Android App 保留以下工具语义：

| MCP 工具 | left_speed | right_speed | 默认持续时间 |
|---|---:|---:|---:|
| `self.chassis.go_forward` | +70 | +70 | 4000 ms |
| `self.chassis.go_back` | -70 | -70 | 4000 ms |
| `self.chassis.turn_left` | -70 | +70 | 1500 ms |
| `self.chassis.turn_right` | +70 | -70 | 1500 ms |
| `self.chassis.stop` | 0 | 0 | 0 ms |

所有速度在发送前限制到 `-100..100`。停止命令优先级最高，不得排在普通动作之后等待。串口未连接、下位机故障或心跳失败时，MCP 返回明确失败状态，不能报告已执行。

### 4.7 UART 接入与 Android 权限

首先在 K11C 上检查：

```sh
adb shell getprop ro.build.version.release
adb shell getprop ro.build.type
adb shell getenforce
adb shell 'ls -lZ /dev/ttyS* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null'
adb shell 'cat /proc/tty/driver/serial 2>/dev/null'
```

根据结果选择：

1. 厂商已有串口 SDK：普通 APK 调用 SDK。
2. 节点允许应用访问：JNI/NDK 直接打开串口。
3. 返回 `Permission denied`：做成平台签名系统应用，并修改 `ueventd.rc` 和 SELinux 策略。
4. 没有对应设备节点：在 RK3566 Android 设备树中启用 UART 并配置 pinmux。

串口初始参数：

```text
115200 bit/s
8 数据位
无校验
1 停止位
无硬件流控
```

Android 的 USB Host API 只适用于 USB 转串口设备；板载 `/dev/ttyS*` 不能用 USB Host API 代替。

### 4.8 Android 后台运行

小车运行期间建议使用前台服务维持音频、WebSocket 和串口链路，并显示持续通知。若设备作为专用终端使用，建议将应用集成为系统应用或设备所有者，并按产品需求配置开机启动、锁屏策略和电池优化白名单。

收到以下事件时必须尝试发送停止帧：

- 用户点击停止。
- WebSocket 会话结束。
- 串口链路发生异常。
- Activity 或前台服务进入终止流程。
- App 捕获到不可恢复错误。

最终安全仍由 ESP32-C3 的 600 ms 心跳超时保证，不能只依赖 Android 生命周期回调。

## 5 ESP32-C3 四路 PWM 下位机方案

### 5.1 职责边界

ESP32-C3 只负责：

- UART 收发和数据帧校验。
- 两台电机的方向和 PWM 调速。
- 心跳监测、动作限时和安全停车。
- 状态与故障回传。
- 硬件看门狗。

下位机不负责 WebSocket、语音、显示、设备绑定、Wi-Fi 或 BLE。关闭不需要的无线功能可以减少功耗和干扰。

### 5.2 PWM 分配

| PWM 通道 | 用途 | 首版状态 |
|---|---|---|
| PWM0 | TB6612 `PWMA`，左电机速度 | 使用 |
| PWM1 | TB6612 `PWMB`，右电机速度 | 使用 |
| PWM2 | 舵机、灯光或其他扩展 | 预留 |
| PWM3 | 舵机、灯光或其他扩展 | 预留 |

推荐电机 PWM 频率为 10 kHz，分辨率至少 10 bit。若具体 ESP32-C3 板载 PWM 驱动电路限制频率，应以该开发板原理图和资料为准。

### 5.3 GPIO 集中配置

具体 GPIO 必须根据 ESP32-C3 四路 PWM 开发板的型号、原理图、板载外设和启动绑带脚确认。首版代码应集中定义，不在业务代码里散落数字：

```c
// board_config.h：以下值必须在确认开发板型号后填写
#define UART_TX_GPIO       GPIO_NUM_NC
#define UART_RX_GPIO       GPIO_NUM_NC

#define MOTOR_PWMA_GPIO    GPIO_NUM_NC
#define MOTOR_AIN1_GPIO    GPIO_NUM_NC
#define MOTOR_AIN2_GPIO    GPIO_NUM_NC

#define MOTOR_PWMB_GPIO    GPIO_NUM_NC
#define MOTOR_BIN1_GPIO    GPIO_NUM_NC
#define MOTOR_BIN2_GPIO    GPIO_NUM_NC
#define MOTOR_STBY_GPIO    GPIO_NUM_NC

#define AUX_PWM2_GPIO      GPIO_NUM_NC
#define AUX_PWM3_GPIO      GPIO_NUM_NC
```

选脚要求：

- 避免与板载 USB、Flash、LED、按键或晶振冲突。
- 谨慎使用启动绑带脚，确保外部上下拉不会影响启动。
- `STBY` 增加硬件下拉，使 C3 未初始化、复位或掉电时 TB6612 默认关闭。
- 上电后先配置方向 GPIO 和 PWM 占空比为零，最后才允许拉高 `STBY`。

### 5.4 ESP-IDF 模块结构

```text
esp32c3_motor_controller/
├─ CMakeLists.txt
├─ sdkconfig.defaults
└─ main/
   ├─ CMakeLists.txt
   ├─ app_main.c
   ├─ board_config.h
   ├─ uart_protocol.c
   ├─ uart_protocol.h
   ├─ motor_driver.c
   ├─ motor_driver.h
   ├─ safety_monitor.c
   ├─ safety_monitor.h
   ├─ crc16.c
   └─ crc16.h
```

建议任务划分：

- `uart_rx_task`：接收字节流、同步帧头、校验长度和 CRC。
- `command_task`：处理已验证命令，更新目标速度和动作截止时间。
- `status_task`：每 500 ms 回传一次状态。
- `safety_monitor`：使用高优先级定时检查或 `esp_timer` 检查心跳超时。
- 硬件任务看门狗：监控关键任务是否正常运行。

### 5.5 电机驱动规则

统一使用有符号速度：

```text
-100  最大反转
   0  停止
+100  最大正转
```

方向逻辑示例：

| 目标速度 | IN1 | IN2 | PWM |
|---|---:|---:|---:|
| 大于 0 | 1 | 0 | `abs(speed)` |
| 小于 0 | 0 | 1 | `abs(speed)` |
| 等于 0，自由停车 | 0 | 0 | 0 |
| 短刹车 | 1 | 1 | 100% 持续约 50 ms |

换向流程：

1. 当前 PWM 降为零。
2. 等待短暂死区，建议 2 至 10 ms。
3. 修改方向 GPIO。
4. 重新拉高 `STBY`。
5. 按斜坡增加 PWM，避免电流突变和机械冲击。

停止流程：

1. 正常停止可短刹车约 50 ms。
2. PWM 置零。
3. 所有方向输入置低。
4. `STBY` 拉低。

发生通信超时、非法命令、看门狗异常或欠压等故障时，直接执行安全停车；故障停车不必等待 Android 确认。

## 6 TB6612 硬件连接

### 6.1 逻辑连接

| ESP32-C3 | TB6612 | 说明 |
|---|---|---|
| `MOTOR_PWMA_GPIO` | PWMA | 左电机 PWM |
| `MOTOR_AIN1_GPIO` | AIN1 | 左电机方向 1 |
| `MOTOR_AIN2_GPIO` | AIN2 | 左电机方向 2 |
| `MOTOR_PWMB_GPIO` | PWMB | 右电机 PWM |
| `MOTOR_BIN1_GPIO` | BIN1 | 右电机方向 1 |
| `MOTOR_BIN2_GPIO` | BIN2 | 右电机方向 2 |
| `MOTOR_STBY_GPIO` | STBY | 总使能，建议外接下拉 |
| 3.3 V | VCC | TB6612 逻辑电源，需确认模块规格 |
| GND | GND | 逻辑共地 |
| AO1、AO2 | 左电机 | A 通道输出 |
| BO1、BO2 | 右电机 | B 通道输出 |
| 电机电源正极 | VM | 不得由 RK3566 或 C3 GPIO 供电 |

### 6.2 RK3566 与 ESP32-C3 UART

| K11C | ESP32-C3 | 说明 |
|---|---|---|
| UART TX | UART RX | 交叉连接 |
| UART RX | UART TX | 交叉连接 |
| GND | GND | 必须共地 |

只允许连接 3.3 V TTL UART。不得把 RS232 电平直接接入。K11C V1.1 与 V1.2 的扩展口电压可能不同，接线前必须核对 PCB 版本、K11C 电压图和对应 UART 的 pinmux。

### 6.3 供电与抗干扰

- 电机电源直接连接 TB6612 `VM`，按电机额定电压选择电源。
- 必须确认电机启动电流和堵转电流没有超过 TB6612 模块及 PCB 的允许范围。
- TB6612、ESP32-C3 和 RK3566 的逻辑地连接在一起。
- 电机电源入口增加足够的电解电容，驱动器附近放置陶瓷去耦电容。
- 电机端根据实际干扰增加抑制电容，并缩短大电流回路。
- 电机电源和数字逻辑电源合理布线，避免电机回流穿过 RK3566 或 C3 的数字地路径。
- 首次上电使用限流电源，抬起车轮进行测试。

## 7 UART 二进制协议

### 7.1 基本帧格式

采用小端二进制帧：

| 字段 | 长度 | 说明 |
|---|---:|---|
| 帧头 | 2 | 固定 `0xAA 0x55` |
| 版本 | 1 | 首版 `0x01` |
| 消息类型 | 1 | 命令、心跳、查询、响应或故障 |
| 负载长度 | 1 | `0..32` |
| 序号 | 1 | `0..255` 循环递增 |
| 负载 | 0..32 | 按消息类型解释 |
| CRC16 | 2 | 覆盖版本到负载，CRC16-CCITT-FALSE |

CRC 参数固定为：

```text
poly    = 0x1021
init    = 0xFFFF
refin   = false
refout  = false
xorout  = 0x0000
```

### 7.2 消息类型

| 值 | 名称 | 方向 | 作用 |
|---:|---|---|---|
| `0x01` | HEARTBEAT | RK → C3 | 维持链路安全状态 |
| `0x10` | SET_MOTOR | RK → C3 | 设置左右轮速度和持续时间 |
| `0x11` | STOP | RK → C3 | 最高优先级立即停车 |
| `0x20` | QUERY_STATUS | RK → C3 | 查询状态 |
| `0x80` | ACK | C3 → RK | 命令确认 |
| `0x81` | STATUS | C3 → RK | 周期状态 |
| `0xE0` | FAULT | C3 → RK | 故障报告 |

### 7.3 SET_MOTOR 负载

| 字段 | 类型 | 范围 | 说明 |
|---|---|---|---|
| `left_speed` | int8 | `-100..100` | 左轮目标速度百分比 |
| `right_speed` | int8 | `-100..100` | 右轮目标速度百分比 |
| `duration_ms` | uint16 | `0..60000` | 非零表示到时停车；零表示仅靠持续心跳维持 |

Android 每 200 ms 发送心跳。ESP32-C3 超过 600 ms 未收到合法心跳或合法控制帧，应立即安全停车并锁存通信超时状态。再次运动前，建议要求先收到连续若干个合法心跳。

### 7.4 状态响应

建议状态负载至少包含：

```text
last_sequence       最近处理的命令序号
left_speed          当前左轮目标速度
right_speed         当前右轮目标速度
motor_state         stopped / moving / braking / fault
fault_flags         通信超时、CRC 错误、看门狗、欠压等位标志
uptime_ms           下位机启动时间
reset_reason        最近一次复位原因
```

下位机只执行校验完整、版本正确、类型已知且参数合法的命令。随机数据、截断帧、CRC 错误和超范围速度均不得触发电机动作。

## 8 安全机制

### 8.1 必须实现

- `STBY` 硬件下拉，上电默认禁用驱动。
- 初始化 PWM 为零后才允许驱动。
- 600 ms UART 心跳超时停车。
- 每条运动命令可携带动作限时。
- 独立最大连续运动时间，建议首版 4 秒。
- CRC16、长度、版本、消息类型和速度范围校验。
- 看门狗复位前后保持电机关闭。
- STOP 命令最高优先级。
- 下位机复位时向上位机回传复位原因。

### 8.2 建议实现

- PWM 加减速斜坡。
- 换向死区。
- 电池电压或驱动故障检测。
- 电机堵转保护；需要电流检测硬件支持。
- 有编码器时增加闭环转速控制，但首版不必提前实现。

## 9 开发阶段和验证

### 阶段 1 下位机最小闭环

实现 ESP32-C3 UART、CRC、双路 PWM、方向 GPIO、STOP 和 600 ms 失联停车。

验证：串口发送左右速度后电机方向正确；拔掉串口或停止心跳，600 ms 内停车。

### 阶段 2 Android 串口控制

实现 `MotorFrameCodec`、`MotorLink`、心跳、状态查询和手动方向按钮。

验证：Android 界面连续执行前后左右和停止各 20 次，状态响应与实际动作一致。

### 阶段 3 WebSocket 和绑定

迁移设备身份、hello、重连策略和文本消息。

验证：未绑定、绑定完成、网络断开和重连流程均有正确 UI 状态，密钥不出现在日志中。

### 阶段 4 音频闭环

实现录音、重采样、Opus 编码、上传、下行解码和播放。

验证：音频帧格式与服务端协商一致，连续对话无明显堆积、爆音或持续增长的内存占用。

### 阶段 5 MCP 和整车联调

把五个 `self.chassis.*` 工具映射到 UART 命令，并把执行或故障状态反馈给服务端。

验证：语音指令能正确触发动作；服务器断开、App 崩溃、RK3566 重启、串口拔除和 C3 复位均不会导致持续失控。

## 10 验收标准

- 连续执行前进、后退、左转、右转和停止共 100 次，无方向错误。
- 左右轮可在 `-100..100` 范围独立控制。
- 拔除 UART 或终止 Android 应用后，电机在 600 ms 内停止。
- ESP32-C3 上电、复位和烧录期间，TB6612 不产生可观察误动作。
- CRC 错误、截断帧、超范围参数和随机串口数据不能驱动电机。
- Android 应用能够完成绑定、WebSocket 连接、录音、Opus 上行、下行播放和状态显示。
- MCP 动作与实际运动一致，失败时返回真实故障，不返回虚假成功。
- 连续运行 8 小时无明显内存泄漏、音频队列堆积或串口线程退出。

## 11 开发前待确认清单

以下信息确认后才能生成最终接线表和可编译代码：

1. ESP32-C3 四路 PWM 开发板的准确型号、原理图或正反面照片。
2. K11C 是 V1.1 还是 V1.2。
3. K11C Android 版本、内核版本和镜像类型。
4. K11C 可用 UART 对应的排针、设备节点和逻辑电压。
5. Android 普通应用是否有权限打开目标串口。
6. 两台电机的额定电压、额定电流和堵转电流。
7. TB6612 模块的型号、最大电流、逻辑供电和是否带 STBY 下拉。
8. 是否有轮速编码器、舵机或另外两路 PWM 的明确用途。
9. K11C 使用的麦克风、扬声器和屏幕是否已经被 Android 镜像正常识别。
10. 舒心服务端 WebSocket 地址、鉴权方式和实际音频协商参数。

## 12 推荐交付物

完整项目建议包含：

```text
deliverables/
├─ android-app/                 RK3566 Android Studio 工程
├─ esp32c3-motor-controller/    ESP-IDF 下位机工程
├─ protocol/
│  ├─ motor_protocol.md         UART 协议定义
│  └─ test_vectors.json         CRC 和帧测试向量
├─ hardware/
│  ├─ wiring.md                 最终接线表
│  └─ power_checklist.md        供电与首次上电检查
└─ test/
   └─ acceptance_test.md        整车验收步骤和记录
```

开发顺序应先完成下位机安全停车，再做 Android 串口控制，之后接入 WebSocket、音频和语音业务。不要在电机安全链路未经验证时直接进行整车语音联调。
