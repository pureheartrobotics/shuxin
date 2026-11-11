# 载板连接器定义（Carrier V1）

冻结目标：零杜邦，模组仍可插拔（K11C 排线 + S3 DevKit 座 + D24A 控制/编码座）。

电源域：**V1.2 K11C 扩展脚 = 3.3 V**。电机 VM ≈ 电池 10.8–12.6 V。舵机独立 **8.4 V**。全车 **GND 星接**（建议以 D24A GND 为星点回流）。

---

## P1 — K11C 30Pin 扩展（2×15, 2.54 mm 母座或排线）

与 KickPi K11C 手册一致（奇数/偶数列）。

| Pin | 信号 | 载板用途 |
|-----|------|----------|
| 1 | VCC3V3_SYS | 仅监测/可选上拉参考，**不给电机** |
| 2 | VCC5V0_SYS | 不用（可 NC） |
| 3 | GND | GND |
| 4 | VCC5V0_SYS | NC |
| 5–14 | I2S/GPIO | NC（预留测试点） |
| 15 | *UART7_RX* | ← S3 GPIO17（TX） |
| 16 | *I2C3_SCL* | → ToF SCL |
| 17 | *UART7_TX* | → S3 GPIO18（RX） |
| 18 | *I2C3_SDA* | → ToF SDA |
| 19–22 | UART9/GPIO | NC |
| 23 | GND | GND |
| 24 | GPIO | NC |
| 25 | UART2_RX_DEBUG | **禁止接业务** |
| 26 | GPIO | NC |
| 27 | UART2_TX_DEBUG | **禁止接业务** |
| 28 | PWM7 | NC |
| 29 | GND | GND |
| 30 | SARADC | NC |

K11C 主板 **DC 12V** 仍走板载电源口，不从本座取大电流。

---

## P2 — ESP32-S3-DevKitC-1 左排（22P 母座，USB 朝上时左侧）

仅列出本车占用脚；其余脚座上存在但不走线。

| DevKit 左脚号 | GPIO | 网名 |
|---------------|------|------|
| 4 | 4 | PWMA |
| 5 | 5 | AIN1 |
| 6 | 6 | AIN2 |
| 7 | 7 | PWMB |
| 8 | 15 | BIN1 |
| 9 | 16 | BIN2 |
| 10 | 17 | UART_TX_TO_K11C（→ P1-15） |
| 11 | 18 | UART_RX_FROM_K11C（← P1-17） |
| 12 | 8 | STBY |
| 13 | 3 | ENC_A_B (E1B) |
| 14 | 46 | ENC_A_A (E1A) |
| 15 | 9 | PWMC |
| 16 | 10 | CIN1 |
| 17 | 11 | CIN2 |
| 18 | 12 | PWMD |
| 19 | 13 | ENC_B_B (E2B) |

**禁止占用**：GPIO19/20（USB）、GPIO48（RGB）、GPIO33–37（Octal PSRAM）。

---

## P3 — ESP32-S3-DevKitC-1 右排（22P 母座）

| DevKit 右脚号 | GPIO | 网名 |
|---------------|------|------|
| 4 | 1 | SERVO_PAN |
| 5 | 2 | SERVO_TILT |
| 6 | 42 | ENC_D_A (E4A) |
| 7 | 41 | ENC_C_B (E3B) |
| 9 | 39 | ENC_D_B (E4B) |
| 10 | 38 | ENC_B_A (E2A) |
| 17 | 47 | ENC_C_A (E3A) |
| 18 | 21 | DIN1 |
| 19 | 14 | DIN2 |

5V/GND：DevKit 的 5V 默认经 **JP1** 可选接到 D24A 逻辑 5V；**烧录时拔掉 JP1**，只用 USB。

---

## P4 — D24A 控制口（对 D24A J4 + J6）

建议 2×8 IDC 或两组 XH2.54，丝印与 D24A 脚位一一对应。

| 载板网名 | D24A | S3 |
|----------|------|-----|
| STBY | J4-2 | GPIO8 |
| PWMA | J4-4 | GPIO4 |
| AIN1 | J4-6 | GPIO5 |
| AIN2 | J4-8 | GPIO6 |
| PWMB | J4-3 | GPIO7 |
| BIN1 | J4-5 | GPIO15 |
| BIN2 | J4-7 | GPIO16 |
| PWMC | J6-4 | GPIO9 |
| CIN1 | J6-6 | GPIO10 |
| CIN2 | J6-8 | GPIO11 |
| PWMD | J6-3 | GPIO12 |
| DIN1 | J6-5 | GPIO21 |
| DIN2 | J6-7 | GPIO14 |
| GND | J4/J6 GND | GND |
| +5V_LOGIC | D24A 5V | → JP1 → DevKit 5V |

每根控制线串 **100 Ω**（1206），靠近 S3 座。

---

## P5 — 编码器（对 D24A E1–E4 / 电机 6P 编码针）

| 电机 | 位置 | E*A | E*B | S3 |
|------|------|-----|-----|-----|
| A | 右后 | E1A→GPIO46 | E1B→GPIO3 | |
| B | 右前 | E2A→GPIO38 | E2B→GPIO13 | |
| C | 左前 | E3A→GPIO47 | E3B→GPIO41 | |
| D | 左后 | E4A→GPIO42 | E4B→GPIO39 | |

编码电源：**3.3 V**（取自 D24A 编码 3V3 或载板稳压），与信号共地。动力线不得进编码座。

---

## P6 — 舵机（2× XH2.54-3P）

| 针 | PAN | TILT |
|----|-----|------|
| 1 | SERVO_PAN (GPIO1) | SERVO_TILT (GPIO2) |
| 2 | V_SERVO 8.4 V | V_SERVO 8.4 V |
| 3 | GND | GND |

---

## P7 — ToF VL53L5CX（4P：3V3 / GND / SCL / SDA）

| 针 | 网名 |
|----|------|
| 1 | 3V3（K11C Pin1 或独立 LDO） |
| 2 | GND |
| 3 | I2C3_SCL（P1-16） |
| 4 | I2C3_SDA（P1-18） |

SDA/SCL 各 **4.7 kΩ** 上拉到 3V3（若模组已带上拉可 DNP）。

---

## 电源连接器

| 位号 | 类型 | 用途 |
|------|------|------|
| JBAT | XT30/XT60 | 电池入 |
| F1 | 自恢复/管状保险 10–15 A | 总保险 |
| SW1 | 总开关 | 电池切断 |
| J_K11C_PWR | DC5.5 或接线端子 | → K11C 12V 口 |
| J_VM | 端子 | → D24A VIN/VM |
| U_BUCK | 8.4 V ≥5 A 模块座 | → V_SERVO |
| TP_* | 测试点 | VM、5V、3V3、8.4V、UART、E1–E4 |
