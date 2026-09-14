# RK3566 Android 与 ESP32-C3 TB6612 方案修改评审

## 1 文档目的

本文从硬件工程和整机安全角度，评审后端同事提交的 RK3566 语音控车方案，并给出必须修改的内容、软硬件接口、接线原则、开发分工和验收门槛。

评审输入：

- KICKPI K11C RK3566 硬件资料：`E:\Users\24303\Desktop\rk3566`
- 后端交接方案：`E:\shuxin\houduan\rk3566`
- 后端代码仓库 RK3566 分支：`E:\shuxin\houduan\shuxin` 的 `feature/rk3566`
- 现有 ESP32 参考工程：`E:\Users\24303\Desktop\screen\SHUXIN-esp32-2.0.3-button-ble`

目标系统不是 Debian/Ubuntu 命令行程序，而是：

```text
RK3566 K11C Android App
        │ 3.3 V TTL UART
        ▼
ESP32-C3 四路 PWM 开发板
        │ 2 路 PWM + 5 路 GPIO
        ▼
TB6612 双路直流电机驱动
        │
        ├─ 左电机
        └─ 右电机
```

## 2 评审结论

后端方案的 WebSocket、设备鉴权、Opus 参数、语音口令解析和底盘抽象可以保留为协议参考。但当前交付物不能直接用于目标整车，必须完成以下架构调整：

1. 将 Python/Linux 客户端重写为 Android App。
2. 删除 RK3566 直接通过脚本长期驱动电机的产品路径。
3. 新增 Android 到 ESP32-C3 的 UART 二进制协议。
4. 新增 ESP32-C3 电机下位机固件。
5. 将 TB6612 PWM、方向控制、刹车、心跳超时和看门狗全部放到 ESP32-C3。
6. 增加 K11C UART 权限、设备树、逻辑电平和 SELinux 验证。
7. 将整段录音和整段播放改成实时流式音频。
8. 修正语音口令误触发风险，停止命令必须拥有最高优先级。

当前方案可作为 Linux 概念验证，不可作为 Android 整车量产方案直接实施。

## 3 后端现方案逐项处理

| 现有内容 | 处理决定 | 原因 | 修改后结果 |
|---|---|---|---|
| `/ws/voice` WebSocket 协议 | 保留 | 已与后端语音服务对接 | Android 使用相同消息协议 |
| `device_code`、`device_secret` 鉴权 | 保留协议，重写存储 | 环境变量不适合 Android 产品 | Keystore 加密保存 |
| 16 kHz 上行 Opus | 保留 | 与现有服务协议一致 | Android 实时编码发送 |
| 24 kHz 下行 Opus | 保留 | 与现有服务协议一致 | Android 实时解码播放 |
| Python 3.11 客户端 | 删除产品依赖 | Android 默认没有 Python/pip | Kotlin/Java + NDK APK |
| `arecord`/`aplay` | 替换 | Android 普通应用不应依赖 ALSA 命令 | `AudioRecord`/`AudioTrack` |
| `drive.sh` 抽象 | 仅保留动作语义 | 当前脚本没有真实电机实现 | Android `MotorLink` 发送 UART 帧 |
| RK3566 GPIO/PWM/ROS2 三选一 | 收敛为 UART | 方案不明确且无法形成安全闭环 | 唯一产品路径为 ESP32-C3 下位机 |
| STT 文本本地正则控车 | 修改 | 否定句、转述句可能误触发 | 安全解析 + 服务端结构化命令 |
| duration 到期后脚本停车 | 移至 C3 | RK3566 卡死时脚本无法保证执行 | 下位机硬件定时独立停车 |
| SIGTERM 时脚本停车 | 仅作辅助 | 强杀、系统死机、断电时无保证 | C3 心跳超时为最终保护 |
| 默认 mock 底盘 | 保留开发模式 | 便于无硬件联调 | Android 提供 mock/uart 两种构建配置 |
| `spin` 动作 | 明确定义 | 当前没有左右轮映射 | 默认原地右旋，可配置左右方向 |
| 括弧动作提取 | 可保留 | 可用于屏幕或舵机 | 不得直接映射成危险电机动作 |

## 4 后端文件需要修改的地方

