# Carrier V1.1 布局与布线

板框：**140 × 100 mm**，双层，1.6 mm FR4。

## 分区（自上而下 / 自左而右）

| 区域 | 坐标约 | 器件 |
|------|--------|------|
| 电源 | 左上–左中 | JBAT、F1、SW1、JVM、JK11、UBUCK、JP1 |
| K11C | 中上 | P1 2×15 |
| S3 DevKit | 右上 | P2 左排、P3 右排（USB 朝板外/上方） |
| 舵机 / ToF | 最右 | P6、P7 |
| D24A 线束 | 中下 | P4 控制、P5 编码 |
| 安装孔 | 四角 | H1–H4 M3 |

## 已完成

- 全连接器**落位** + pad **已绑网名**（打开 PCB 可见完整 ratsnest）  
- 板框 140×100、安装孔、丝印分区  
- **GND** 背面整板铺铜 + 电源区正面 GND/VM 铺铜区  

## 待在 KiCad 里完成（布线）

脚本自动走线在排针阵列上会穿焊盘短路，已去掉。请在 PCB 编辑器按 ratsnest 布线（或 FreeRouting）：

1. 电源：VBAT→F1→SW1→VM（粗线/铺铜）→ Buck → V_SERVO  
2. UART + I2C  
3. 编码 → 电机控制（控制可走 B.Cu）→ 舵机 PWM

## 在 KiCad 中打板前

1. 打开 `carrier_v1.kicad_pro` → PCB  
2. **Edit → Fill All Zones**  
3. 完成信号布线 → **DRC**（排针 `solder_mask_bridge` 可按厂规则忽略或缩小焊盘）  
4. 按采购件替换 XT60/XH/IDC 真实封装  
5. 导出 Gerber：已有样例 `cam/` 与 `out/carrier_v1_gerbers.zip`（布完信号后务必重导）  
6. 顶视图：`out/board_top.png`  

## 丝印注意

- `JP1 off when USB-flash S3`  
- `P1-25/27 NC`  
