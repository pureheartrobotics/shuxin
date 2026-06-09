#!/usr/bin/env bash
# 舒心语音 demo 的日常 Docker 重部署/启动。
# 保留挂载数据: data/、models/、samples/、outputs/。
#
# Windows/WSL: 需要 Docker Desktop，并对当前 WSL 发行版开启 integration。
# 启动前验证 daemon（勿用 docker info | head -5，Client 段无法说明已连上）:
#   docker info 2>&1 | grep -E "Server Version|Cannot connect"
# 在项目根目录执行:
#   bash scripts/redeploy_docker.sh

if [[ -z "${BASH_VERSION:-}" ]]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck source=lib/docker_compose.sh
source "${ROOT_DIR}/scripts/lib/docker_compose.sh"

PROJECT_NAME="${PROJECT_NAME:-shuxin}"
SERVICE="${SERVICE:-shuxin-voice-demo}"
IMAGE="${IMAGE:-shuxin-voice-demo:latest}"
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
      cat <<'EOF'
用法: bash scripts/redeploy_docker.sh [--build|--no-build]

环境变量:
  COMPOSE_FILE   默认 docker-compose.yml；生产可设
                 docker-compose.yml:docker-compose.prod.yml
  SHUXIN_HOST_*  见 .env.example（阶段 A 大磁盘 bind mount）
EOF
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

load_host_data_dirs
info "数据目录: data=${SHUXIN_HOST_DATA_DIR} outputs=${SHUXIN_HOST_OUTPUTS_DIR}"
DEPS_HASH_FILE="${DEPS_HASH_FILE:-${SHUXIN_HOST_DATA_DIR}/docker_deps.hash}"
mkdir -p "$SHUXIN_HOST_DATA_DIR" "$SHUXIN_HOST_MODELS_DIR" "$SHUXIN_HOST_SAMPLES_DIR" "$SHUXIN_HOST_OUTPUTS_DIR"

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  warn "已从 .env.example 创建 .env"
fi

if [[ ! -f "${SHUXIN_HOST_DATA_DIR}/devices.yaml" ]]; then
  if [[ -f "${SHUXIN_HOST_DATA_DIR}/devices.yaml.example" ]]; then
    cp "${SHUXIN_HOST_DATA_DIR}/devices.yaml.example" "${SHUXIN_HOST_DATA_DIR}/devices.yaml"
    warn "已从示例创建 ${SHUXIN_HOST_DATA_DIR}/devices.yaml"
  elif [[ -f data/devices.yaml.example ]]; then
    cp data/devices.yaml.example "${SHUXIN_HOST_DATA_DIR}/devices.yaml"
    warn "已从仓库 data/devices.yaml.example 创建 ${SHUXIN_HOST_DATA_DIR}/devices.yaml"
  fi
fi

info "检查 docker compose 配置 ..."
compose_cmd config >/dev/null

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
  DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 compose_cmd build "$SERVICE"
  printf "%s\n" "$CURRENT_HASH" > "$DEPS_HASH_FILE"
else
  info "仅代码变更，跳过依赖层构建"
  if [[ -z "$PREVIOUS_HASH" ]]; then
    printf "%s\n" "$CURRENT_HASH" > "$DEPS_HASH_FILE"
  fi
fi

info "启动依赖服务（postgres、qdrant）..."
compose_cmd up -d postgres qdrant

info "重建并启动 voice 服务（--no-deps: 保持 postgres/qdrant 健康）..."
compose_cmd up -d --force-recreate --no-deps "$SERVICE"

QDRANT_PORT="${QDRANT_HTTP_PORT:-6335}"
if [[ -f .env ]]; then
  _env_port="$(grep -E '^QDRANT_HTTP_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
  [[ -n "$_env_port" ]] && QDRANT_PORT="$_env_port"
fi
if [[ "$QDRANT_PORT" == "6335" ]]; then
  warn "生产部署前请将 .env 中 QDRANT_HTTP_PORT 改为 6333（见 docs/DEPLOY_SERVER.md）"
fi

if [[ "$SHUXIN_HOST_DATA_DIR" != "./data" || "$SHUXIN_HOST_OUTPUTS_DIR" != "./outputs" ]]; then
  info "宿主机数据目录: data=${SHUXIN_HOST_DATA_DIR} outputs=${SHUXIN_HOST_OUTPUTS_DIR}"
fi
info "重部署完成，挂载的运行时数据已保留。"
info "Qdrant 控制台（若已映射端口）: http://localhost:${QDRANT_PORT}/dashboard"