### 4.1 `HARDWARE_HANDOFF.md`

后端交接文件：

```text
E:\shuxin\houduan\rk3566\HARDWARE_HANDOFF.md
```

必须修改：

- 将系统描述从“RK3566 Linux Debian/Ubuntu、Python 3.11”改为“RK3566 Android App”。
- 删除 `apt-get`、`pip`、Python venv、`arecord`、`aplay` 作为产品安装步骤。
- 明确 Python 版本只用于电脑端或 Linux 原型验证，不是最终板端实现。
- 将“电子同事在 `drive.sh` 填 GPIO/串口/ROS2”改为固定接口：“Android App 通过 UART 与 ESP32-C3 通信”。
- 增加 UART 电气标准、帧格式、CRC、心跳、状态回传和故障码。
- 增加 K11C V1.1/V1.2 电平差异。
- 增加 ESP32-C3 和 TB6612 的接线、供电及上电默认安全状态。
- 增加“不得由 RK3566 GPIO 直接驱动电机或给电机供电”。
- 增加 Android 串口权限和设备树验收步骤。
- 把“脚本退出后停车”降级为上位机辅助保护，把 ESP32-C3 失联停车定义为最终保护。

### 4.2 `scripts/drive.sh`

后端模板：

```text
E:\shuxin\houduan\rk3566\scripts\drive.sh
```

当前问题：

- `cleanup()` 只有日志，没有刹车。
- 动作分支只有 `sleep`，不会控制电机。
- 没有 UART、CRC、序号、ACK、状态和心跳。
- 进程或系统崩溃时无法保证停止。
- 一个动作启动一个进程，不适合持续维护 200 ms 心跳。
- 脚本无法作为 Android APK 的正常硬件接口。

处理建议：

- 产品版本不再使用 `drive.sh` 控制电机。
- 脚本只保留为 Linux 原型兼容工具，内部调用一个长期运行的串口守护进程，而不是直接碰 GPIO。
- Android 产品中用常驻 `MotorLink` 取代脚本：保持 UART 打开、每 200 ms 心跳、异步接收状态。
- 如果暂时继续使用脚本联调，脚本必须调用一个能发送 `SET_MOTOR`/`STOP` 帧的串口 CLI；真正的 duration 和超时仍由 C3 执行。

### 4.3 `apps/rk3566/shuxin_rk3566/config.py`

现有配置通过环境变量读取设备身份。Android 版需要：

- `DeviceRuntimeConfig` 改为 Kotlin 数据类。
- WebSocket 地址和非敏感参数存入 DataStore。
- `device_secret` 使用 Android Keystore 加密存储。
- 禁止提供 `demo-device-001` 作为生产默认设备。
- 未配置密钥时进入绑定界面，不得带空密钥不断重连。
- 增加 UART 设备节点、波特率和协议版本配置，但生产构建应锁定经过验证的值。

### 4.4 `apps/rk3566/shuxin_rk3566/audio.py`

必须重写：

- `AlsaCapture` 替换为 `AudioRecord`。
- `AlsaPlayback` 替换为 `AudioTrack`。
- `opuslib_next` 替换为 Android NDK `libopus` 或经过互操作测试的 Android Opus 实现。
- 由一次录制完整 4 秒改为连续读取 PCM，每 60 ms 编码并立即发送。
- 由收齐所有下行包后播放改为边接收、边解码、边播放。
- 增加录音设备能力检测、采样率转换、有界缓冲区、播放欠载处理和音频焦点管理。
- 录音权限拒绝时进入明确错误状态。

### 4.5 `apps/rk3566/shuxin_rk3566/client.py`

可保留消息语义，但需重写为 Android WebSocket 客户端：

- 使用 Kotlin 协程管理连接、发送、接收和重连。
- WebSocket ping 与电机 UART 心跳必须完全分开；20 秒网络 ping 不能代替 200 ms 电机心跳。
- 接收 Opus 包后立即进入解码队列，不能全部保存到 `downlink_packets`。
- 录音帧按真实时间发送，不能录完后突发上传。
- 网络断开或会话异常时调用 `MotorLink.emergencyStop()`。
- 服务端 `STT final` 不是唯一安全动作来源；优先增加服务端签发的结构化 `motion/command` 事件。
- 对消息乱序、重复、无效 JSON 和超大包做限制。

