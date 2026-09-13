# RK3566 语音控车 — 电子同事对接说明

面向：底盘 / 音频 / 板端 Linux。  
软件分支：`feature/rk3566`。ESP32 固件协议仍在 `master`，本板不跑那套。

目标：车上说话 → 云端听写成字 → **板端立刻开车**。网页 `/voice-demo` 只聊天，不会动轮子。

---

## 1. 分工

| 谁 | 做什么 |
|----|--------|
| 软件 | 语音客户端、口令解析、调用 `drive.sh` |
| 电子 | `drive.sh` 里接真实电机；麦/喇叭 ALSA；板子能上网到语音服务器 |
| 不要 | 不要在板子上存 DeepSeek / 腾讯 ASR / 火山 TTS 的 Key |

---

## 2. 板上准备

系统：RK3566 Linux（Debian/Ubuntu 均可），Python 3.11+。

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv alsa-utils
cd /opt/shuxin   # 或你们放代码的目录
python3 -m venv .venv
source .venv/bin/activate
pip install -r apps/rk3566/requirements.txt
chmod +x apps/rk3566/scripts/drive.sh
```

用 `arecord -l` / `aplay -l` 确认默认麦和喇叭。不对就改 `--alsa-device`（例如 `plughw:0,0`）。

---

## 3. 连语音服务器

板子和跑 Docker 的电脑要在同一局域网。电脑上先确认：

```text
http://<电脑局域网IP>:8765/health
```

应返回 `{"status":"ok",...}`。

`device_code` / `device_secret` 向软件要（Admin「加载设备」或后台设备页），不要用网页随便猜。

```bash
export SHUXIN_VOICE_WS_URL=ws://<电脑局域网IP>:8765/ws/voice
export SHUXIN_DEVICE_CODE=<device_id>
export SHUXIN_DEVICE_SECRET=<device_secret>
```

先不接电机，确认语音通：

```bash
python apps/rk3566/run.py --live --seconds 4 --loop --debug
```

对着车说「往前走一点」。日志里要有：

```text
STT: 往前走一点
voice motion forward duration=0.80s
chassis forward ...
```

此时还是 mock，**轮子不会转**，只有日志。

---

## 4. 接电机（你们要实现的部分）

软件调用：

```bash
apps/rk3566/scripts/drive.sh {action} {duration} {speed}
```

| 参数 | 含义 |
|------|------|
| `action` | `forward` `backward` `left` `right` `spin` `stop` |
| `duration` | 秒，如 `0.80`；`stop` 为 `0` |
| `speed` | `0.00`～`1.00`，口头「快/慢」会变 |

模板在 `apps/rk3566/scripts/drive.sh`。把 `TODO` 换成 GPIO / 串口 / 驱动板协议。

约定：

1. **`stop` 立刻刹车**，然后退出码 0。
2. 其它动作：**跑满 duration 后自己停**，再退出 0。
3. 进程被 SIGTERM 时立刻刹车（用户说「停」会杀掉上一条）。
4. 先把车架空或限流，避免第一次 PWM 写反冲出去。

接上后：

```bash
export SHUXIN_CHASSIS=cmd
export SHUXIN_CHASSIS_CMD='/opt/shuxin/apps/rk3566/scripts/drive.sh {action} {duration} {speed}'
python apps/rk3566/run.py --live --seconds 4 --loop --debug
```

不接语音、只试电机：

```bash
./apps/rk3566/scripts/drive.sh forward 0.80 0.55
./apps/rk3566/scripts/drive.sh stop 0 0
```

---

## 5. 口令（软件已实现）

| 说 | action |
|----|--------|
| 前进 / 往前走 / 过来 | `forward` |
| 后退 / 往后 / 倒车 | `backward` |
| 左转 / 向左转 | `left` |
| 右转 / 向右转 | `right` |
| 转一圈 / 掉头 | `spin` |
| 停 / 停下 / 别动 | `stop`（马上打断） |
| …一点 / 一下 | duration ≈ 0.8s |
| …两秒 | duration = 2s（最长 4s） |

普通聊天（「你好初心」）不会开车。

---

## 6. 怎么判断真的动了

| 日志 | 含义 |
|------|------|
| `voice motion backward ...` | 口令解析成功 |
| `chassis cmd ['.../drive.sh', 'backward', '0.80', '0.55']` | 已经调用你们的脚本 |
| 只有 `chassis backward` 没有 `chassis cmd` | 还在 mock，没设 `SHUXIN_CHASSIS=cmd` |
| 网页 voice-demo 的 `agent/delta` 括弧动作 | 那是说话演戏，**不是电机** |

---

## 7. 常见问题

- **连不上 8765**：用电脑局域网 IP，不要用 `127.0.0.1`（那是板子自己）。电脑防火墙放行 8765。
- **hello 失败**：设备未绑定，或 secret 错。找软件从 Admin 复制。
- **有 STT 但没 chassis cmd**：检查环境变量是否 export 到同一终端。
- **脚本跑了车不停**：`stop` 和 SIGTERM 里必须断电；不要只 `echo`。
- **麦没声**：`arecord -d 2 -f S16_LE -r 16000 -c 1 /tmp/t.wav && aplay /tmp/t.wav`

软件接口问题找 `apps/rk3566/`；电机不转先查 `drive.sh` 和电源/驱动板。
