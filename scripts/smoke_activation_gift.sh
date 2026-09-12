#!/usr/bin/env bash
# 首绑礼包 + 额度用尽绑机 — Docker 一键冒烟验收。
# 依赖: docker compose -p shuxin 已启动 voice + postgres。
#
# 用法:
#   bash scripts/smoke_activation_gift.sh
#
# 环境变量:
#   SHUXIN_ADMIN_TOKEN  默认 dev-admin-token
#   VOICE_BASE          默认 http://127.0.0.1:${VOICE_DEMO_PORT:-8765}
#   SMOKE_DEVICE_A/B    默认自动选两台 provisioned 且无 active 绑定的设备

if [[ -z "${BASH_VERSION:-}" ]]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck source=lib/docker_compose.sh
source "${ROOT_DIR}/scripts/lib/docker_compose.sh"

load_voice_port
load_postgres_env

ADMIN_TOKEN="${SHUXIN_ADMIN_TOKEN:-dev-admin-token}"
VOICE_BASE="${VOICE_BASE:-http://127.0.0.1:${VOICE_DEMO_PORT}}"
USER_ID="wx_smoke_$(date +%s)"
SESSION_TOKEN="smoke-session-${USER_ID}"
DEVICE_A="${SMOKE_DEVICE_A:-}"
DEVICE_B="${SMOKE_DEVICE_B:-}"
BINDING_A=""

info() { echo -e "\033[1;36m[smoke]\033[0m $*"; }
fail() { echo -e "\033[1;31m[smoke] FAIL:\033[0m $*" >&2; exit 1; }
pass() { echo -e "\033[1;32m[smoke] OK:\033[0m $*"; }

admin_curl() {
  curl -sf -H "X-Admin-Token: ${ADMIN_TOKEN}" "$@"
}

json_get() {
  local expr="$1"
  python3 -c "import json,sys; d=json.load(sys.stdin); print(${expr})"
}

psql_exec() {
  compose_cmd exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 -At -c "$1"
}

pick_provisioned_devices() {
  psql_exec "
    SELECT d.device_id
    FROM devices d
    WHERE d.status = 'provisioned'
      AND d.enabled = true
      AND d.deleted_at IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM device_bindings b WHERE b.device_id = d.device_id
      )
    ORDER BY d.device_id
    LIMIT 2;
  "
}

inject_session_via_postgres() {
  local token_hash
  token_hash="$(compose_cmd exec -T shuxin-voice-demo python3 -c "
import hashlib, os
pepper = os.environ.get('SHUXIN_SECRET_PEPPER', '')
print(hashlib.sha256(f'{pepper}:${SESSION_TOKEN}'.encode()).hexdigest())
")"
  token_hash="${token_hash//$'\r'/}"
  psql_exec "
    INSERT INTO wechat_sessions (session_token_hash, user_id, expires_at)
    VALUES ('${token_hash}', '${USER_ID}', now() + interval '30 days');
  "
}

zero_user_pool() {
  psql_exec "
    UPDATE devices d
    SET subscription_minutes_limit = 0,
        subscription_minutes_used = 0,
        subscription_expires_at = NULL,
        fuel_minutes_balance = 0,
        daily_allowance_seconds_used = 99999,
        daily_allowance_date = CURRENT_DATE
    FROM device_bindings b
    WHERE b.device_id = d.device_id
      AND b.user_id = '${USER_ID}'
      AND b.status = 'active';
  "
}

cleanup_bindings() {
  local bindings
  bindings="$(psql_exec "
    SELECT binding_id FROM device_bindings
    WHERE user_id = '${USER_ID}' AND status = 'active';
  " || true)"
  if [[ -z "${bindings}" ]]; then
    return 0
  fi
  while IFS= read -r binding_id; do
    [[ -z "${binding_id}" ]] && continue
    admin_curl -s -X POST "${VOICE_BASE}/admin/api/bindings/unbind" \
      -H "Content-Type: application/json" \
      -d "{\"binding_id\":\"${binding_id}\"}" >/dev/null || true
  done <<< "${bindings}"
}

trap cleanup_bindings EXIT

info "检查 voice 健康: ${VOICE_BASE}"
curl -sf "${VOICE_BASE}/health" >/dev/null || fail "voice 未就绪，请先 bash scripts/redeploy_docker.sh"

info "创建临时用户 ${USER_ID}"
admin_curl -s -X POST "${VOICE_BASE}/admin/api/users" \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"${USER_ID}\",\"enabled\":true}" >/dev/null

if [[ -z "${DEVICE_A}" || -z "${DEVICE_B}" ]]; then
  mapfile -t picked < <(pick_provisioned_devices)
  [[ -z "${DEVICE_A}" ]] && DEVICE_A="${picked[0]:-}"
  [[ -z "${DEVICE_B}" ]] && DEVICE_B="${picked[1]:-}"