### 4.6 `apps/rk3566/shuxin_rk3566/chassis.py`

必须把 `CommandChassis` 替换为 Android `UartChassisDriver`：

```text
MotionCommand
  → 动作映射为 left_speed/right_speed
  → MotorFrameCodec 编码
  → UART 发送 SET_MOTOR
  → 等待匹配序号 ACK
  → 状态更新或故障上报
```

必须新增：

- UART 连接状态。
- 发送互斥与序号生成。
- ACK 超时和有限重试。
- STOP 抢占普通动作。
- 心跳协程。
- 状态接收和 CRC 错误统计。
- App 退出、服务异常和串口异常时的停止请求。

不得把“收到 ACK”理解成“电机物理上一定已经转动”。ACK 只表示 C3 接受命令；实际状态需由 C3 的 STATUS 返回。

### 4.7 `motion_intent.py`

当前正则解析存在危险误触发。必须增加：

- 否定优先：`不要后退`、`不能前进`、`别往左`只能产生 STOP 或无动作。
- 疑问过滤：`可以前进吗`默认不执行，除非产品明确定义为命令。
- 转述过滤：`他说让我前进`、`刚才往左走了`不得执行。
- 指令白名单和最大持续时间。
- 同一句同时出现停止和移动时只执行 STOP。
- 低置信度不动作。
- 测试至少覆盖否定句、疑问句、转述句、同音误识别和重复 STT final。

硬件侧不信任自然语言解析结果。ESP32-C3 仍需独立校验速度、持续时间和帧完整性。

### 4.8 `main.py`

必须替换为 Android 应用生命周期：

- Android `Application` 初始化非硬件资源。
- 前台 Service 管理 WebSocket、音频和 UART。
- Activity/Compose 只负责显示和用户输入。
- 使用状态机统一管理 `UNBOUND`、`IDLE`、`LISTENING`、`SPEAKING`、`MOVING`、`FAULT`。
- 开机自启仅在系统应用、Device Owner 或允许的产品配置下启用。
- Android 进入错误、服务结束或用户退出时发送 STOP，但最终安全依靠 C3 超时。

### 4.9 后端需要新增的服务端字段

建议增加结构化运动事件，避免 Android 仅靠 STT 文本正则控制真实电机：

```json
{
  "type": "motion",
  "state": "command",
  "command_id": "server-generated-id",
  "action": "forward",
  "left_speed": 55,
  "right_speed": 55,
  "duration_ms": 800,
  "expires_at_ms": 0
}
```

要求：

- `command_id` 可去重。
- `left_speed`、`right_speed` 范围为 `-100..100`。
- `duration_ms` 最大 4000 ms。
- STOP 独立消息并拥有最高优先级。
- 指令需绑定当前已鉴权 WebSocket 会话。
- Android 必须检查事件类型、参数范围、过期时间和重复 ID。
- 服务端不得发送无限时长运动命令。

本地 STT 规则可以作为低延迟优化，但必须通过同一安全校验层后才能发往 C3。

## 5 RK3566 K11C 硬件修改和确认

### 5.1 推荐 UART 选择

根据现有 K11C 引脚图，可选 UART 包括：

| UART | K11C 物理引脚 | Rockchip GPIO | 备注 |
|---|---|---|---|
| UART7 RX | Pin 15 | GPIO4_A3 | 图中标注 `UART7_RX_M2` |
| UART7 TX | Pin 17 | GPIO4_A2 | 图中标注 `UART7_TX_M2` |
| UART9 TX | Pin 19 | GPIO4_A4 | 图中标注 `UART9_TX_M2` |
| UART9 RX | Pin 21 | GPIO4_A5 | 图中标注 `UART9_RX_M2` |
| UART3 TX | Pin 16 | GPIO1_A1 | 与 I2C3 SCL 复用 |
| UART3 RX | Pin 18 | GPIO1_A0 | 与 I2C3 SDA 复用 |
| UART2 RX/TX | Pin 25/27 | 调试串口 | 不推荐占用系统调试口 |

