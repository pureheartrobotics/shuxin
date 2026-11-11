# ESP32-S3 下位机 + D24A 四路 TB6612

车上 Android 仍发 `F/B/L/R/S`（ttyS7、115200）。S3 把左右轮命令映射到四路电机：A/C 左侧，B/D 右侧。不跑语音。

| 动作 | 左 A/C | 右 B/D |
|---|---|---|
| F 前进 | 前进 | 前进 |
| B 后退 | 后退 | 后退 |
| L 左转 | 后退 | 前进 |
| R 右转 | 前进 | 后退 |
| S 停止 | 短路刹车 50ms，再 STBY=0 |

PWM 10kHz/10位，默认 70%，4 秒无新命令自动停。上电待机。

## 接线（与已接排针对齐）

电源：12V 电池 Y 分 → K11C DC 与 D24A VIN；D24A J1 的 5V → S3 右 21；GND 以 D24A 为星点。不要 USB 与模块 5V 同时供，不要 3V3 互连。

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

K11C Pin17 TX → S3 左 11 GPIO18；Pin15 RX ← 左 10 GPIO17。

电机：A 前左、B 前右、C 后左、D 后右。不要接到编码器针。

## 烧录

已编译的 bin 在 `firmware/`。先拔掉 D24A 到 S3 的 5V，只留 USB（CH340 那个口，不要和模块 5V 同时供）。轮子架空。

在 `firmware/` 目录：

```text
python -m esptool --chip esp32s3 -p COMx -b 460800 --before default_reset --after hard_reset write_flash --flash_mode dio --flash_size 16MB --flash_freq 80m 0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin 0x10000 esp32s3_d24a_shuxin.bin
```

进不了下载模式时：按住 BOOT，点一下 RESET，松开 BOOT。

烧完拔 USB，再接回模块 5V。发 `F 25` 看四轮方向；左轮反了改 `MOTOR_INVERT_A`/`C`，右轮反了改 `B`/`D`。

有效命令回 `OK moving` / `OK braking` / `OK stopped`。
