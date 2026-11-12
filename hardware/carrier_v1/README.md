# shuxin 互连载板 Carrier V1.4（JST XH 2.50）

这是**普通 FR4 互连板**（K11C / S3 DevKit 排针座 + **线束 JST XH 2.50 mm**），**不是**芯片封装 substrate。

- 对 V1.3 评审的逐条回应：`docs/REVIEW_V14_RESPONSE.md`
- 连接器真值：`docs/CONNECTORS.md`

## 设计目标

1. 去掉杜邦线，信号与电源走板内铜皮  
2. MCU 与驱动**先继续用现成模组**（DevKit + D24A）  
3. 脚位与 `ESP32S3_D24A_SHUXIN/main/config.h` 一致（**DIN2 = GPIO14 = P2-20**）  
4. 烧录安全：`JP1` 断开 `+5V_LOGIC`→`S3_5V`  

## 目录

| 路径 | 内容 |
|------|------|
| `docs/CONNECTORS.md` | 各连接器脚位 |
| `docs/REVIEW_V14_RESPONSE.md` | 评审 21 条对照 |
| `docs/BOM.csv` | 物料（含 MPN 意向） |
| `docs/FAB.md` | 打板参数 |
| `docs/nets.csv` | 网表摘要 |
| `carrier_v1.kicad_*` | KiCad 工程（已布线） |
| `out/carrier_v1_gerbers.zip` | Gerber 包 |
| `gen/build_board_v14.py` | V1.4 重建脚本 |
| `gen/run_freerouting.py` | FreeRouting |
| `gen/post_fix_power.py` | 铺铜 refill |

## 系统关系

```text
电池 → D1(SS54) → 保险/开关 → VM
                              ├─ K11C 12V
                              ├─ D24A VIN
                              └─ Buck 8.4V → 舵机

K11C 30Pin ──UART── ESP32-S3 DevKit ──CTRL/ENC── D24A
         └──I2C3── VL53L5CX
```

## 重建

```bash
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" hardware/carrier_v1/gen/build_board_v14.py
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" hardware/carrier_v1/gen/run_freerouting.py all
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" hardware/carrier_v1/gen/post_fix_power.py
```

## 明确不做（V1.4）

- 不画 RK3566 / ESP32 核心电路  
- 不把 TB6612 功率级硬集成进载板  
- 不接 K11C DEBUG UART（Pin25/27）  

板尺寸 **170×120 mm**，Revision **E**。
