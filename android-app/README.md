# 初心 K11C 语音客户端（Android）

量产带屏车上位机。连现网或实验室 Voice BFF，Opus 实时上下行。口令开车走云端 MCP，Android 经 UART7 把 `F/B/L/R/S` 发给 MCU（C3 二驱或 S3 四驱）。头部另发 `HEAD` / `NOD` / `SHAKE`。MCU 未接或串口打不开时自动改模拟，轮子和舵机都不会动。开机先显示商标，约两秒后进入脸。语音可环顾四周、拍照存相册、点头摇头。

## 装到板上

1. 在电脑上编译：

```powershell
cd F:\shuxin\android-app
$env:ANDROID_HOME = "F:\shuxin\.android-sdk"
$env:JAVA_HOME = (Get-Command java).Source | Split-Path | Split-Path
.\gradlew.bat :app:assembleDebug
```

2. 安装并设成这台板子的唯一界面（开机就是初心的脸，不要先落到安卓桌面再点 Open）：

```powershell
cd F:\shuxin
powershell -File scripts\kiosk_kickpi.ps1
```

脚本会装 APK、预授权麦克风和摄像头（避免开机弹出「是否允许」）、把初心设成 HOME，并尽量设成 device-owner。刷完安卓、**还没添加账号**时设 owner 最稳，之后重启不再出现启动器选择框。板上已经有用户时 owner 可能失败，HOME 仍然生效。

手动等价：

```powershell
$adb = "F:\shuxin\RKDevTool_v3.30_for_window\RKDevTool_v3.30_for_window\bin\adb.exe"
& $adb install -r -g app\build\outputs\apk\debug\app-debug.apk
& $adb shell pm grant cn.shuxin.car android.permission.RECORD_AUDIO
& $adb shell pm grant cn.shuxin.car android.permission.CAMERA
& $adb shell cmd package set-home-activity cn.shuxin.car/.MainActivity
& $adb shell dpm set-device-owner cn.shuxin.car/.KioskAdminReceiver
& $adb shell am start -n cn.shuxin.car/.MainActivity
```

3. 实验室密钥仍走右上角连点五下；量产机应已写入 `device_code` / `device_secret`，打开即连 Voice。不要填网页测试台的 `demo-device-001`。电机显示「模拟」时，说「往前走一点」只会改屏幕文字。显示 `ttyS7` 时才会真下发。

## 接线（K11C V1.2 + C3）

- UART：**Pin 17 TX → C3 GPIO20 RX**，**Pin 15 RX ← C3 GPIO21 TX**，GND 共地。3.3 V TTL，不要 5V 转换。
- 电机：C3 七根控制线经 SN74AHCT125 上 D153C；VM 走电池 Y 线，**不要**从 K11C 12V 小口取电。
- 首次务必架空轮子，低占空比试 `前进`。C3 烧 `esp32_c3/ESP32C3_D153C_SHUXIN`；四驱 S3 烧 `esp32_s3/ESP32S3_D24A_SHUXIN`（需含 `HEAD/NOD/SHAKE`）。
- 颈部 MG996R 红线只要 5–6V，不要接 12V。S3：水平 GPIO1、俯仰 GPIO2。C3：水平 GPIO10、俯仰 GPIO8。
- 上位机退出会发 `S`。底盘自己还有 4 秒无命令超时停车。舵机指令不停车。