fi
[[ -n "${DEVICE_A}" && -n "${DEVICE_B}" && "${DEVICE_A}" != "${DEVICE_B}" ]] \
  || fail "需要两台从未绑定过的 provisioned 设备（设置 SMOKE_DEVICE_A/B 或释放测试设备）"
info "使用设备 A=${DEVICE_A} B=${DEVICE_B}"

info "Admin 绑定设备 A，应获赠首绑礼包"
bind_a_json="$(admin_curl -s -X POST "${VOICE_BASE}/admin/api/bindings" \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"${USER_ID}\",\"device_id\":\"${DEVICE_A}\"}")"
BINDING_A="$(printf '%s' "${bind_a_json}" | json_get "d['binding_id']")"

quota_json="$(admin_curl -s "${VOICE_BASE}/admin/api/users/${USER_ID}/quota")"
sub_left="$(printf '%s' "${quota_json}" | json_get "float(d.get('subscription_minutes_left', 0))")"
exhausted="$(printf '%s' "${quota_json}" | json_get "str(d.get('exhausted'))")"
[[ "${exhausted}" == "False" ]] || fail "首绑后 exhausted 应为 false，实际 ${exhausted}"
python3 -c "import sys; v=float(sys.argv[1]); sys.exit(0 if v >= 120 else 1)" "${sub_left}" \
  || fail "首绑后 subscription_minutes_left 应 >= 120，实际 ${sub_left}"
pass "首绑礼包 ${sub_left} 分钟"

info "清零用户额度池"
zero_user_pool
quota_json="$(admin_curl -s "${VOICE_BASE}/admin/api/users/${USER_ID}/quota")"
exhausted="$(printf '%s' "${quota_json}" | json_get "str(d.get('exhausted'))")"
total="$(printf '%s' "${quota_json}" | json_get "float(d.get('total_minutes_left', -1))")"
[[ "${exhausted}" == "True" ]] || fail "清零后 exhausted 应为 true"
python3 -c "import sys; sys.exit(0 if float(sys.argv[1]) == 0 else 1)" "${total}" \
  || fail "清零后 total_minutes_left 应为 0，实际 ${total}"
pass "额度池已耗尽"

info "注入 session 并绑定设备 B（额度用尽时仍应 200）"
inject_session_via_postgres
bind_b_http="$(curl -s -o /tmp/smoke_bind_b.json -w '%{http_code}' -X POST "${VOICE_BASE}/api/devices/bind" \
  -H "Content-Type: application/json" \
  -d "{\"session_token\":\"${SESSION_TOKEN}\",\"device_code\":\"${DEVICE_B}\"}")"
[[ "${bind_b_http}" == "200" ]] || fail "绑机 B 应返回 200，实际 ${bind_b_http}: $(cat /tmp/smoke_bind_b.json)"
quota_json="$(admin_curl -s "${VOICE_BASE}/admin/api/users/${USER_ID}/quota")"
exhausted="$(printf '%s' "${quota_json}" | json_get "str(d.get('exhausted'))")"
total="$(printf '%s' "${quota_json}" | json_get "float(d.get('total_minutes_left', 0))")"
[[ "${exhausted}" == "False" ]] || fail "绑机 B 后 exhausted 应为 false"
python3 -c "import sys; sys.exit(0 if float(sys.argv[1]) >= 120 else 1)" "${total}" \
  || fail "绑机 B 后 total_minutes_left 应 >= 120，实际 ${total}"

gift_flag="$(psql_exec "
  SELECT COALESCE((metadata->>'activation_gift_applied')::text, 'false')
  FROM devices WHERE device_id = '${DEVICE_B}';
")"
[[ "${gift_flag}" == "true" ]] || fail "设备 B metadata.activation_gift_applied 应为 true"
pass "耗尽后绑机 B 恢复额度 total=${total}"

info "解绑并重绑设备 A，不应重复礼包"
admin_curl -s -X POST "${VOICE_BASE}/admin/api/bindings/unbind" \
  -H "Content-Type: application/json" \
  -d "{\"binding_id\":\"${BINDING_A}\"}" >/dev/null
limit_before="$(psql_exec "SELECT subscription_minutes_limit FROM devices WHERE device_id = '${DEVICE_A}';")"
admin_curl -s -X POST "${VOICE_BASE}/admin/api/bindings" \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"${USER_ID}\",\"device_id\":\"${DEVICE_A}\"}" >/dev/null
limit_after="$(psql_exec "SELECT subscription_minutes_limit FROM devices WHERE device_id = '${DEVICE_A}';")"
python3 -c "import sys; sys.exit(0 if float(sys.argv[1]) == float(sys.argv[2]) else 1)" "${limit_before}" "${limit_after}" \
  || fail "重绑设备 A 不应增加 subscription_minutes_limit (${limit_before} -> ${limit_after})"
pass "重绑设备 A 未重复礼包"

pass "全部验收通过 (user=${USER_ID})"
exit 0
