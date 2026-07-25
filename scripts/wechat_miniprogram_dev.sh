#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/apps/wechat-miniprogram"
MODE="${1:-dev}"
DEFAULT_API_BASE="https://shuxinzzx.com.cn"
DEFAULT_APPID="wxda3acb8842b5c9f4"
# DEFAULT_API_BASE="http://localhost:8765"

read_env_var() {
  local key="$1"
  local env_file="$ROOT_DIR/.env"
  if [ ! -f "$env_file" ]; then
    return 1
  fi
  local line
  line="$(grep -E "^${key}=" "$env_file" | tail -n 1 || true)"
  if [ -z "$line" ]; then
    return 1
  fi
  echo "${line#*=}" | sed 's/^["'\'']//;s/["'\'']$//'
}

resolve_appid() {
  if [ -n "${WECHAT_MINIPROGRAM_APPID:-}" ]; then
    echo "$WECHAT_MINIPROGRAM_APPID"
    return
  fi
  local from_env
  from_env="$(read_env_var WECHAT_MINIPROGRAM_APPID || true)"
  if [ -n "$from_env" ]; then
    echo "$from_env"
    return
  fi
  from_env="$(read_env_var SHUXIN_WECHAT_APPID || true)"
  if [ -n "$from_env" ]; then
    echo "$from_env"
    return
  fi
  echo "$DEFAULT_APPID"
}

APPID="$(resolve_appid)"

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
  for page in pages/index/index pages/mall/index pages/profile/profile pages/login/login pages/prov/ble; do
    for ext in wxml js json wxss; do
      if [ ! -f "$out_dir/$page.$ext" ]; then
        echo "Build output is missing $page.$ext in $out_dir"
        missing=1
      fi
    done
  done
  for prov_file in security1.js provision-client.js ble-transport.js; do
    if [ ! -f "$out_dir/pages/prov/esp-idf-prov/$prov_file" ]; then
      echo "Build output is missing pages/prov/esp-idf-prov/$prov_file in $out_dir"
      missing=1
    fi
  done
  if [ "$missing" -ne 0 ]; then
    exit 1
  fi
  if grep -q 'usingComponents' "$out_dir/pages/index/index.json" 2>/dev/null \
    && grep -q 'MbtiRevealModal\|PrivacyGate' "$out_dir/pages/index/index.json" 2>/dev/null; then
    echo "pages/index/index.json still references external components; WSL DevTools may fail to load the page."
    exit 1
  fi
  if [ -f "$out_dir/pages/prov/ble.json" ] \
    && grep -q 'PrivacyGate' "$out_dir/pages/prov/ble.json" 2>/dev/null; then
    echo "pages/prov/ble.json still references PrivacyGate; restart dev server after a clean rebuild."
    exit 1
  fi
}

patch_project_appid() {
  local dir="$1"
  local appid="$2"
  local cfg="$dir/project.config.json"
  if [ ! -f "$cfg" ]; then
    return 0
  fi
  python3 - "$cfg" "$appid" <<'PY'
import json
import sys

path, appid = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)
data["appid"] = appid
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY
}

generate_miniprogram_configs() {
  sed "s/__WECHAT_MINIPROGRAM_APPID__/$APPID/g" \
    "$APP_DIR/project.config.example.json" > "$APP_DIR/project.config.json"
  sed "s/__WECHAT_MINIPROGRAM_APPID__/$APPID/g" \
    "$APP_DIR/src/manifest.example.json" > "$APP_DIR/src/manifest.json"
}

patch_dist_appids() {
  local patched=0
  for out_dir in "$APP_DIR/dist/build/mp-weixin" "$APP_DIR/dist/dev/mp-weixin"; do
    if [ -f "$out_dir/project.config.json" ]; then
      patch_project_appid "$out_dir" "$APPID"
      patched=1
    fi
  done
  if [ "$patched" -eq 1 ]; then
    echo "AppID patched in dist/build/mp-weixin and/or dist/dev/mp-weixin"
  fi
}

sync_build_to_dev() {
  local build_dir="$APP_DIR/dist/build/mp-weixin"
  local dev_dir="$APP_DIR/dist/dev/mp-weixin"
  rm -rf "$dev_dir"
  mkdir -p "$(dirname "$dev_dir")"
  cp -a "$build_dir" "$dev_dir"
  echo "Synced build → dist/dev/mp-weixin (matches project.config miniprogramRoot)"
}

print_build_hints() {
  local local_mode="$1"
  echo ""
  echo "Build OK. API baked: $API_BASE"
  echo "AppID: $APPID (root + dist/*/mp-weixin/project.config.json)"
  echo "Import in WeChat DevTools: $APP_DIR or $APP_DIR/dist/dev/mp-weixin"
  if [ "$local_mode" = "1" ]; then
    echo "DevTools: 详情 → 本地设置 → 勾选「不校验合法域名…」"
    echo "支付 notify 仍走 trycloudflare（SHUXIN_WXPAY_NOTIFY_URL）；tunnel 变更只需 redeploy，无需重编小程序"
  else
    echo "WeChat DevTools: 改 API 地址后须重新 build 并在工具内点「编译」"
    echo "若仍显示旧 AppID，删除工具内旧项目后重新导入"
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

generate_miniprogram_configs

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
  patch_project_appid "$APP_DIR/dist/build/mp-weixin" "$APPID"
  if [ "$LOCAL_BUILD" != "1" ]; then
    check_no_stale_localhost "$APP_DIR/dist/build/mp-weixin"
  fi
  check_page_outputs "$APP_DIR/dist/build/mp-weixin"
  sync_build_to_dev
  patch_project_appid "$APP_DIR/dist/dev/mp-weixin" "$APPID"
  check_page_outputs "$APP_DIR/dist/dev/mp-weixin"
  print_build_hints "$LOCAL_BUILD"
else
  echo "Open in WeChat DevTools: $APP_DIR/dist/dev/mp-weixin"
  clean_dev_output
  VITE_SHUXIN_API_BASE="$API_BASE" pnpm dev:mp-weixin
  if [ "$LOCAL_BUILD" != "1" ]; then
    check_no_stale_localhost "$APP_DIR/dist/dev/mp-weixin"
  fi
fi