首选 UART7 的 Pin 15/17；若被系统占用，再评估 UART9。UART2 调试串口应保留给启动日志和故障调试。

### 5.2 K11C 版本与电平

现有电压图显示：

- K11C V1.2 的 Pin 15 和 Pin 17 为 3.3 V 逻辑，可与 ESP32-C3 3.3 V UART 直接连接。
- K11C V1.1 的 Pin 15 和 Pin 17 为 1.8 V 逻辑，不能直接按 3.3 V UART 连接；必须使用双向电平转换器，或重新选择经确认的 3.3 V UART 引脚。
- K11C V1.1 的 Pin 16/18 标为 3.3 V，但默认复用信息显示 I2C3，改作 UART3 前需要设备树和 pinmux 调整。

在 PCB 版本未确认前，不得焊接 UART 信号线。

### 5.3 推荐接线表

以 K11C V1.2、UART7 为例：

| K11C | ESP32-C3 | 连接 |
|---|---|---|
| Pin 17 UART7 TX | C3 UART RX | 交叉连接 |
| Pin 15 UART7 RX | C3 UART TX | 交叉连接 |
| Pin 13、23 或 29 GND | C3 GND | 必须共地 |

注意：

- 不要把 K11C Pin 1 的 3.3 V 默认用作整车供电。
- ESP32-C3 的供电方式取决于具体开发板输入接口和稳压设计。
- UART 仅连接 TX、RX、GND；除非电源设计明确，不通过排针互相反向供电。
- 电机电源不得从 K11C 或 ESP32-C3 GPIO/3.3 V 引脚取得。

### 5.4 Android 镜像必须验证

在真机执行：

```sh
adb shell getprop ro.build.version.release
adb shell getprop ro.build.type
adb shell uname -a
adb shell id
adb shell getenforce
adb shell 'ls -lZ /dev/ttyS* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null'
adb shell 'cat /proc/tty/driver/serial 2>/dev/null'
```

然后确认：

1. UART7 对应的真实 `/dev/tty*` 节点。
2. UART7 pinmux 是否已经启用。
3. 是否被系统服务占用。
4. 普通 APK 是否可读写。
5. SELinux enforcing 下是否允许访问。

如果普通 APK 返回 `Permission denied`，需要：

- 将应用做成平台签名系统应用，或增加受控的 Binder/AIDL 串口服务。
- 修改 `ueventd.rc` 的目标串口设备权限和属组。
- 增加最小范围的 SELinux type/enforcement 规则。
- 不允许使用全局关闭 SELinux 作为正式解决方案。

如果没有设备节点，需要在 K11C Android 设备树中启用相应 UART 和 pinctrl。修改后还要确认该引脚没有与 I2C、I2S、PWM、PDM 或其他设备冲突。

## 6 ESP32-C3 四路 PWM 下位机必须新增

### 6.1 功能边界

ESP32-C3 负责：

- UART 二进制协议解析。
- CRC16、长度、版本、序号和参数校验。
- 左右轮独立 PWM。
- TB6612 方向和 STBY。
- 运动限时。
- 600 ms 通信超时停车。
- 50 ms 短刹车。
- 换向死区和可选速度斜坡。
- 状态、故障和复位原因回传。
- 任务看门狗。

ESP32-C3 不负责云端连接、Wi-Fi、BLE、ASR、TTS、显示和设备绑定。首版关闭不需要的无线功能。

### 6.2 四路 PWM 分配

TB6612 双路电机只使用两路 PWM：

| C3 PWM | 用途 | 状态 |
|---|---|---|
| PWM0 | TB6612 PWMA，左轮调速 | 使用 |
| PWM1 | TB6612 PWMB，右轮调速 | 使用 |
| PWM2 | 舵机或灯光 | 预留 |
| PWM3 | 舵机或灯光 | 预留 |

PWM0/PWM1 推荐 10 kHz、10 bit。PWM2/PWM3 不得与电机通道并接。若后续用作普通舵机，应使用约 50 Hz，与电机 PWM 分开配置定时器。

### 6.3 ESP32-C3 GPIO 不能提前写死

目前只知道是“四路 PWM 开发板”，没有准确型号和原理图。因此必须先确认：

