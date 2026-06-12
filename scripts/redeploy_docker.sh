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
SKIP_BUILD=0

for arg in "$@"; do
  case "$arg" in
    --build) FORCE_BUILD=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    -h|--help)
      cat <<'EOF'
用法: bash scripts/redeploy_docker.sh [--build|--skip-build]

  （无选项）  默认执行 compose build（Docker 层缓存加速，未变的层秒过）
  --skip-build   跳过镜像构建（仅重启容器，改 .env 后可用）
  --build        强制全量重建（--no-cache，改 apt/pip 层后用）

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

if [[ "$FORCE_BUILD" -eq 1 && "$SKIP_BUILD" -eq 1 ]]; then
  echo "[redeploy] --build 与 --skip-build 不能同时使用" >&2
  exit 1
fi

info() { echo -e "\033[1;32m[redeploy]\033[0m $*"; }
warn() { echo -e "\033[1;33m[redeploy] 警告:\033[0m $*" >&2; }
error() { echo -e "\033[1;31m[redeploy] 错误:\033[0m $*" >&2; exit 1; }

check_deps() {
  command -v docker >/dev/null 2>&1 || error "未找到 docker，请安装 Docker Desktop"
  docker compose version >/dev/null 2>&1 || error "未找到 docker compose，请安装带 Compose v2 的 Docker Desktop"
  docker info >/dev/null 2>&1 || error "Docker 未运行，请启动 Docker Desktop 后重试"
}

if grep -q $'\r' "$0" 2>/dev/null; then
  warn "脚本含 CRLF 换行，请执行: git checkout -- scripts/redeploy_docker.sh"
fi

check_deps

load_host_data_dirs
info "数据目录: data=${SHUXIN_HOST_DATA_DIR} outputs=${SHUXIN_HOST_OUTPUTS_DIR}"
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

if [[ "$SKIP_BUILD" -eq 1 ]]; then
  info "已指定 --skip-build，跳过构建"
elif [[ "$FORCE_BUILD" -eq 1 ]]; then
  info "构建 Docker 镜像（--build，禁用缓存）..."
  DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 compose_cmd build --no-cache "$SERVICE"
else
  info "构建 Docker 镜像（Docker 层缓存加速，Dockerfile/requirements 无变化则秒过）..."
  DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 compose_cmd build "$SERVICE"
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

CONTAINER_ID="$(compose_cmd ps -q "$SERVICE" 2>/dev/null || true)"

if [[ -n "$CONTAINER_ID" ]]; then
  if ! docker exec "$CONTAINER_ID" sh -c 'command -v ffmpeg >/dev/null && ffmpeg -version | head -1'; then
    warn "容器内未检测到 ffmpeg（检查 Dockerfile apt 层是否已 build）"
  fi

  if ! docker exec "$CONTAINER_ID" python -c "from shuxin.voice.opus_codec import opus_available; assert opus_available()"; then
    warn "容器内 opuslib_next 不可用（检查 requirements-voice-app.txt）"
  fi
fi
