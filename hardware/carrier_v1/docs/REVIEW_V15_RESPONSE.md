# Carrier V1.5 / Rev F — 对 V1.5 复审 P0（GND 浮岛）的回应

对照：`Carrier_V1.5_评审报告.md`。

## P0：GND 铺铜岛屿（已修）

根因：FreeRouting 在 B.Cu 编码器排下方走 **+3V3**（y≈86–92），把 `J_ENC_*` 地焊盘和 DevKit 地切成浮岛；`post_fix_power` 原先只删重建铺铜，不做护城河规避。

修复：

1. `build_board_v14.py`：在编码器下加 **B.Cu track keepout**（允许铺铜/过孔，禁止信号走线）
2. `post_fix_power.py`：若 FreeRouting 仍穿过 keepout，**只清扫 +3V3**（不清 ENC 信号，避免断线）；P3-1 北向 F.Cu 缝合；JP1 `S3_5V` 用 B.Cu BFS 接到 P2/TP5 树

### DRC（KiCad 10.0.8，`--refill-zones --severity-all`）

| 项 | 结果 |
|----|------|
| **焊盘 unconnected** | **0**（评审要求的「不是只有碎块↔碎块」——PTH/ENC/DevKit 地均入主平面） |
| `shorting_items` | **0** |
| `tracks_crossing` | **0** |
| `clearance` | **0** |
| severity=error（电气） | **0** |
| unconnected（铺铜碎块↔碎块 / VM 碎块） | 3 条，**无焊盘** |
| 其余 | 丝印 overlap/edge、isolated_copper、text_height 等 warning |

## V1.5 评审小项

| 项 | 状态 |
|----|------|
| BOM JVM/JK11 Value → MKDS | ✅ `docs/BOM.csv` 已为 `MKDS 1,5/2-G-5,0` |
| D1 散热实测 | ⏳ 打样后满载摸温 |
| 丝印越界/字高 | 不挡功能；嘉立创可能提示 |
| 170×120 壳体 | ⏳ 仍待卡尺量壳体 |

## 7 条必做（V1.4→V1.5，保持）

| # | 结果 |
|---|------|
| 1 铺铜重建 | ✅ 四块 F.Cu 电源岛 + B.Cu GND |
| 2 换 D1 | ✅ SR20100 DO-201AD |
| 3 courtyard | ✅ 0 重叠 |
| 4 电源端子防呆 | ✅ JBAT=XT60；其余 MKDS |
| 5 cam/ + 顶视图 | ✅ 已删；`out/board_top.svg/pdf` 已刷新 |
| 6 3V3 双源 | ✅ P2-1/2 NC |
| 7 机械 | ⏳ 等壳体 |

## 交付物

- 板：`hardware/carrier_v1/carrier_v1.kicad_pcb`
- Gerber：`hardware/carrier_v1/out/carrier_v1_gerbers.zip`
- 顶视图：`out/board_top.svg` / `board_top.pdf`
- 脚本：`gen/build_board_v14.py`、`gen/run_freerouting.py`、`gen/post_fix_power.py`
