# RK3566 设备端（本分支）

`master` 继续服务 ESP32 产品。本目录是 RK3566 上的语音客户端：走现有云端 `/ws/voice` 协议，**不在板端保存 LLM / 腾讯 ASR / 火山 TTS 密钥**。

## 现在能做什么

- `hello` 鉴权（Opus 16k 上 / 24k 下）
- 一轮 `listen` → 收 STT / Agent / TTS
- **语音控车**：STT 一出「前进 / 左转 / 停」等口令，板端立刻驱动底盘（不等云端说完）
- 解析 `（括弧动作）` 并打日志，留给屏幕/舵机
- 回复 `factory_verify_ack`
- 开发机用 WAV 闭环；板上用 `arecord` / `aplay`

## 语音移动口令

识别到后默认跑一小段就停，避免一直冲。说「停」会马上打断当前动作。

| 口令例子 | 动作 |
|----------|------|
| 前进 / 往前走 / 过来 | 向前 |
| 后退 / 倒车 | 向后 |
| 左转 / 向左转 | 左转 |
| 右转 / 向右转 | 右转 |
| 转一圈 / 掉头 | 原地转 |
| 停 / 停下 / 别动 | 立即停车 |
| 往前走一点 | 短距（约 0.8s） |
| 快速后退两秒 | 更快、按时长 |

开发机先不接电机，只看解析是否正确：

```powershell
python apps/rk3566/run.py --say 往前走一点
python apps/rk3566/run.py --say 停下
```

真车把电机脚本接上（参数：动作、秒、速度 0~1）：

```bash
export SHUXIN_CHASSIS=cmd
export SHUXIN_CHASSIS_CMD='/opt/car/drive {action} {duration} {speed}'
python apps/rk3566/run.py --live --seconds 4 --loop
```

`{action}` 为 `forward|backward|left|right|spin|stop`。没接电机时默认 `mock`，只打日志。

电子同事真机对接见 [`HARDWARE_HANDOFF.md`](HARDWARE_HANDOFF.md)（电机脚本模板：`scripts/drive.sh`）。

## 开发机（Windows / 已有 Docker 语音服务）

```powershell
pip install -r apps/rk3566/requirements.txt
python apps/rk3566/run.py --input samples/demo.wav --output outputs/rk3566-reply.wav --device-secret <secret> --no-play
```

## RK3566 Linux

```bash
pip install -r apps/rk3566/requirements.txt
sudo apt-get install -y alsa-utils
export SHUXIN_VOICE_WS_URL=ws://<server>:8765/ws/voice
export SHUXIN_DEVICE_CODE=<device_id>
export SHUXIN_DEVICE_SECRET=<secret>
python apps/rk3566/run.py --live --seconds 4 --loop
```

后续会在本分支把 Agent / 陪伴循环迁到板端，云端只保留鉴权、额度与模型网关。ESP32 相关协议与固件文档仍以 `master` 为准。
