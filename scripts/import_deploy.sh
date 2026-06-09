#!/usr/bin/env bash
# 在目标主机恢复并部署舒心语音 demo 迁移包。
#
# 用法:
#   bash scripts/import_deploy.sh <bundle.tar.gz> [安装目录]
#
# 安装目录默认为当前目录，可用 INSTALL_DIR 环境变量覆盖。
# 优先级: 第二参数 > INSTALL_DIR > $(pwd)
#
# 恢复代码、bind mount、Postgres（pg_restore）、Qdrant 存储卷，
# 然后执行 redeploy_docker.sh --build 启动全栈。

if [[ -z "${BASH_VERSION:-}" ]]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

info() { echo -e "\033[1;32m[deploy]\033[0m $*"; }
warn() { echo -e "\033[1;33m[deploy] 警告:\033[0m $*" >&2; }
error() { echo -e "\033[1;31m[deploy] 错误:\033[0m $*" >&2; exit 1; }

BUNDLE="${1:-}"
[[ -n "$BUNDLE" ]] || {
  echo "用法: bash scripts/import_deploy.sh <bundle.tar.gz> [安装目录]" >&2
  exit 1
}
[[ -f "$BUNDLE" ]] || error "未找到迁移包: $BUNDLE"
[[ -z "${3:-}" ]] || error "参数过多"

TARGET_DIR="${2:-${INSTALL_DIR:-$(pwd)}}"
INSTALL_DIR="$(cd "$TARGET_DIR" 2>/dev/null && pwd)" || error "无效的安装目录: $TARGET_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
EXTRACT_DIR="/tmp/shuxin_voice_import_${TIMESTAMP}"

cleanup() {
  rm -rf "$EXTRACT_DIR"
}
trap cleanup EXIT

check_deps() {
  for cmd in docker tar; do
    command -v "$cmd" >/dev/null 2>&1 || error "未找到命令 '$cmd'"
  done
  docker compose version >/dev/null 2>&1 || error "未找到 docker compose v2"
  docker info >/dev/null 2>&1 || error "Docker 未运行"
}

warn_existing_install() {
  if [[ -f "${INSTALL_DIR}/docker-compose.yml" ]]; then
    warn "安装目录已有 docker-compose.yml，导入将覆盖项目文件"
  fi
}

extract_bundle() {
  info "步骤 1/8  解包 ..."
  mkdir -p "$EXTRACT_DIR"
  tar xzf "$BUNDLE" -C "$EXTRACT_DIR"
  if [[ -f "${EXTRACT_DIR}/BUNDLE_INFO.txt" ]]; then
    sed 's/^/    /' "${EXTRACT_DIR}/BUNDLE_INFO.txt"
  fi
}

restore_code() {
  info "步骤 2/8  恢复代码到 ${INSTALL_DIR} ..."
  [[ -f "${EXTRACT_DIR}/code.tar.gz" ]] || error "迁移包中缺少 code.tar.gz"
  mkdir -p "$INSTALL_DIR"
  tar xzf "${EXTRACT_DIR}/code.tar.gz" -C "$INSTALL_DIR" --strip-components=1
  cd "$INSTALL_DIR"
  # shellcheck source=lib/docker_compose.sh
  source "${INSTALL_DIR}/scripts/lib/docker_compose.sh"
}

_restore_host_archive() {
  local archive="$1"
  local host_dir="$2"
  [[ -f "$archive" ]] || return 0
  local parent
  parent="$(dirname "$host_dir")"
  mkdir -p "$parent"
  tar xzf "$archive" -C "$parent"
}

restore_volumes() {
  info "步骤 3/8  恢复 data/models/samples/outputs ..."
  if [[ -f .env ]]; then
    load_host_data_dirs
  else
    SHUXIN_HOST_DATA_DIR="./data"
    SHUXIN_HOST_MODELS_DIR="./models"
    SHUXIN_HOST_SAMPLES_DIR="./samples"
    SHUXIN_HOST_OUTPUTS_DIR="./outputs"
  fi
  mkdir -p \
    "$SHUXIN_HOST_DATA_DIR" \
    "$SHUXIN_HOST_MODELS_DIR" \
    "$SHUXIN_HOST_SAMPLES_DIR" \
    "$SHUXIN_HOST_OUTPUTS_DIR"

  _restore_host_archive "${EXTRACT_DIR}/data.tar.gz" "$SHUXIN_HOST_DATA_DIR"
  if [[ -f "${EXTRACT_DIR}/models.tar.gz" ]]; then
    _restore_host_archive "${EXTRACT_DIR}/models.tar.gz" "$SHUXIN_HOST_MODELS_DIR"
  else
    warn "缺少 models.tar.gz，STT 前需自行准备模型"
  fi
  _restore_host_archive "${EXTRACT_DIR}/samples.tar.gz" "$SHUXIN_HOST_SAMPLES_DIR"
  _restore_host_archive "${EXTRACT_DIR}/outputs.tar.gz" "$SHUXIN_HOST_OUTPUTS_DIR"

  if [[ ! -f "${SHUXIN_HOST_DATA_DIR}/devices.yaml" && -f "${SHUXIN_HOST_DATA_DIR}/devices.yaml.example" ]]; then
    cp "${SHUXIN_HOST_DATA_DIR}/devices.yaml.example" "${SHUXIN_HOST_DATA_DIR}/devices.yaml"
    warn "已从示例创建 devices.yaml，chat-audio 前请填写真实 API 配置"
  elif [[ ! -f "${SHUXIN_HOST_DATA_DIR}/devices.yaml" && -f data/devices.yaml.example ]]; then
    cp data/devices.yaml.example "${SHUXIN_HOST_DATA_DIR}/devices.yaml"
    warn "已从仓库示例创建 ${SHUXIN_HOST_DATA_DIR}/devices.yaml"
  fi
}

