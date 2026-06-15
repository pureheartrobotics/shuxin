# 初心语音脚本共用的 Docker Compose 辅助函数。
# 在 bash 中引用: source "$(dirname "$0")/lib/docker_compose.sh"

: "${PROJECT_NAME:=shuxin}"
: "${COMPOSE_FILE:=docker-compose.yml}"

compose_cmd() {
  local -a cmd=(docker compose -p "$PROJECT_NAME")
  local spec="${COMPOSE_FILE:-docker-compose.yml}"
  local part files_added=0 old_ifs="$IFS"
  IFS=':'
  for part in $spec; do
    part="${part#"${part%%[![:space:]]*}"}"
    part="${part%"${part##*[![:space:]]}"}"
    if [[ -n "$part" ]]; then
      cmd+=(-f "$part")
      files_added=1
    fi
  done
  IFS="$old_ifs"
  if [[ "$files_added" -eq 0 ]]; then
    cmd+=(-f docker-compose.yml)
  fi
  "${cmd[@]}" "$@"
}

compose_volume() {
  local key="$1"
  echo "${PROJECT_NAME}_${key}"
}

load_postgres_env() {
  POSTGRES_USER="${POSTGRES_USER:-shuxin}"
  POSTGRES_DB="${POSTGRES_DB:-shuxin}"
  if [[ -f .env ]]; then
    local _u _d
    _u="$(grep -E '^POSTGRES_USER=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
    _d="$(grep -E '^POSTGRES_DB=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
    [[ -n "$_u" ]] && POSTGRES_USER="$_u"
    [[ -n "$_d" ]] && POSTGRES_DB="$_d"
  fi
  return 0
}

wait_postgres_healthy() {
  local max="${1:-60}" i=0
  load_postgres_env
  while [[ "$i" -lt "$max" ]]; do
    if compose_cmd exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    i=$((i + 1))
  done
  return 1
}

load_voice_port() {
  VOICE_DEMO_PORT="${VOICE_DEMO_PORT:-8765}"
  if [[ -f .env ]]; then
    local _p
    _p="$(grep -E '^VOICE_DEMO_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
    [[ -n "$_p" ]] && VOICE_DEMO_PORT="$_p"
  fi
  return 0
}

load_host_data_dirs() {
  SHUXIN_HOST_DATA_DIR="${SHUXIN_HOST_DATA_DIR:-./data}"
  SHUXIN_HOST_MODELS_DIR="${SHUXIN_HOST_MODELS_DIR:-./models}"
  SHUXIN_HOST_SAMPLES_DIR="${SHUXIN_HOST_SAMPLES_DIR:-./samples}"
  SHUXIN_HOST_OUTPUTS_DIR="${SHUXIN_HOST_OUTPUTS_DIR:-./outputs}"
  if [[ -f .env ]]; then
    local _v _key
    for _key in SHUXIN_HOST_DATA_DIR SHUXIN_HOST_MODELS_DIR SHUXIN_HOST_SAMPLES_DIR SHUXIN_HOST_OUTPUTS_DIR; do
      _v="$(grep -E "^${_key}=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
      [[ -n "$_v" ]] && printf -v "$_key" '%s' "$_v"
    done
  fi
  return 0
}
