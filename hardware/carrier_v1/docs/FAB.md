# 打板说明 Carrier V1.4

## 建议参数（首板）

| 项 | 值 |
|----|-----|
| 层数 | 2 |
| 尺寸 | **170 × 120 mm** |
| 板厚 | 1.6 mm |
| 铜厚 | 1 oz（电源 Power netclass 1.6 mm + 铺铜） |
| 阻焊 | 绿油白字 |
| 表面 | HASL 有铅或无铅 |
| 最小线宽/间距 | 信号 0.2 / 0.2 mm；VBAT/VM/V_SERVO **1.6 mm** |
| 过孔 | ≥ 0.4 / 0.8 mm |
| 安装孔 | M3 **NPTH** 3.2 mm（勿选镀铜） |
| 工程版本 | Title **Carrier V1.4** / Revision **E** |

## Gerber

`out/carrier_v1_gerbers.zip` — 嘉立创 / JLCPCB 直接上传。

## 装配顺序

1. 电源路径 D1→F1→SW1→Buck，空载测 VM / 8.4 V  
2. 插 S3（确认 P2/P3 间距 22.86）；JP1 视烧录拔掉  
3. K11C UART / 编码器  
4. 舵机与 ToF  

## 验收

- [ ] USB 烧录 S3（JP1 开路）  
- [ ] P2-20 为 DIN2（示波器/蜂鸣测固件脚）  
- [ ] 四轮方向与 `config.h` 一致  
- [ ] 舵机只吃 8.4 V  
- [ ] ToF `i2cdetect` 可见  
