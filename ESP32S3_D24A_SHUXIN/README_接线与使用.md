# ESP32-S3 + D24A 四路电机驱动

车上 Android 仍发 `F/B/L/R/S`（ttyS7、115200）。本版 GPIO 按实车接线表。

- C：左前  PWM GPIO9，CIN1 GPIO10，CIN2 GPIO11
- B：右前  PWM GPIO7，BIN1 GPIO15，BIN2 GPIO16
- D：左后  PWM GPIO12，DIN1 GPIO21，DIN2 GPIO14
- A：右后  PWM GPIO4，AIN1 GPIO5，AIN2 GPIO6
- STBY：GPIO8
- 串口：K11C TX → GPIO18（S3 RX），K11C RX ← GPIO17（S3 TX）

PWM 10kHz/10位，默认 70%，4 秒无命令自动停。左侧=C+D，右侧=B+A；右侧 A/B 默认反相。

## 接线

| D24A | 信号 | S3 |
|---|---|---|
| J4-2 | STBY | 左 12 GPIO8 |
| J4-4 | PWMA | 左 4 GPIO4 |
| J4-6 | AIN1 | 左 5 GPIO5 |
| J4-8 | AIN2 | 左 6 GPIO6 |
| J4-3 | PWMB | 左 7 GPIO7 |
| J4-5 | BIN1 | 左 8 GPIO15 |
| J4-7 | BIN2 | 左 9 GPIO16 |
| J6-4 | PWMC | 左 17 GPIO9 |
| J6-6 | CIN1 | 左 18 GPIO10 |
| J6-8 | CIN2 | 左 19 GPIO11 |
| J6-3 | PWMD | 左 20 GPIO12 |
| J6-5 | DIN1 | 右 18 GPIO21 |
| J6-7 | DIN2 | 右 19 GPIO14 |

ToF 已迁 K11C。S3 四轮正交编码：
- A 右后 E1A/E1B→GPIO46/3；B 右前 E2A/E2B→GPIO38/13
- C 左前 E3A/E3B→GPIO47/41；D 左后 E4A/E4B→GPIO42/39
- 勿接 GPIO48(RGB)、19/20(USB)、33–37(PSRAM)；闭环左=C+D、右=B+A；`ENC`/`ENC R`

烧录：拔掉 D24A 的 5V，USB 接电脑。在 `firmware/` 目录：

```text
python -m esptool --chip esp32s3 -p COMx -b 460800 write_flash "@flash_args"
```
