#!/usr/bin/env bash
# 舒心语音 demo 的日常 Docker 重部署/启动。
# 保留挂载数据: data/、models/、samples/、outputs/。
#
# Windows: 需要 Git for Windows（Git Bash）+ Docker Desktop。
# 在项目根目录、原生盘符路径下执行（如 C:/Users/.../shuxin）:
#   bash scripts/redeploy_docker.sh

if [[ -z "${BASH_VERSION:-}" ]]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROJECT_NAME="${PROJECT_NAME:-shuxin}"
SERVICE="${SERVICE:-shuxin-voice-demo}"
IMAGE="${IMAGE:-shuxin-voice-demo:latest}"
DEPS_HASH_FILE="${DEPS_HASH_FILE:-data/docker_deps.hash}"
FORCE_BUILD=0
NO_BUILD=0
DEPS_MODULES=(
  "voice-heavy requirements-voice-heavy.txt"
  "voice-app requirements-voice-app.txt"
)

for arg in "$@"; do
  case "$arg" in
    --build) FORCE_BUILD=1 ;;
    --no-build) NO_BUILD=1 ;;
    -h|--help)
      echo "用法: bash scripts/redeploy_docker.sh [--build|--no-build]"
      exit 0
      ;;
    *) echo "[redeploy] 未知参数: $arg" >&2; exit 1 ;;
  esac
done

if [[ "$FORCE_BUILD" -eq 1 && "$NO_BUILD" -eq 1 ]]; then
  echo "[redeploy] --build 与 --no-build 不能同时使用" >&2
  exit 1
fi

info() { echo -e "\033[1;32m[redeploy]\033[0m $*"; }
warn() { echo -e "\033[1;33m[redeploy] 警告:\033[0m $*" >&2; }
error() { echo -e "\033[1;31m[redeploy] 错误:\033[0m $*" >&2; exit 1; }

check_deps() {
  command -v docker >/dev/null 2>&1 || error "未找到 docker，请安装 Docker Desktop"
  docker compose version >/dev/null 2>&1 || error "未找到 docker compose，请安装带 Compose v2 的 Docker Desktop"
  docker info >/dev/null 2>&1 || error "Docker 未运行，请启动 Docker Desktop 后重试"
  command -v awk >/dev/null 2>&1 || error "未找到 awk，请使用完整版 Git for Windows"
  if ! command -v sha256sum >/dev/null 2>&1 \
      && ! command -v shasum >/dev/null 2>&1 \
      && ! command -v python >/dev/null 2>&1; then
    error "需要 sha256sum、shasum 或 python 来计算依赖 hash"
  fi
}

if grep -q $'\r' "$0" 2>/dev/null; then
  warn "脚本含 CRLF 换行，请执行: git checkout -- scripts/redeploy_docker.sh"
fi

check_deps

mkdir -p data models samples outputs

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  warn "已从 .env.example 创建 .env"
fi

if [[ ! -f data/devices.yaml && -f data/devices.yaml.example ]]; then
  cp data/devices.yaml.example data/devices.yaml
  warn "已从示例创建 data/devices.yaml"
fi

info "检查 docker compose 配置 ..."
docker compose -p "$PROJECT_NAME" config >/dev/null

hash_file() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
  else
    python - "$path" <<'PY'
import hashlib, sys
print(hashlib.file_digest(open(sys.argv[1], "rb"), "sha256").hexdigest())
PY
  fi
}

current_deps_hash() {
  local module path hash
  for entry in "${DEPS_MODULES[@]}"; do
    module="${entry%% *}"
    path="${entry#* }"
    hash="$(hash_file "$path")"
    echo "$module $hash $path"
  done
}

changed_deps_modules() {
  local current previous entry module path hash old_hash changed=()
  current="$1"
  previous="$2"

  if [[ -z "$previous" ]]; then
    return 0
  fi

  # 旧部署可能只存一行汇总 hash；视为未知依赖布局，报告全部模块有变更。
  if [[ "$previous" != *$'\n'* && "$previous" != *" "* ]]; then
    for entry in "${DEPS_MODULES[@]}"; do
      changed+=("${entry%% *}")
    done
    printf "%s" "${changed[*]}"
    return 0
  fi

  while read -r module hash path; do
    [[ -n "$module" ]] || continue
    old_hash="$(awk -v target="$module" '$1 == target {print $2}' <<<"$previous")"
    if [[ "$old_hash" != "$hash" ]]; then
      changed+=("$module")
    fi
  done <<<"$current"

  printf "%s" "${changed[*]}"
}

tier_for_module() {
  case "$1" in
    voice-heavy) echo heavy ;;
    voice-app) echo app ;;
    *) echo unknown ;;
  esac
}

format_changed_tiers() {
  local modules="$1" module tier
  local heavy=() app=() unknown=()

  for module in $modules; do
    tier="$(tier_for_module "$module")"
    case "$tier" in
      heavy) heavy+=("$module") ;;
      app) app+=("$module") ;;
      *) unknown+=("$module") ;;
    esac
  done

  local parts=()
  if ((${#heavy[@]})); then
    parts+=("heavy(${heavy[*]})")
  fi
  if ((${#app[@]})); then
    parts+=("app(${app[*]})")
  fi
  if ((${#unknown[@]})); then
    parts+=("unknown(${unknown[*]})")
  fi

  local IFS=' '
  printf "%s" "${parts[*]}"
}

CURRENT_HASH="$(current_deps_hash)"
PREVIOUS_HASH=""
if [[ -f "$DEPS_HASH_FILE" ]]; then
  PREVIOUS_HASH="$(<"$DEPS_HASH_FILE")"
fi

BUILD_REASON=""
if [[ "$NO_BUILD" -eq 1 ]]; then
  info "已指定 --no-build，跳过构建"
elif [[ "$FORCE_BUILD" -eq 1 ]]; then
  BUILD_REASON="已请求 --build"
elif ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  BUILD_REASON="未找到镜像: $IMAGE"
elif [[ -n "$PREVIOUS_HASH" && "$PREVIOUS_HASH" != "$CURRENT_HASH" ]]; then
  CHANGED_MODULES="$(changed_deps_modules "$CURRENT_HASH" "$PREVIOUS_HASH")"
  CHANGED_TIERS="$(format_changed_tiers "$CHANGED_MODULES")"
  BUILD_REASON="依赖 tier 变更: ${CHANGED_TIERS:-${CHANGED_MODULES:-unknown}}"
elif [[ -z "$PREVIOUS_HASH" ]]; then
  info "未找到依赖 hash 文件；镜像已存在，跳过重建"
fi

if [[ -n "$BUILD_REASON" ]]; then
  info "构建 Docker 镜像（${BUILD_REASON}）..."
  DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose -p "$PROJECT_NAME" build "$SERVICE"
  printf "%s\n" "$CURRENT_HASH" > "$DEPS_HASH_FILE"
else
  info "仅代码变更，跳过依赖层构建"
  if [[ -z "$PREVIOUS_HASH" ]]; then
    printf "%s\n" "$CURRENT_HASH" > "$DEPS_HASH_FILE"
  fi
fi

info "重建并启动 voice 服务 ..."
docker compose -p "$PROJECT_NAME" up -d --force-recreate "$SERVICE"

info "重部署完成，挂载的运行时数据已保留。"