init_env() {
  info "步骤 4/8  初始化 .env ..."
  if [[ ! -f .env ]]; then
    cp .env.example .env
    warn "已从 .env.example 创建 .env，chat-audio 前请填写 DEMO_LLM_API_KEY 等密钥"
  else
    info "  .env 已存在"
  fi
}

restore_postgres() {
  [[ -f "${EXTRACT_DIR}/postgres.dump" ]] || {
    warn "缺少 postgres.dump，已跳过 DB 恢复（redeploy 将使用全新 Postgres）"
    return 0
  }

  info "步骤 5/8  从 dump 恢复 Postgres ..."
  compose_cmd up -d postgres
  load_postgres_env
  if ! wait_postgres_healthy 60; then
    error "postgres 未就绪，无法 pg_restore"
  fi

  compose_cmd exec -T postgres pg_restore \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-acl \
    < "${EXTRACT_DIR}/postgres.dump" || warn "pg_restore 有警告（空库首次恢复时可能正常）"
  info "  Postgres 恢复完成"
}

restore_qdrant() {
  [[ -f "${EXTRACT_DIR}/qdrant_storage.tar.gz" ]] || {
    warn "缺少 qdrant_storage.tar.gz，已跳过 Qdrant 恢复（redeploy 将使用全新向量库）"
    return 0
  }

  info "步骤 6/8  恢复 Qdrant 存储卷 ..."
  local vol
  vol="$(compose_volume shuxin_qdrant_data)"
  compose_cmd up -d qdrant
  compose_cmd stop qdrant
  docker run --rm \
    -v "${vol}:/dest" \
    -v "${EXTRACT_DIR}:/backup:ro" \
    alpine sh -c 'rm -rf /dest/* /dest/.[!.]* 2>/dev/null; tar xzf /backup/qdrant_storage.tar.gz -C /dest'
  compose_cmd up -d qdrant
  info "  Qdrant 存储恢复完成"
}

redeploy_stack() {
  info "步骤 7/8  构建镜像并启动全栈 ..."
  bash scripts/redeploy_docker.sh --build
}

verify_health() {
  info "步骤 8/8  检查语音服务健康状态 ..."
  load_voice_port
  local url="http://127.0.0.1:${VOICE_DEMO_PORT}/health"
  local max=30 i=0

  while [[ "$i" -lt "$max" ]]; do
    if command -v curl >/dev/null 2>&1 && curl -sf "$url" >/dev/null 2>&1; then
      info "  健康检查通过: ${url}"
      return 0
    fi
    if docker exec shuxin-voice-demo-pg python -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=2)" \
        >/dev/null 2>&1; then
      info "  健康检查通过: ${url}"
      return 0
    fi
    sleep 2
    i=$((i + 1))
  done

  warn "健康检查超时: ${url}，服务可能仍在启动"
  warn "请检查: docker compose -p ${PROJECT_NAME} ps"
}

finish() {
  load_voice_port
  info ""
  info "部署完成。"
  info "  安装目录 : ${INSTALL_DIR}"
  info "  语音测试台: http://localhost:${VOICE_DEMO_PORT}/voice-demo"
  warn "请编辑 .env 填入真实 API 密钥，然后在安装目录执行: bash scripts/redeploy_docker.sh"
}

main() {
  info "舒心语音 demo 部署 (${TIMESTAMP})"
  info "安装目录: ${INSTALL_DIR}"
  check_deps
  warn_existing_install
  extract_bundle
  restore_code
  restore_volumes
  init_env
  restore_postgres
  restore_qdrant
  redeploy_stack
  verify_health
  finish
}

main "$@"
