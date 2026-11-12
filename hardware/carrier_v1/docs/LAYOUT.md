# Carrier V1.3 布局（XH2.54 线束）

板框：**160 × 110 mm**，双层。

## 分区

| 区域 | 内容 |
|------|------|
| 左 | 电源 JBAT/F1/SW1/JVM/JK11/UBUCK/JP1 |
| 中左 | P1 K11C 排针 + **J_UART** XH2.54-3P |
| 中右 | P2/P3 S3 DevKit 母座 |
| 右 | **J_SERVO_*** XH-3P、**J_TOF** XH-4P |
| 下 | **J_ENC_A…D** XH-4P；**J_CTRL_AB/CD** XH-8P |

## 布线

`gen/run_freerouting.py`（FreeRouting）。改封装后需重跑。

## 丝印

`harness=XH2.54` · `JP1 off when USB-flash S3`
