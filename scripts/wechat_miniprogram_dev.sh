#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/apps/wechat-miniprogram"
APPID="${WECHAT_MINIPROGRAM_APPID:-touristappid}"
MODE="${1:-dev}"
DEFAULT_API_BASE="http://localhost:8765"

check_api_base() {
  if ! curl -fsS "$API_BASE/health" >/dev/null; then
    echo "Warning: cannot reach ShuXin voice backend: $API_BASE/health"
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

API_BASE="${SHUXIN_API_BASE:-$DEFAULT_API_BASE}"

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

echo "ShuXin mini program dev server"
echo "AppID: $APPID"
echo "API: $API_BASE"
check_api_base
if [ "$MODE" = "build" ]; then
  echo "Open in WeChat DevTools: $APP_DIR/dist/build/mp-weixin"
  VITE_SHUXIN_API_BASE="$API_BASE" pnpm build:mp-weixin
  check_no_stale_localhost "$APP_DIR/dist/build/mp-weixin"
  check_page_outputs "$APP_DIR/dist/build/mp-weixin"
else
  echo "Open in WeChat DevTools: $APP_DIR/dist/dev/mp-weixin"
  clean_dev_output
  VITE_SHUXIN_API_BASE="$API_BASE" pnpm dev:mp-weixin
  check_no_stale_localhost "$APP_DIR/dist/dev/mp-weixin"
fi
