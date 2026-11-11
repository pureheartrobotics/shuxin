# shuxin 互连载板 Carrier V1

这是**普通 FR4 互连板**（把 K11C / ESP32-S3 DevKit / D24A / 电源 / 舵机 / ToF 用座子和排线固定），**不是**芯片封装用的 IC substrate。

## 设计目标

1. 去掉杜邦线，信号与电源走板内铜皮  
2. MCU 与驱动**先继续用现成模组**（DevKit + D24A），降低一次改板风险  
3. 脚位与车上固件冻结表一致：`ESP32S3_D24A_SHUXIN/main/config.h`  
4. 烧录安全：`JP1` 断开 D24A→S3 的 5V  

## 目录

| 路径 | 内容 |
|------|------|
| `docs/CONNECTORS.md` | **主真值**：各连接器脚位 |
| `docs/nets.csv` | 网表摘要 |
| `docs/BOM.csv` | 物料 |
| `docs/FAB.md` | 打板参数与叠层注意 |
| `carrier_v1.kicad_*` | KiCad 8 工程（由 `gen/make_kicad_project.py` 生成） |

## 系统关系

```text
电池 → 保险/开关 → VM
                 ├─ K11C 12V
                 ├─ D24A VIN（电机）
                 └─ Buck 8.4V → 两舵机

K11C 30Pin ──UART7── ESP32-S3 DevKit ──控制/编码── D24A
         └──I2C3── VL53L5CX
```

## 使用步骤

1. 读 `docs/CONNECTORS.md`，对照实车确认 K11C 为 **V1.2（3.3 V 扩展脚）**  
2. 安装 [KiCad 8+](https://www.kicad.org/)，打开 `carrier_v1.kicad_pro`  
3. 在原理图里把框式标注替换为 `Connector_Generic` 符号与真实封装（或按 BOM 选座）  
4. 布局：大电流左侧电源，右侧信号；GND 星点靠近 D24A  
5. DRC 通过后按 `docs/FAB.md` 下单 2 层板  

重新生成 KiCad 骨架：

```bash
python hardware/carrier_v1/gen/make_kicad_project.py
```

## 明确不做（V1）

- 不画 RK3566 / ESP32 核心电路（用模组）  
- 不把 TB6612 功率级硬集成进载板（D24A 仍外挂；V2 可再并）  
- 不接 K11C DEBUG UART（Pin25/27）  

## 固件对应

S3：`ESP32S3_D24A_SHUXIN/`（四轮正交 + 左右 trim）  
Android：`android-app/` UART `/dev/ttyS7` @ 115200  
产品交接总览：`docs/HARDWARE_PCB_HANDOFF.md`
