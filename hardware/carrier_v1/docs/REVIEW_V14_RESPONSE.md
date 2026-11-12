# Carrier V1.4 对评审报告的逐条回应

来源：`Carrier_V1.3_评审报告`（P0×5 / P1×5 / P2×11）。  
本版工程：`hardware/carrier_v1/`，板号 **V1.4 / Revision E**，尺寸 **170×120 mm**。

电气 DRC（KiCad 10.0.8）：**unconnected=0，short=0，clearance=0**（残留多为丝印重叠 / courtyard=0 库问题）。

## P0

| # | 原问题 | V1.4 处理 |
|---|--------|-----------|
| 1 | S3 无地无电；JP1 两端同网 | P2：`+3V3×2` / `S3_5V` / `GND`；P3：`GND×3`。**JP1 = `+5V_LOGIC` ↔ `S3_5V`**（拔掉才切断） |
| 2 | DIN2 接到 P3-19/GPIO20 | **DIN2 → P2-20（GPIO14）**；P3-19 空；DIN1 → P3-18 |
| 3 | 全板功率 0.2 mm | Netclass **Power** 宽 **1.6 mm**（VBAT/VM/V_SERVO…）+ 铺铜 |
| 4 | ENC_C/D、TOF 的 GND 未连 | 全 XH GND 入网；B.Cu **GND 整板铺铜**；DRC 未连接=0 |
| 5 | BOM 电阻电容无封装 | 板载 **R1–R15（15）+ C_IN/C_SERVO1/2（3）** |

## P1

| # | 原问题 | V1.4 处理 |
|---|--------|-----------|
| 1 | P2–P3 排距 22.0 | **22.86 mm**（DevKit） |
| 2 | XH 按 2.54/1.0 画 | 改用 KiCad **JST XH P2.50mm** 官方封装 |
| 3 | courtyard=0 / 丝印过小 | 库固有；装配按本体尺寸，丝印警告不挡电气 |
| 4 | SW1/F1/UBUCK 封装与 BOM 不符 | BOM 标明 **首板飞线占位** + 真实 MPN 意向 |
| 5 | K11C/D24A 无机械固定 | 增加 **MH_K11C×4、MH_D24A×2（NPTH）** |

## P2（关键已做 / 文档化）

| # | 原问题 | V1.4 |
|---|--------|------|
| 原理图 parity | 仍以 PCB+nets 为真；完整原理图符号待补 |
| NC_DEBUG 短接 | P1-25/27 **不布网** |
| 同族互插 | UART 改 **4P**（针4 NC）；CTRL-CD 用 **卧式 8P** |
| 测试点 | **TP1–TP7** |
| 反接/TVS/去耦 | 已加 **D1 SS54** + 电解；TVS 下版再加 |
| rev / 文档 | 统一 **V1.4 / Rev E**；重写 BOM/FAB/CONNECTORS |
| 丝印功能名 | 座旁丝印 CTRL/ENC/UART/TOF/SERVO |
| BOM 无 MPN | BOM 增加 Manufacturer/MPN、立创提示列 |
| M3 镀铜孔 | **NPTH**（attribute=3） |
| J_UART 双驱 | 仍与 P1 UART 同网（可选只焊其一；文档注明） |
| Gerber Revision | 导出前 TitleBlock Revision=**E** |

## 返工顺序（已执行）

1. `gen/build_board_v14.py` 落位+网表+Power netclass  
2. `gen/run_freerouting.py all`  
3. `gen/post_fix_power.py` 铺铜 refill  
4. `kicad-cli pcb drc` → 0 unconnected / 0 short  
5. 更新文档 + Gerber zip  

## 下单前请再目视

- [ ] DevKit 实物对齐 P2/P3  
- [ ] JST XH **2.50** 壳体（不要买标「XH2.54」的）  
- [ ] JP1 丝印「烧录拔掉」  
- [ ] D1 极性（A←电池，K→保险）  
- [ ] K11C/D24A 安装孔与实物孔距（MH_* 为近似锚点）  
