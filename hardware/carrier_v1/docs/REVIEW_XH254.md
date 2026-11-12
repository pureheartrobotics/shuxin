# 审阅说明 — Carrier V1.3（杜邦 → XH2.54）

请按本页审阅。仓库分支：`hardware/pcb-review-k11c`。

## 路径

| 内容 | 路径 |
|------|------|
| 工程目录 | [`hardware/carrier_v1/`](https://github.com/pureheartrobotics/shuxin/tree/hardware/pcb-review-k11c/hardware/carrier_v1) |
| **连接器真值（先看）** | [`docs/CONNECTORS.md`](https://github.com/pureheartrobotics/shuxin/blob/hardware/pcb-review-k11c/hardware/carrier_v1/docs/CONNECTORS.md) |
| BOM | [`docs/BOM.csv`](https://github.com/pureheartrobotics/shuxin/blob/hardware/pcb-review-k11c/hardware/carrier_v1/docs/BOM.csv) |
| 布局说明 | [`docs/LAYOUT.md`](https://github.com/pureheartrobotics/shuxin/blob/hardware/pcb-review-k11c/hardware/carrier_v1/docs/LAYOUT.md) |
| 打板参数 | [`docs/FAB.md`](https://github.com/pureheartrobotics/shuxin/blob/hardware/pcb-review-k11c/hardware/carrier_v1/docs/FAB.md) |
| KiCad PCB | `carrier_v1.kicad_pcb` |
| Gerber 包 | `out/carrier_v1_gerbers.zip` |
| 顶视渲染 | `out/board_top.png` |
| 总交接 | [`docs/HARDWARE_PCB_HANDOFF.md`](https://github.com/pureheartrobotics/shuxin/blob/hardware/pcb-review-k11c/docs/HARDWARE_PCB_HANDOFF.md) |

## 本次改动摘要

原先用杜邦跳线的线束口，全部改为 **XH2.54 直针座**：

| 新位号 | 规格 | 替代原用途 |
|--------|------|------------|
| J_UART | XH2.54-3P | K11C↔S3 串口杜邦 |
| J_CTRL_AB | XH2.54-8P | D24A A/B/STBY 控制杜邦 |
| J_CTRL_CD | XH2.54-8P | D24A C/D/5V 控制杜邦 |
| J_ENC_A/B/C/D | 各 XH2.54-4P | 四轮编码杜邦 |
| J_SERVO_PAN/TILT | 各 XH2.54-3P | 舵机线 |
| J_TOF | XH2.54-4P | ToF I2C |

**未改成 XH（本来就不是杜邦线束）：**

- P1：K11C 30Pin 扩展排针  
- P2/P3：S3 DevKit 母座  
- JBAT XT60、电源端子  

## 请你重点核对

1. XH 针序是否与你手头线束习惯一致（尤其舵机：信号-电源-地）  
2. J_CTRL_AB / CD 与 D24A J4/J6 是否方便做线  
3. 是否还需要保留「整排 P1 排线」还是日常只插 J_UART + J_TOF  
4. 封装按市售 **XH2.54（2.54 mm）**；不要买成稀有 2.50 mm 正宗 JST 却硬插  

## 打样

Gerber 仍可交嘉立创光板；焊接时用 XH2.54 针座 + 对应胶壳端子线。
