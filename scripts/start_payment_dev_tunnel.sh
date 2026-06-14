#!/usr/bin/env bash
# 本地微信支付联调：cloudflared 隧道 + 更新 .env 中的 NOTIFY_URL（小程序 API 仍连 localhost）
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
LOCAL_PORT="${LOCAL_PORT:-8765}"
LOG_FILE="${LOG_FILE:-/tmp/shuxin-cloudflared.log}"
PID_FILE="${PID_FILE:-/tmp/shuxin-cloudflared.pid}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "错误: 未找到 $1。请先安装 cloudflared。" >&2
    echo "  curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb" >&2
    echo "  sudo dpkg -i /tmp/cloudflared.deb" >&2
    exit 1
  fi
}

update_env_notify_url() {
  local tunnel_url="$1"
  local notify_url="${tunnel_url%/}/api/payment/notify"
  python3 - "$ENV_FILE" "$notify_url" <<'PY'
import re
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
notify_url = sys.argv[2]
text = env_path.read_text(encoding="utf-8")
key = "SHUXIN_WXPAY_NOTIFY_URL="
if key in text:
    text = re.sub(r"^SHUXIN_WXPAY_NOTIFY_URL=.*$", f"{key}{notify_url}", text, flags=re.M)
else:
    text = text.rstrip() + f"\n{key}{notify_url}\n"
env_path.write_text(text, encoding="utf-8")
print(notify_url)
PY
}

stop_existing() {
  if [[ -f "$PID_FILE" ]]; then
    local old_pid
    old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
      kill "$old_pid" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$PID_FILE"
  fi
}

wait_for_tunnel_url() {
  local attempts=0
  while (( attempts < 30 )); do
    if [[ -f "$LOG_FILE" ]]; then
      local url
      url="$(grep -a -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$LOG_FILE" | head -1 || true)"
      if [[ -n "$url" ]]; then
        echo "$url"
        return 0
      fi
    fi
    sleep 1
    attempts=$((attempts + 1))
  done
  echo "错误: 未从 cloudflared 日志中解析到 trycloudflare.com 地址。查看 $LOG_FILE" >&2
  return 1
}

main() {
  require_cmd cloudflared
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "错误: 未找到 $ENV_FILE" >&2
    exit 1
  fi

  if ! curl -fsS "http://127.0.0.1:${LOCAL_PORT}/health" >/dev/null 2>&1; then
    echo "警告: http://127.0.0.1:${LOCAL_PORT}/health 不可达。"
    echo "请先启动 voice 服务，例如: bash scripts/redeploy_docker.sh"
  fi

  stop_existing
  : >"$LOG_FILE"
  cloudflared tunnel --url "http://127.0.0.1:${LOCAL_PORT}" >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"

  tunnel_url="$(wait_for_tunnel_url)"
  notify_url="$(update_env_notify_url "$tunnel_url")"

  echo ""
  echo "cloudflared 已启动 (pid $(cat "$PID_FILE"))"
  echo "  隧道:    $tunnel_url"
  echo "  回调:    $notify_url"
  echo "  日志:    $LOG_FILE"
  echo ""
  echo "下一步:"
  echo "  bash scripts/redeploy_docker.sh --skip-build"
  echo ""
  echo "小程序（DevTools 本地联调）:"
  echo "  API 固定 http://localhost:8765，仅首次或改源码时:"
  echo "  WECHAT_MINIPROGRAM_APPID=你的AppID bash scripts/wechat_miniprogram_dev.sh build-local"
  echo "  tunnel 换域名后不必重编小程序；notify 已写入 .env"
  echo ""
  echo "停止隧道: kill \$(cat $PID_FILE)"
}

main "$@"
