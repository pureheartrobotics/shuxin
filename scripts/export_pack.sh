#!/usr/bin/env bash
# 打包初心语音 demo 的代码、bind mount 与数据库卷。
#
# 用法:
#   bash scripts/export_pack.sh [输出目录]
#
# 迁移包不含 Docker 镜像，目标机需能执行 docker compose build。
# Docker 可用时会包含 Postgres（pg_dump）与 Qdrant 存储卷。

if [[ -z "${BASH_VERSION:-}" ]]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck source=lib/docker_compose.sh
source "${ROOT_DIR}/scripts/lib/docker_compose.sh"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${1:-${HOME}/shuxin_voice_export}"
WORK_DIR="${OUT_DIR}/shuxin_voice_pack_${TIMESTAMP}"
BUNDLE="${OUT_DIR}/shuxin_voice_bundle_${TIMESTAMP}.tar.gz"

POSTGRES_DUMPED=0
QDRANT_PACKED=0

info() { echo -e "\033[1;32m[pack]\033[0m $*"; }
warn() { echo -e "\033[1;33m[pack] 警告:\033[0m $*" >&2; }
error() { echo -e "\033[1;31m[pack] 错误:\033[0m $*" >&2; exit 1; }

check_deps() {
  for cmd in tar date hostname du; do
    command -v "$cmd" >/dev/null 2>&1 || error "未找到命令 '$cmd'"
  done
}

check_docker() {
  command -v docker >/dev/null 2>&1 || return 1
  docker compose version >/dev/null 2>&1 || return 1
  docker info >/dev/null 2>&1 || return 1
  return 0
}

ensure_stack_for_backup() {
  info "步骤 1/8  确保 postgres/qdrant 已启动以便备份 ..."
  compose_cmd up -d postgres qdrant
  load_postgres_env
  if ! wait_postgres_healthy 60; then
    error "postgres 未就绪，无法 pg_dump"
  fi
}

pack_postgres() {
  info "步骤 2/8  导出 Postgres ..."
  load_postgres_env
  compose_cmd exec -T postgres \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
    > "${WORK_DIR}/postgres.dump"
  POSTGRES_DUMPED=1
  info "  postgres.dump $(du -sh "${WORK_DIR}/postgres.dump" | cut -f1)"
}

pack_qdrant_volume() {
  info "步骤 3/8  打包 Qdrant 存储卷 ..."
  local vol
  vol="$(compose_volume shuxin_qdrant_data)"
  compose_cmd stop qdrant
  docker run --rm \
    -v "${vol}:/source:ro" \
    -v "${WORK_DIR}:/backup" \
    alpine tar czf /backup/qdrant_storage.tar.gz -C /source .
  compose_cmd up -d qdrant
  QDRANT_PACKED=1
  info "  qdrant_storage.tar.gz $(du -sh "${WORK_DIR}/qdrant_storage.tar.gz" | cut -f1)"
}

pack_code() {
  info "步骤 4/8  打包代码 ..."
  tar czf "${WORK_DIR}/code.tar.gz" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.pytest_cache' \
    --exclude='.env' \
    --exclude='outputs' \
    --exclude='models' \
    --exclude='data/devices.yaml' \
    -C "$(dirname "$ROOT_DIR")" \
    "$(basename "$ROOT_DIR")"
  info "  code.tar.gz $(du -sh "${WORK_DIR}/code.tar.gz" | cut -f1)"
}

_pack_host_dir() {
  local archive_name="$1"
  local host_dir="$2"
  local exclude="${3:-}"
  local parent base
  if [[ ! -d "$host_dir" ]]; then
    warn "未找到 ${host_dir}，已跳过 ${archive_name}"
    return 0
  fi
  parent="$(cd "$(dirname "$host_dir")" && pwd)"
  base="$(basename "$host_dir")"
  if [[ -n "$exclude" ]]; then
    tar czf "${WORK_DIR}/${archive_name}" --exclude="$exclude" -C "$parent" "$base"
  else
    tar czf "${WORK_DIR}/${archive_name}" -C "$parent" "$base"
  fi
  info "  ${archive_name} $(du -sh "${WORK_DIR}/${archive_name}" | cut -f1) (from ${host_dir})"
}

pack_data() {
  info "步骤 5/8  打包 data ..."
  _pack_host_dir "data.tar.gz" "$SHUXIN_HOST_DATA_DIR" "devices.yaml.example"
}

pack_models() {
  info "步骤 6/8  打包 models ..."
  if [[ -d "$SHUXIN_HOST_MODELS_DIR" ]] \
    && [[ -n "$(find "$SHUXIN_HOST_MODELS_DIR" -type f ! -name '.gitkeep' -print -quit 2>/dev/null)" ]]; then
    _pack_host_dir "models.tar.gz" "$SHUXIN_HOST_MODELS_DIR"
  else
    warn "models/ 无模型文件，已跳过 models.tar.gz"
  fi
}

pack_samples() {
  _pack_host_dir "samples.tar.gz" "$SHUXIN_HOST_SAMPLES_DIR"
}

pack_outputs() {
  if [[ -d "$SHUXIN_HOST_OUTPUTS_DIR" ]] \
    && [[ -n "$(find "$SHUXIN_HOST_OUTPUTS_DIR" -type f -print -quit 2>/dev/null)" ]]; then
    _pack_host_dir "outputs.tar.gz" "$SHUXIN_HOST_OUTPUTS_DIR"
  else
    warn "outputs/ 为空或不存在，已跳过 outputs.tar.gz"
  fi
}

bundle() {
  info "步骤 8/8  写入迁移包元数据 ..."
  local file_list postgres_flag qdrant_flag
  file_list="$(ls -lh "${WORK_DIR}" | tail -n +2)"
  postgres_flag="否"
  qdrant_flag="否"
  [[ "$POSTGRES_DUMPED" -eq 1 ]] && postgres_flag="是"
  [[ "$QDRANT_PACKED" -eq 1 ]] && qdrant_flag="是"
  cat > "${WORK_DIR}/BUNDLE_INFO.txt" <<EOF
初心语音 Demo 迁移包
====================
打包时间     : ${TIMESTAMP}
打包主机     : $(hostname)
项目路径     : ${ROOT_DIR}
Compose 项目 : ${PROJECT_NAME}
包含镜像     : 否
包含 Postgres: ${postgres_flag}
包含 Qdrant  : ${qdrant_flag}

文件列表:
${file_list}

恢复方式:
  mkdir -p ~/shuxin && cd ~/shuxin
  bash scripts/import_deploy.sh ${BUNDLE}
  # 可选: bash scripts/import_deploy.sh ${BUNDLE} /other/path
EOF

  tar czf "$BUNDLE" -C "$WORK_DIR" .
  rm -rf "$WORK_DIR"
  info ""
  info "迁移包已生成: ${BUNDLE}"
  info "大小        : $(du -sh "$BUNDLE" | cut -f1)"
}

main() {
  info "初心语音 demo 打包 (${TIMESTAMP})"
  check_deps
  load_host_data_dirs
  mkdir -p "$WORK_DIR"

  if check_docker; then
    ensure_stack_for_backup
    pack_postgres
    pack_qdrant_volume
  else
    warn "Docker 不可用，已跳过 postgres.dump 与 qdrant_storage.tar.gz"
  fi

  pack_code
  pack_data
  pack_models
  info "步骤 7/8  打包 samples 与 outputs ..."
  pack_samples
  pack_outputs
  bundle
}

main "$@"
