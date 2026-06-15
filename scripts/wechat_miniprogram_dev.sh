#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/apps/wechat-miniprogram"
APPID="${WECHAT_MINIPROGRAM_APPID:-touristappid}"
MODE="${1:-dev}"
DEFAULT_API_BASE="http://localhost:8765"

check_api_base() {
  if ! curl -fsS "$API_BASE/health" >/dev/null; then
    echo "Warning: cannot reach ChuXin voice backend: $API_BASE/health"
    echo "If WeChat DevTools times out, start the backend or override with SHUXIN_API_BASE=http://<host>:8765"
  fi
}

check_no_stale_localhost() {
  local out_dir="$1"
  if grep -R "http://127.0.0.1:8765" "$out_dir" >/dev/null 2>&1; then
    echo "Build output still contains stale http://127.0.0.1:8765 in $out_dir"
    exit 1
  fi
}

clean_dev_output() {
  rm -rf "$APP_DIR/dist/dev/mp-weixin"
}

check_page_outputs() {
  local out_dir="$1"
  local missing=0
  for page in pages/index/index pages/profile/profile pages/login/login; do
    for ext in wxml js json wxss; do
      if [ ! -f "$out_dir/$page.$ext" ]; then
        echo "Build output is missing $page.$ext in $out_dir"
        missing=1
      fi
    done
  done
  if [ "$missing" -ne 0 ]; then
    exit 1
  fi
}

print_build_hints() {
  local local_mode="$1"
  echo ""
  echo "Build OK. API baked: $API_BASE"
  echo "Open in WeChat DevTools: $APP_DIR/dist/build/mp-weixin"
  if [ "$local_mode" = "1" ]; then
    echo "DevTools: 详情 → 本地设置 → 勾选「不校验合法域名…」"
    echo "支付 notify 仍走 trycloudflare（SHUXIN_WXPAY_NOTIFY_URL）；tunnel 变更只需 redeploy，无需重编小程序"
  else
    echo "WeChat DevTools: 改 API 地址后须重新 build 并在工具内点「编译」"
  fi
}

LOCAL_BUILD=0
if [ "$MODE" = "build-local" ]; then
  MODE=build
  LOCAL_BUILD=1
  API_BASE="${SHUXIN_API_BASE:-$DEFAULT_API_BASE}"
else
  API_BASE="${SHUXIN_API_BASE:-$DEFAULT_API_BASE}"
fi

cd "$APP_DIR"

sed "s/__WECHAT_MINIPROGRAM_APPID__/$APPID/g" \
  project.config.example.json > project.config.json

if [ ! -d node_modules ]; then
  echo "node_modules is missing. Run pnpm install manually before starting dev mode."
  exit 1
fi

if [ ! -e node_modules/@dcloudio/uni-components ]; then
  echo "@dcloudio/uni-components is missing. Install it manually before starting dev mode."
  exit 1
fi

echo "ChuXin mini program dev server"
echo "AppID: $APPID"
echo "API: $API_BASE"
check_api_base
if [ "$MODE" = "build" ]; then
  VITE_SHUXIN_API_BASE="$API_BASE" pnpm build:mp-weixin
  if [ "$LOCAL_BUILD" != "1" ]; then
    check_no_stale_localhost "$APP_DIR/dist/build/mp-weixin"
  fi
  check_page_outputs "$APP_DIR/dist/build/mp-weixin"
  print_build_hints "$LOCAL_BUILD"
else
  echo "Open in WeChat DevTools: $APP_DIR/dist/dev/mp-weixin"
  clean_dev_output
  VITE_SHUXIN_API_BASE="$API_BASE" pnpm dev:mp-weixin
  if [ "$LOCAL_BUILD" != "1" ]; then
    check_no_stale_localhost "$APP_DIR/dist/dev/mp-weixin"
  fi
fi
