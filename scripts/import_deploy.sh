#!/usr/bin/env bash
# Restore and deploy a ShuXin voice demo bundle on a target host.
#
# Usage:
#   bash scripts/import_deploy.sh <bundle.tar.gz>

if [[ -z "${BASH_VERSION:-}" ]]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

BUNDLE="${1:-}"
[[ -n "$BUNDLE" ]] || { echo "Usage: bash scripts/import_deploy.sh <bundle.tar.gz>" >&2; exit 1; }
[[ -f "$BUNDLE" ]] || { echo "[deploy] ERROR: bundle not found: $BUNDLE" >&2; exit 1; }

PROJECT_NAME="${PROJECT_NAME:-shuxin_voice_demo}"
INSTALL_DIR="${INSTALL_DIR:-/opt/shuxin-voice-demo}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
EXTRACT_DIR="/tmp/shuxin_voice_import_${TIMESTAMP}"

info() { echo -e "\033[1;32m[deploy]\033[0m $*"; }
warn() { echo -e "\033[1;33m[deploy] WARN:\033[0m $*" >&2; }
error() { echo -e "\033[1;31m[deploy] ERROR:\033[0m $*" >&2; exit 1; }

cleanup() {
  rm -rf "$EXTRACT_DIR"
}
trap cleanup EXIT

check_deps() {
  for cmd in docker tar; do
    command -v "$cmd" >/dev/null 2>&1 || error "'$cmd' not found"
  done
  docker compose version >/dev/null 2>&1 || error "docker compose v2 not found"
}

extract_bundle() {
  info "Step 1/6  Extracting bundle ..."
  mkdir -p "$EXTRACT_DIR"
  tar xzf "$BUNDLE" -C "$EXTRACT_DIR"
  if [[ -f "${EXTRACT_DIR}/BUNDLE_INFO.txt" ]]; then
    sed 's/^/    /' "${EXTRACT_DIR}/BUNDLE_INFO.txt"
  fi
}

restore_code() {
  info "Step 2/6  Restoring code to ${INSTALL_DIR} ..."
  [[ -f "${EXTRACT_DIR}/code.tar.gz" ]] || error "code.tar.gz missing from bundle"
  mkdir -p "$INSTALL_DIR"
  tar xzf "${EXTRACT_DIR}/code.tar.gz" -C "$INSTALL_DIR" --strip-components=1
  cd "$INSTALL_DIR"
}

restore_volumes() {
  info "Step 3/6  Restoring data/models/samples ..."
  mkdir -p data models samples outputs

  [[ -f "${EXTRACT_DIR}/data.tar.gz" ]] && tar xzf "${EXTRACT_DIR}/data.tar.gz" -C "$INSTALL_DIR"
  [[ -f "${EXTRACT_DIR}/models.tar.gz" ]] && tar xzf "${EXTRACT_DIR}/models.tar.gz" -C "$INSTALL_DIR" || warn "models.tar.gz missing; add model files before STT"
  [[ -f "${EXTRACT_DIR}/samples.tar.gz" ]] && tar xzf "${EXTRACT_DIR}/samples.tar.gz" -C "$INSTALL_DIR"

  if [[ ! -f data/devices.yaml && -f data/devices.yaml.example ]]; then
    cp data/devices.yaml.example data/devices.yaml
    warn "Created data/devices.yaml from example; fill real API values before chat-audio"
  fi
}

init_env() {
  info "Step 4/6  Initializing .env ..."
  if [[ ! -f .env ]]; then
    cp .env.example .env
    warn "Created .env from .env.example; fill real API values before chat-audio"
  else
    info "  .env already exists"
  fi
}

build_image() {
  info "Step 5/6  Building Docker image ..."
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" build
}

smoke_test() {
  info "Step 6/6  Running smoke test ..."
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" run --rm \
    shuxin-voice-demo python -m shuxin.voice.cli --help
  info ""
  info "Deploy complete."
  info "Try:"
  info "  cd ${INSTALL_DIR}"
  info "  docker compose run --rm shuxin-voice-demo python -m shuxin.voice.cli tts \"hello\" --out outputs/hello.mp3"
}

main() {
  info "ShuXin voice demo deploy (${TIMESTAMP})"
  check_deps
  extract_bundle
  restore_code
  restore_volumes
  init_env
  build_image
  smoke_test
}

main "$@"
