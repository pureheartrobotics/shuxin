# ESP32-C3下位机 + 双路TB6612 D153C

本版结合 `SHUXIN-esp32-2.0.3-button-ble/main/boards/jc4827w543-tb6612/jc4827w543_tb6612.cc` 中的 `Tb6612Chassis` 与五个 `self.chassis.*` 语音工具，移植成独立ESP-IDF工程。支持前进、后退、原地左转、原地右转、停止。

你提供的语音源码当前sdkconfig目标为ESP32-S3，屏幕板使用GPIO14/15/16等C3不能照用的引脚。因此本包的 `main/` 是给 **C3烧录的下位机**；`shuxin_bridge/` 是可选的 **原S3语音工程串口适配文件**，不要将整套S3屏幕/语音工程直接烧进C3。本包不在C3上运行语音识别，也没有把BLE配网改成BLE遥控。

原资料与源码未修改。本版按A=左轮、B=右轮安排；左右转采用原地差速转向，与原源码一致。

## 1. 保留的行为

| 项目 | 本版行为 |
|---|---|
| PWM | 10kHz、10位，沿用原源码 |
| 默认占空比 | 70%，可通过命令设为0～100% |
| 前进 | 左轮前进、右轮前进 |
| 后退 | 左轮后退、右轮后退 |
| 左转 | 左轮后退、右轮前进 |
| 右转 | 左轮前进、右轮后退 |
| 停止 | 短路刹车50ms，随后STBY=0高阻待机 |
| 运动超时 | 4秒没有新有效运动命令，自动刹车后待机 |
| 上电 | 保持待机，不自动转动 |

同方向重复命令仅更新占空比和超时，不反复切断PWM。改变方向时先关闭STBY再切换引脚，并留2ms电气间隔；这个间隔不代表车轮机械上已停稳，测试时先停车再反向。采用单任务维护运动与刹车截止时间，避免旧刹车定时回调中止新动作。

占空比不是实际转速，原地转向时间也不能直接换算角度。本版没有编码器PID、里程计或电池ADC采样。

## 2. D153C控制电平：使用3.3V到5V转换

提供的D153C V1.0/V1.1原理图均把TB6612FNG的VCC（20脚）接 **5V**，芯片手册第5页规定控制输入与STBY的高电平最小值为0.7×VCC，也就是3.5V。C3的3.3V输出不能保证达到这个门限。

本版接线使用两片 **SN74AHCT125**，由D153C的5V输出供电，把七个控制信号非反相转换到5V。两片14脚接5V、7脚接公共GND，每片电源脚附近放100nF去耦电容。使用的通道/OE接GND，输入端各用10kΩ下拉到GND；D153C侧STBY也用10kΩ下拉，确保ESP重启或转换器未供电时不意外使能。第二片未使用通道输入接GND、/OE接5V、输出悬空。接线前核对所购封装数据手册。

| AHCT125通道 | 输入脚A | 输出脚Y | /OE脚 |
|---|---|---|---|
| 1 | 2 | 3 | 1 |
| 2 | 5 | 6 | 4 |
| 3 | 9 | 8 | 10 |
| 4 | 12 | 11 | 13 |

不要用普通HC125直接替代AHCT125，其输入门限不同。D153C的3V3输出、V1.1插座编码器电源3.3V，都不等于TB6612的逻辑电源3.3V。不得将ESP的3V3与模块5V相连；转换器断电时避免ESP持续输出高电平。

## 3. 控制线接线表

GPIO数字对应C3 SuperMini的数字丝印。七根控制线均经过上面的转换器。

| ESP32-C3 | 缓冲器 | D153C丝印 | V1.1原理图H1脚号 |
|---|---|---|---|
| GPIO0 | 第一片通道1 | PWMA | 7 |
| GPIO1 | 第一片通道2 | AIN1 | 5 |
| GPIO3 | 第一片通道3 | AIN2 | 6 |
| GPIO4 | 第一片通道4 | PWMB | 1 |
| GPIO5 | 第二片通道1 | BIN1 | 3 |
| GPIO6 | 第二片通道2 | BIN2 | 2 |
| GPIO7 | 第二片通道3 | STBY | 4 |
| GND | 直接共地 | GND | — |