- 四路 PWM 接口对应的 C3 GPIO。
- 哪些 GPIO 已连接板载 MOSFET、LED、继电器或其他器件。
- PWM 接口输出是不是 3.3 V 逻辑信号。
- 是否允许把 PWM 接口直接接到 TB6612 PWMA/PWMB。
- 可用 UART TX/RX。
- 可用的 5 路普通 GPIO。
- 启动绑带脚和板载上下拉。

固件统一通过 `board_config.h` 配置：

```c
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

在开发板原理图确认前，任何具体 GPIO 表只能作为占位，不得直接接线生产。

### 6.4 TB6612 接线

| ESP32-C3 | TB6612 | 功能 |
|---|---|---|
| PWM0 GPIO | PWMA | 左电机速度 |
| AIN1 GPIO | AIN1 | 左电机方向 1 |
| AIN2 GPIO | AIN2 | 左电机方向 2 |
| PWM1 GPIO | PWMB | 右电机速度 |
| BIN1 GPIO | BIN1 | 右电机方向 1 |
| BIN2 GPIO | BIN2 | 右电机方向 2 |
| STBY GPIO | STBY | 驱动总使能 |
| 3.3 V 逻辑电源 | VCC | TB6612 逻辑供电 |
| GND | GND | 逻辑共地 |
| 电机电源 | VM | 电机功率供电 |
| AO1/AO2 | 左电机 | A 通道输出 |
| BO1/BO2 | 右电机 | B 通道输出 |

STBY 必须增加外部下拉。C3 未启动、复位、下载固件或掉电时，TB6612 必须保持关闭。

### 6.5 供电修改

必须补充完整电源树：

```text
电池/外部电源
├─ 稳压后供 K11C
├─ 稳压后供 ESP32-C3 开发板
└─ 按电机额定电压供 TB6612 VM

K11C GND ─ ESP32-C3 GND ─ TB6612 GND
```

设计要求：

- 核对电机额定电压、启动电流和堵转电流。
- 核对 TB6612 模块连续及峰值电流能力。
- VM 入口布置电解储能电容，TB6612 附近布置陶瓷去耦。
- 大电流电机回路不要经过 K11C 或 C3 的数字地细线。
- 电机端按 EMC 测试结果增加抑制电容。
- 首次测试使用限流电源并架空车轮。
- 如果堵转电流超出 TB6612 能力，必须更换驱动器，不能靠软件限速掩盖。

## 7 Android 与 ESP32-C3 UART 协议

### 7.1 物理层

```text
115200 bit/s
8 data bits
no parity
1 stop bit
no flow control
3.3 V TTL for K11C V1.2
```

K11C V1.1 使用 UART7 时增加合适的 1.8 V/3.3 V 双向电平转换器。电平转换器必须适合推挽 UART，不使用只适合低速开漏 I2C 的错误接法。

### 7.2 帧格式

所有多字节整数使用小端：

| 字段 | 字节数 | 说明 |
|---|---:|---|
| Header | 2 | `AA 55` |
| Version | 1 | `01` |
| Type | 1 | 消息类型 |
| Length | 1 | 负载长度，最大 32 |
| Sequence | 1 | 发送序号 |
| Payload | 0..32 | 消息内容 |
| CRC16 | 2 | Version 到 Payload |

CRC 使用 CRC16-CCITT-FALSE：

```text
poly=0x1021 init=0xFFFF refin=false refout=false xorout=0x0000
```

### 7.3 消息定义

| Type | 名称 | 方向 | 说明 |
|---:|---|---|---|
| `0x01` | HEARTBEAT | RK → C3 | 每 200 ms |
| `0x10` | SET_MOTOR | RK → C3 | 左右速度和时长 |
| `0x11` | STOP | RK → C3 | 立即停车，最高优先级 |
| `0x20` | QUERY_STATUS | RK → C3 | 查询状态 |
| `0x80` | ACK | C3 → RK | 返回对应序号和结果 |
| `0x81` | STATUS | C3 → RK | 周期状态 |
| `0xE0` | FAULT | C3 → RK | 故障上报 |

`SET_MOTOR` 负载：

```text
int8   left_speed       -100..100
int8   right_speed      -100..100
uint16 duration_ms      0..4000
```

动作映射：

| 动作 | 左轮 | 右轮 |
|---|---:|---:|
| forward | `+speed` | `+speed` |
| backward | `-speed` | `-speed` |
| left | `-speed` | `+speed` |
| right | `+speed` | `-speed` |
| spin | `+speed` | `-speed`，默认右旋 |
| stop | 0 | 0 |

如果实车电机极性相反，只在 C3 的板级配置中设置左右轮反相，不在后端或 Android 到处交换正负号。

### 7.4 安全时序

```text
C3 上电
 → STBY 硬件下拉保持低
 → 初始化 GPIO
 → PWM=0
 → 启动 UART 与看门狗
 → 等待连续合法心跳
 → 允许接受运动命令

