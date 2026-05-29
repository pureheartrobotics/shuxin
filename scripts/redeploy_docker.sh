#!/usr/bin/env bash
# Daily Docker redeploy/start for ShuXin voice demo.
# Preserves mounted data: data/, models/, samples/, outputs/.

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
  "voice-local requirements-voice-local.txt"
  "shuxin-core requirements-shuxin-core.txt"
  "voice-web requirements-voice-web.txt"
  "voice-integrations requirements-voice-integrations.txt"
  "voice-barcode requirements-voice-barcode.txt"
)

for arg in "$@"; do
  case "$arg" in
    --build) FORCE_BUILD=1 ;;
    --no-build) NO_BUILD=1 ;;
    -h|--help)
      echo "Usage: bash scripts/redeploy_docker.sh [--build|--no-build]"
      exit 0
      ;;
    *) echo "[redeploy] unknown argument: $arg" >&2; exit 1 ;;
  esac
done

if [[ "$FORCE_BUILD" -eq 1 && "$NO_BUILD" -eq 1 ]]; then
  echo "[redeploy] --build and --no-build cannot be used together" >&2
  exit 1
fi

info() { echo -e "\033[1;32m[redeploy]\033[0m $*"; }
warn() { echo -e "\033[1;33m[redeploy] WARN:\033[0m $*" >&2; }

mkdir -p data models samples outputs

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  warn "Created .env from .env.example"
fi

if [[ ! -f data/devices.yaml && -f data/devices.yaml.example ]]; then
  cp data/devices.yaml.example data/devices.yaml
  warn "Created data/devices.yaml from example"
fi

info "Checking docker compose config ..."
docker compose -p "$PROJECT_NAME" config >/dev/null

current_deps_hash() {
  local module path hash
  for entry in "${DEPS_MODULES[@]}"; do
    module="${entry%% *}"
    path="${entry#* }"
    hash="$(sha256sum "$path" | awk '{print $1}')"
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

  # Older deployments stored one aggregate hash line. Treat that as an unknown
  # dependency layout and report all current modules as changed.
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

CURRENT_HASH="$(current_deps_hash)"
PREVIOUS_HASH=""
if [[ -f "$DEPS_HASH_FILE" ]]; then
  PREVIOUS_HASH="$(<"$DEPS_HASH_FILE")"
fi

BUILD_REASON=""
if [[ "$NO_BUILD" -eq 1 ]]; then
  info "Skipping build because --no-build was requested"
elif [[ "$FORCE_BUILD" -eq 1 ]]; then
  BUILD_REASON="--build requested"
elif ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  BUILD_REASON="image not found: $IMAGE"
elif [[ -n "$PREVIOUS_HASH" && "$PREVIOUS_HASH" != "$CURRENT_HASH" ]]; then
  CHANGED_MODULES="$(changed_deps_modules "$CURRENT_HASH" "$PREVIOUS_HASH")"
  BUILD_REASON="dependency modules changed: ${CHANGED_MODULES:-unknown}"
elif [[ -z "$PREVIOUS_HASH" ]]; then
  info "Dependency hash file not found; initializing without rebuild because image exists"
fi

if [[ -n "$BUILD_REASON" ]]; then
  info "Building Docker image ($BUILD_REASON) ..."
  DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose -p "$PROJECT_NAME" build "$SERVICE"
  printf "%s\n" "$CURRENT_HASH" > "$DEPS_HASH_FILE"
else
  info "Code-only redeploy: skipping dependency build"
  if [[ -z "$PREVIOUS_HASH" ]]; then
    printf "%s\n" "$CURRENT_HASH" > "$DEPS_HASH_FILE"
  fi
fi

info "Starting service with container recreate ..."
docker compose -p "$PROJECT_NAME" up -d --force-recreate "$SERVICE"

info "Redeploy complete. Mounted runtime data was preserved."
