#!/usr/bin/env bash
# RK3566 底盘驱动入口（电子同事实现电机部分）。
# 软件侧调用：
#   drive.sh {action} {duration} {speed}
# action:  forward | backward | left | right | spin | stop
# duration: 秒，两位小数；stop 时为 0
# speed: 0.00~1.00
#
# 约定：
# 1. stop 必须立刻断电/刹车，然后 exit 0。
# 2. 其它动作：按 duration 跑完后自行停车，再 exit 0。
# 3. 收到 SIGTERM/SIGINT 时立刻停车（新口令会取消上一条）。
# 4. 不要在脚本里访问 LLM / ASR / TTS 密钥。

set -euo pipefail

ACTION="${1:-stop}"
DURATION="${2:-0}"
SPEED="${3:-0}"

cleanup() {
  # TODO: 在这里写真实刹车（PWM=0 / 串口 stop）
  echo "[drive] STOP (signal or exit)" >&2
}
trap cleanup EXIT INT TERM

echo "[drive] action=${ACTION} duration=${DURATION} speed=${SPEED}" >&2

case "${ACTION}" in
  stop)
    exit 0
    ;;
  forward|backward|left|right|spin)
    # TODO: 按 ACTION + SPEED 启动电机
    # 例：GPIO / UART / ROS2 都可以，软件不绑定具体芯片。
    sleep "${DURATION}"
    ;;
  *)
    echo "[drive] unknown action: ${ACTION}" >&2
    exit 2
    ;;
esac