H1针脚号用于核对原理图；实际按丝印与1脚标记连接，不能只凭插座朝向数针。避开GPIO2/8/9启动配置引脚，GPIO20/21用于上位机UART，USB18/19不占用。GPIO4～7被占用后不能同时用于外部JTAG。

电机A接AO1/AO2（AOUT1/AOUT2），电机B接BO1/BO2（BOUT1/BOUT2），或使用板上相应6P电机插座。编码器与ADC本版不连接。使用电机插座时先核对电机线序，不能混接电机线与编码器电源/信号。

电池接驱动模块标记的输入端正负极，按电机额定电压选择电池；原理图“12V输出”端不是输入端。TB6612推荐VM最高13.5V，15V为绝对最大额定值。电机持续与堵转电流必须符合驱动能力；资料中的1.2A平均、3.2A峰值不表示可以长期堵转。

首次测试：C3由USB供电，D153C由电池供电，模块5V输出仅给转换器供电，所有地共接。独立运行可用模块5V给C3的5V端供电，避免USB5V和模块5V同时直接并联。

## 4. 电机方向校准

沿用原源码的镜像安装方式：`main/config.h` 默认 `MOTOR_INVERT_A=false`、`MOTOR_INVERT_B=true`。

| 动作 | AIN1/AIN2 | BIN1/BIN2 |
|---|---|---|
| 前进 | 1/0 | 0/1 |
| 后退 | 0/1 | 1/0 |
| 左转 | 0/1 | 0/1 |
| 右转 | 1/0 | 1/0 |

架空车轮发送 `F 25`：若左轮后退，改变 `MOTOR_INVERT_A`；若右轮后退，改变 `MOTOR_INVERT_B`。确认A实际是左轮、B实际是右轮。不能只看GPIO真值判断实车前后方向，电机线序与安装方向都会影响结果。

## 5. USB或RK3566串口命令

USB与UART两路都可接收命令，最后收到的有效命令生效。操作时选择一个控制来源，避免两边互相覆盖。

每条命令必须以换行结束，字母区分大小写。115200、8N1。

| 命令 | 行为 |
|---|---|
| `F` | 默认70%前进，最长4秒 |
| `B` | 后退 |
| `L` | 原地左转 |
| `R` | 原地右转 |
| `S` | 停止 |
| `F 25` | 25%前进 |
| `L 40` | 40%原地左转 |
| `F 0` | 停止 |
| `self.chassis.go_forward 25` | 与`F 25`相同 |
| `self.chassis.go_back` | 与`B`相同 |
| `self.chassis.turn_left` | 与`L`相同 |
| `self.chassis.turn_right` | 与`R`相同 |
| `self.chassis.stop` | 与`S`相同 |

有效命令返回 `OK moving`、`OK braking` 或 `OK stopped`，表示下位机已接受并设置驱动状态，不是车轮运动反馈。不合法命令返回 `ERR COMMAND`，不刷新超时；超长行或含NUL的行丢弃至下一个换行，返回 `ERR LINE`。超时停机不主动发串口消息。

测试USB时，用普通串口工具打开C3的USB串口并发送命令，可接受LF或CRLF行尾。首次低占空比、架空测试；小占空比可能不足以克服静摩擦，不转时缓慢增加。

RK3566连接：板上 **3.3V TTL UART TX → C3 GPIO20（RX）**，**RX ← C3 GPIO21（TX）**，GND共地。不经过电机控制的5V转换器。RK的具体端口与针脚按板型确认，不能连接RS232/RS485/5V TTL。

RK示例使用Python pyserial，`/dev/ttyS4`仅为占位端口，替换成你的实际串口：

```python
import serial, time
with serial.Serial('/dev/ttyS4', 115200, timeout=0.2) as port:
    try:
        for command in (b'F 25\n', b'B 25\n', b'L 25\n', b'R 25\n'):
            port.write(command)
            time.sleep(0.5)
            port.write(b'S\n')
            time.sleep(0.3)
    finally:
        port.write(b'S\n')
        port.flush()
```

