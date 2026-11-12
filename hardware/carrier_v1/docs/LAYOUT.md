# Carrier V1.2 布局与布线

板框：**160 × 110 mm**，双层，1.6 mm FR4。

## 分区

| 区域 | 内容 |
|------|------|
| 左 | 电源 JBAT / F1 / SW1 / JVM / JK11 / UBUCK / JP1 |
| 中左 | P1 K11C 2×15 |
| 中右 | P2/P3 ESP32-S3 DevKit 双排座（中间留走廊） |
| 右 | P6 舵机、P7 ToF |
| 下左 | P5 编码器 |
| 下右 | P4 D24A 控制（与 P5 错开，避免竖线打架） |

## 布线状态（V1.2）

用 **FreeRouting** 自动布通：

- 连接 incomplete：**0**
- DRC：仅剩丝印压铜警告（可接受）
- 轨迹 / 过孔：见当前 `carrier_v1.kicad_pcb`

重跑：

```bash
python hardware/carrier_v1/gen/make_pcb_layout.py
# KiCad python:
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" hardware/carrier_v1/gen/run_freerouting.py
```

`tools/freerouting.jar` 需自行放入（体积大，未入库）。

## 打板前

1. KiCad 打开工程 → Fill Zones → 再确认 DRC  
2. 按 BOM 换成真实 XT60 / XH / IDC 封装  
3. 导出 Gerber：`out/carrier_v1_gerbers.zip`  
4. 顶视：`out/board_top.png`  
