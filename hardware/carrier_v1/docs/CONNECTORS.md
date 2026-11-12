# 载板连接器定义（Carrier V1.5 · JST XH 2.50）

线束全部 **JST XH（2.50 mm）**；模组座用 2.54 排针。

> **不要买「XH2.54」**。旧 `REVIEW_XH254.md` 已废止。

## 排针

| 位号 | 用途 |
|------|------|
| P1 | K11C 30Pin；DEBUG 25/27 **NC** |
| P2/P3 | DevKit；排距 **22.86 mm** |
| JP1 | `+5V_LOGIC`→`S3_5V`；烧录拔掉 |

### P2 关键脚

| 针 | 网名 | 备注 |
|----|------|------|
| 1, 2 | **NC** | 禁止与 K11C 3V3 并联 DevKit LDO |
| 20 | DIN2 | GPIO14 |
| 21 | S3_5V | 仅经 JP1 |
| 22 | GND | |

### P3

| 针 | 网名 |
|----|------|
| 1, 21, 22 | GND |
| 18 | DIN1 |
| 19 | NC |

## 电源端子

| 位号 | 封装 | 丝印 |
|------|------|------|
| JBAT | **Amass XT60PW-M** | BAT ONLY |
| F1 / SW1 / JVM / JK11 | Phoenix MKDS-1,5 P5.00 | FUSE / SW / D24A-VIN / K11C-12V |

## XH 线束

- J_UART 4P（针4 NC；**或 P1，不要两边都焊**）
- J_CTRL_AB 8P 直插 / J_CTRL_CD 8P **卧式**
- J_ENC_* 4P；J_SERVO_* 3P；J_TOF 4P