连续运动每100ms重发当前命令即可刷新4秒超时。上位机退出时主动发送S，不依赖超时。若希望更短的断线停止时间，修改 `MOTION_TIMEOUT_US`，并同步修改上位机重发周期。

## 6. 编译与下载C3

使用 **ESP-IDF 5.5.4**（本地已安装版本），不使用Arduino IDE。打开ESP-IDF终端并进入本包根目录：

```text
idf.py set-target esp32c3
idf.py build
idf.py -p COM实际端口 flash monitor
```

例如端口是COM6，将最后一条替换为 `idf.py -p COM6 flash monitor`。第一次无法进入下载模式时，按住BOOT，按一下RESET，松开BOOT，再下载。

本工程默认4MB Flash、USB Serial/JTAG控制台。USB命令收发使用原生USB驱动；不要在同一端口同时打开监视器和另一个串口软件。

`firmware/` 中附本次已成功编译的C3固件。若不改引脚或方向，可直接烧录；若修改配置，重新编译后使用新固件。在ESP-IDF终端进入 `firmware/`，将COM6替换为实际端口：

```text
python -m esptool --chip esp32c3 -p COM6 -b 460800 write_flash "@flash_args"
```

使用图形烧录工具时：`bootloader/bootloader.bin`地址0x0，`partition_table/partition-table.bin`地址0x8000，`esp32c3_d153c_shuxin.bin`地址0x10000；Flash配置DIO、80MHz、4MB。应用bin不能单独烧到0x0。

## 7. 可选：让原SHUXIN语音工程控制C3

若仍用当前JC4827W543 ESP32-S3屏幕语音板作上位机，将本包 `shuxin_bridge/uart_chassis.h` 和 `shuxin_bridge/jc4827w543_tb6612.cc` 复制到原工程 `main/boards/jc4827w543-tb6612/`，备份再替换同名.cc文件。**本次没有修改你的原工程。**

生成的.cc保留原屏幕、触摸、音频初始化和五个MCP工具，只把本地TB6612类换成串口适配类。原config.h可继续使用；其中原电机GPIO宏不再控制电机。S3上的七根原TB6612控制线需移除，电机驱动改接C3。

| 原S3屏幕板 | C3 |
|---|---|
| P2 GPIO5，TX | GPIO20，RX |
| P2 GPIO9，RX | GPIO21，TX |
| GND | GND |

适配文件显式使用UART1、GPIO5/9；这两个引脚在该板原config.h里用于电机控制，未用于显示/音频/触摸。这里是3.3V TTL直连，不能接5V转换器。不要占用原工程已经给麦克风使用的GPIO43/44。若用其他S3板型，必须重新检查可用串口引脚，本替换.cc仅针对当前JC4827W543 TB6612板型。

原语音工具名保持 `self.chassis.go_forward/go_back/turn_left/turn_right/stop`。返回 `command_sent` 仅表示上位机成功发送字节，`execution_confirmed=false`；此适配器没有等待C3回复，不把发送成功当成电机执行反馈。原语音调用发一次动作最长运行4秒，没有自动无限续期。

串口适配代码已用原工程的真实编译配置通过语法检查，未完整重建和链接原大型S3工程。当前源码sdkconfig选择的是JC4827W543 TB6612板型；复制后保持该板型重新编译。本替换文件不适用于未选中该板型的构建。

## 8. 参考与验证

本地依据：原Tb6612Chassis、D153C V1.0/V1.1原理图、TB6612FNG芯片手册、ESP32-C3引脚图。软件构建及模拟测试结果见 `验证说明.md`。电机方向、实际PWM波形、电平转换和负载表现仍需上板验证。

- [SuperMini引脚说明](https://www.nologo.tech/product/esp32/esp32c3/esp32c3supermini/esp32C3SuperMiniFoot.html)
- [Espressif ESP-IDF 5.5.4 C3 LEDC接口](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32c3/api-reference/peripherals/ledc.html)
- [Espressif ESP-IDF 5.5.4 C3 UART接口](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32c3/api-reference/peripherals/uart.html)
- [TI SN74AHCT125规格与数据手册](https://www.ti.com/product/SN74AHCT125)
