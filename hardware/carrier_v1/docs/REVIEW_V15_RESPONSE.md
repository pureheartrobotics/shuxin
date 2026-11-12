# Carrier V1.5 / Rev F — 对 V1.4 复审「发板前 7 条」的回应

对照：`Carrier_V1.4_评审报告.md` 第 4 节。

## DRC（KiCad 10.0.8，`--refill-zones`）

| 项 | 结果 |
|----|------|
| `courtyards_overlap` | **0** |
| `zones_intersect` | **0** |
| `shorting_items` | **0** |
| `clearance`（severity=error） | **0** |
| `isolated_copper` | **0** |
| violations severity=error | **0**（仅剩丝印 warning） |
| unconnected | 4 条均为 **B.Cu GND 铺铜碎块↔碎块**（无焊盘未连）；PTH/TP 地已入铺铜 |

## 7 条必做

| # | 要求 | V1.5 |
|---|------|------|
| 1 | 重做铺铜，GND/VBAT 不相交 | F.Cu：**VBAT / VBAT_F / VM / V_SERVO** 分岛且不相交；B.Cu：整板 **GND**。`post_fix_power.py` 每次布线后**删重建**铺铜并赋网 |
| 2 | 换 D1 | **SR20100** DO-201AD（20 A 级肖特基），阴极侧 **VBAT_F 铺铜散热** |
| 3 | 挪开 courtyard 冲突 | C_SERVO→(160,*)；舵机座→145；TP 离开 C_IN/ENC；**courtyards_overlap=0** |
| 4 | BOM 电源端子 + JBAT 防呆 | BOM 写明 **MKDS-1,5 P5.00**；**JBAT=Amass XT60PW-M**（与 MKDS 不同型） |
| 5 | 删 cam/、换顶视图、更新 REVIEW_XH254 | **已删 `cam/`**；`out/board_top.svg` + `board_top.pdf`；`REVIEW_XH254.md` 改为废止页 |
| 6 | 3.3 V 双源 | **P2-1/2 = NC**；+3V3 仅来自 K11C；S3 经 JP1/`S3_5V` 或 USB |
| 7 | 170×120 机械 | 板框仍 **170×120**；请用卡尺核壳体 / DevKit / MH_* |

## V1.4 新问题对照

| ID | 处理 |
|----|------|
| N1 D1 电流 | SR20100 |
| N2 铺铜无网/重叠 | 重建+赋网+不相交 |
| N3 courtyard | 已清零 |
| N4 电源口同型 | JBAT→XT60 |
| N5 3V3 双源 | P2-1/2 NC |
| N6 BOM 封装 | 与板一致 |
| N7 cam/ | 已删 |
| N8 board_top | 换 SVG/PDF |
| N9 REVIEW_XH254 | 废止 |
| N11 过孔 | FAB 改为与板一致 **0.6/0.3** |

## 仍可接受（评审第 5 节）

- 原理图 parity 未做（PCB+`nets.csv` 为真值）
- J_UART 与 P1 同网（丝印：or P1, not both）
- 无 TVS（调试板）
