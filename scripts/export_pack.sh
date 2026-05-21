#!/usr/bin/env bash
# Pack the ShuXin voice demo code and runtime volumes.
#
# Usage:
#   bash scripts/export_pack.sh [output_dir]
#
# This bundle does not include Docker images. The target host must be able to
# run docker compose build.

if [[ -z "${BASH_VERSION:-}" ]]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROJECT_NAME="${PROJECT_NAME:-shuxin_voice_demo}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${1:-${HOME}/shuxin_voice_export}"
WORK_DIR="${OUT_DIR}/shuxin_voice_pack_${TIMESTAMP}"
BUNDLE="${OUT_DIR}/shuxin_voice_bundle_${TIMESTAMP}.tar.gz"

info() { echo -e "\033[1;32m[pack]\033[0m $*"; }
warn() { echo -e "\033[1;33m[pack] WARN:\033[0m $*" >&2; }
error() { echo -e "\033[1;31m[pack] ERROR:\033[0m $*" >&2; exit 1; }

check_deps() {
  for cmd in tar date hostname du; do
    command -v "$cmd" >/dev/null 2>&1 || error "'$cmd' not found"
  done
}

pack_code() {
  info "Step 1/5  Packing code ..."
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

pack_data() {
  info "Step 2/5  Packing data ..."
  if [[ -d data ]]; then
    tar czf "${WORK_DIR}/data.tar.gz" \
      --exclude='devices.yaml.example' \
      -C "$ROOT_DIR" data
    info "  data.tar.gz $(du -sh "${WORK_DIR}/data.tar.gz" | cut -f1)"
  else
    warn "data/ not found, skipping"
  fi
}

pack_models() {
  info "Step 3/5  Packing models ..."
  if [[ -d models ]] && find models -type f ! -name '.gitkeep' | grep -q .; then
    tar czf "${WORK_DIR}/models.tar.gz" -C "$ROOT_DIR" models
    info "  models.tar.gz $(du -sh "${WORK_DIR}/models.tar.gz" | cut -f1)"
  else
    warn "models/ has no model files, skipping models.tar.gz"
  fi
}

pack_samples() {
  info "Step 4/5  Packing samples ..."
  if [[ -d samples ]]; then
    tar czf "${WORK_DIR}/samples.tar.gz" -C "$ROOT_DIR" samples
    info "  samples.tar.gz $(du -sh "${WORK_DIR}/samples.tar.gz" | cut -f1)"
  else
    warn "samples/ not found, skipping"
  fi
}

bundle() {
  info "Step 5/5  Writing bundle metadata ..."
  cat > "${WORK_DIR}/BUNDLE_INFO.txt" <<EOF
ShuXin Voice Demo Bundle
========================
Packed at    : ${TIMESTAMP}
Packed host  : $(hostname)
Packed path  : ${ROOT_DIR}
Project name : ${PROJECT_NAME}
Includes image: no

Files:
$(ls -lh "${WORK_DIR}" | tail -n +2)

Restore:
  bash scripts/import_deploy.sh ${BUNDLE}
EOF

  tar czf "$BUNDLE" -C "$WORK_DIR" .
  rm -rf "$WORK_DIR"
  info ""
  info "Bundle created: ${BUNDLE}"
  info "Bundle size   : $(du -sh "$BUNDLE" | cut -f1)"
}

main() {
  info "ShuXin voice demo pack (${TIMESTAMP})"
  check_deps
  mkdir -p "$WORK_DIR"
  pack_code
  pack_data
  pack_models
  pack_samples
  bundle
}

main "$@"