运动期间
 → Android 每 200 ms 发心跳
 → C3 持续检查 CRC 和时间
 → 超过 600 ms 无合法帧
 → PWM=0 / 安全刹车
 → STBY=0
 → 回传通信超时故障
```

正常停止可先进行约 50 ms 短刹车，再 PWM 清零并拉低 STBY。故障状态应优先快速进入安全态，不依赖 Android ACK。

## 8 Android App 必须新增的模块

建议最小工程结构：

```text
android-app/
├─ ui/                  界面、绑定、状态和手动急停
├─ binding/             设备身份与 Keystore
├─ network/             WebSocket 和重连
├─ audio/               AudioRecord、AudioTrack、Opus
├─ conversation/        会话状态机
├─ motion/              动作安全判定
├─ motor/
│  ├─ MotorLink         UART 长连接和心跳
│  ├─ MotorFrameCodec   帧编码、解码和 CRC
│  ├─ MotorController   STOP 抢占与命令状态
│  └─ MotorStatus       下位机状态
└─ native/
   ├─ serial_port.cpp   串口 JNI
   └─ opus_bridge.cpp   Opus JNI
```

Android 必须提供：

- 显眼且始终可用的屏幕急停按钮。
- UART 未连接、C3 未就绪、故障未清除时禁止发送运动命令。
- App 在后台运动时使用前台服务。
- 网络状态、串口状态、C3 状态和电机状态分开显示。
- 生产日志隐藏设备密钥。
- 音频与 UART 都使用有界队列。
- STOP 不进入普通动作队列，直接抢占。
- Android UI 卡顿不能影响 UART 心跳线程。

## 9 ESP32-C3 固件文件清单

建议新增独立工程：

```text
esp32c3-motor-controller/
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

任务建议：

- UART 接收任务：同步帧头、限制长度、校验 CRC。
- 命令任务：处理已经通过校验的控制命令。
- 状态任务：每 500 ms 回传状态。
- 安全定时器：检查 600 ms 心跳和动作截止时间。
- 任务看门狗：监控关键任务。

每次复位后的第一条动作必须在 UART 链路重新就绪后执行。不要从 NVS 恢复上一次运动状态。

## 10 测试和验收修改

后端现有单元测试只覆盖基础文本解析和 mock 动作取消，必须增加以下测试。

### 10.1 协议单元测试

- Android 与 C3 使用同一组 CRC 测试向量。
- 覆盖最小帧、最大负载、错误版本、错误长度、错误 CRC 和随机字节流。
- 序号从 255 回绕到 0。
- 重复 SET_MOTOR 不产生不可控重复状态。
- STOP 在任何状态下均可执行。

### 10.2 C3 台架测试

- 未连接 RK3566 时上电，STBY 保持低。
- UART 随机输入不能产生 PWM。
- 心跳停止后 600 ms 内停车。
- 控制程序崩溃或看门狗复位时不误动作。
- 运动到 duration 后由 C3 自行停车。
- 连续正反转检查死区和电流尖峰。
- PWM0/PWM1 可独立调速；PWM2/PWM3 保持未启用。

### 10.3 K11C Android 测试

- 冷启动后能打开正确 UART。
- SELinux enforcing 下持续运行，不依赖临时 `chmod 777`。
- App 切后台、息屏和网络重连时 UART 心跳稳定。
- 强制停止 App 后 C3 在 600 ms 内停车。
- Android 重启、拔 UART 和 C3 重启均进入明确故障状态。
- 连续 8 小时运行，无音频缓存增长或串口任务退出。

### 10.4 整车安全测试

- 车轮架空完成方向确认后才能落地。
- 前进、后退、左转、右转、停止各执行 100 次。
- `不要前进`、`不要后退`、`不要左转`不能产生反向误动作。
- 用户说“停”时中断当前动作，C3 实际停止时间符合要求。
- 拔掉 UART、杀死 App、断网和重启 RK3566，车辆均不会持续运行。
- 电机堵转和低电压测试需在限流条件下进行。

## 11 开发任务与责任划分

| 责任方 | 必须交付 |
|---|---|
| 后端 | WebSocket 协议、设备鉴权、结构化 motion 事件、测试账号和服务端联调环境 |
| Android | APK、实时音频、WebSocket、Keystore、UART MotorLink、状态 UI 和急停 |
| ESP32 | C3 UART 协议、PWM、TB6612、心跳超时、看门狗和状态回传 |
| 硬件 | K11C 版本确认、UART 电平、接线图、电源树、TB6612 电流核算和 EMC 整改 |
| 测试 | CRC 测试向量、台架故障注入、整车动作和长稳测试 |

接口责任边界：

- 后端不直接控制 GPIO。
- Android 不生成实时 PWM。
- ESP32-C3 不保存云厂商密钥。
- TB6612 不由 RK3566 直接供电。
- 电机最终安全状态由 ESP32-C3 保证。

## 12 修改优先级

### P0 阻塞项

在这些事项完成前不得上车落地测试：

1. 确认 K11C V1.1/V1.2。
2. 确认 ESP32-C3 四路 PWM 板准确型号和原理图。
3. 确认电机额定和堵转电流与 TB6612 匹配。
4. 确认 K11C UART 节点、pinmux、电平和 Android 权限。
5. 完成 C3 上电默认 STBY 低和 600 ms 失联停车。
6. 完成 UART CRC 协议和 STOP 抢占。
7. 修复否定语句误触发。

### P1 功能项

1. Android WebSocket 客户端。
2. Android 实时录音和 Opus 上行。
3. Android 流式 Opus 播放。
4. 设备绑定与 Keystore。
5. C3 状态回传和 Android 状态展示。
6. MCP/结构化运动事件接入。

### P2 优化项

1. PWM 加减速斜坡。
2. 编码器闭环控制。
3. 电流/堵转检测。
4. 欠压保护。
5. PWM2/PWM3 舵机或灯光扩展。
6. OTA 和工厂测试工具。

## 13 修改完成判定

只有同时满足以下条件，才能认为后端方案已修改为可实施的整车方案：

- Android APK 不依赖 Python、pip、Bash、`arecord` 或 `aplay`。
- Android 能在 SELinux enforcing 状态访问经过授权的 UART。
- 音频真正按帧实时上传和播放。
- Android 与 C3 使用固定、带 CRC 的 UART 协议。
- C3 独立生成双路电机 PWM，并管理 TB6612 STBY。
- RK3566 失联后 C3 能在 600 ms 内停车。
- 随机串口数据、CRC 错误和非法参数不能驱动电机。
- 否定句、疑问句和转述句不会误触发动作。
- 整车通过断网、断串口、杀 App、重启和堵转等故障测试。

## 14 当前仍需提供的资料

为了输出最终无占位符的接线图、设备树修改和 ESP32-C3 `board_config.h`，还需要：

1. K11C PCB 丝印照片，用于确认 V1.1 或 V1.2。
2. ESP32-C3 四路 PWM 开发板的准确商品型号、原理图或清晰正反面照片。
3. TB6612 模块正反面照片或原理图。
4. 电机铭牌参数，至少包括额定电压和堵转电流。
5. K11C Android 真机命令输出，包括 Android 版本、内核、SELinux 和 `/dev/tty*`。
6. 是否必须使用 UART7，还是允许修改设备树启用 UART9/UART3。

在上述资料补齐之前，可以并行完成 Android 协议层、C3 通用协议层和测试向量，但不应确定最终 GPIO 或制作量产线束。
