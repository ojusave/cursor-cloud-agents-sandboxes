#!/usr/bin/env bash
# Start one Render Sandbox for one claimed Cursor pool request.
# The service account key stays on the controller host. The sandbox receives
# only the claim's session token, which the worker reads from a file.
set -euo pipefail

: "${CURSOR_AGENT_WORKER_ID:?}"
: "${CURSOR_POOL:?}"
: "${CURSOR_AUTH_TOKEN:?run the controller with --session-token}"
: "${CURSOR_REQUEST_ID:?}"
: "${WORKER_SNAPSHOT_ID:?}"

RENDER_BIN="${RENDER_BIN:-render}"
STATE_DIR="${STATE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
IDLE_RELEASE_TIMEOUT="${CURSOR_WORKER_IDLE_RELEASE_TIMEOUT:-600}"
SANDBOX_TIMEOUT_SECONDS="${SANDBOX_TIMEOUT_SECONDS:-7200}"

ENV_FILE=""
SANDBOX_ID=""

cleanup_env_file() {
  if [ -n "${ENV_FILE}" ]; then
    rm -f "${ENV_FILE}"
  fi
}
trap cleanup_env_file EXIT

release_claim() {
  if [ -z "${CURSOR_RELEASE_API_KEY:-}" ]; then
    echo "CURSOR_RELEASE_API_KEY is unset; release ${CURSOR_REQUEST_ID} manually" >&2
    return 0
  fi
  local cfg
  cfg="$(mktemp)"
  chmod 600 "${cfg}"
  printf 'user = "%s:"\n' "${CURSOR_RELEASE_API_KEY}" > "${cfg}"
  curl --config "${cfg}" --silent --show-error --max-time 30 --request POST \
    --url "https://api.cursor.com/v0/private-workers/claims/${CURSOR_REQUEST_ID}/release" \
    >/dev/null || true
  rm -f "${cfg}"
}

fail() {
  echo "spawn failed: $*" >&2
  if [ -n "${SANDBOX_ID}" ]; then
    "${RENDER_BIN}" ea sandboxes stop "${SANDBOX_ID}" --confirm >/dev/null 2>&1 || true
  fi
  release_claim
  exit 1
}

json_id() {
  python3 -c 'import json,sys
raw=sys.stdin.read()
start=raw.find("{")
if start < 0:
    raise SystemExit("missing JSON")
print(json.JSONDecoder().raw_decode(raw, start)[0]["id"])'
}

wait_until_running() {
  local status="" _
  for _ in $(seq 1 60); do
    status="$("${RENDER_BIN}" ea sandboxes list --all -o json \
      | SID="$1" python3 -c 'import json,os,sys
rows=json.load(sys.stdin) or []
print(next((r["status"] for r in rows if r.get("id")==os.environ["SID"]), "missing"))')"
    case "${status}" in
      running) return 0 ;;
      errored|terminated) return 1 ;;
    esac
    sleep 2
  done
  return 1
}

umask 077
ENV_FILE="$(mktemp)"
cat > "${ENV_FILE}" <<EOF
CURSOR_AGENT_WORKER_ID=${CURSOR_AGENT_WORKER_ID}
CURSOR_POOL=${CURSOR_POOL}
CURSOR_AUTH_TOKEN=${CURSOR_AUTH_TOKEN}
CURSOR_WORKER_IDLE_RELEASE_TIMEOUT=${IDLE_RELEASE_TIMEOUT}
EOF

CREATE="$("${RENDER_BIN}" ea sandboxes create \
  --snapshot-id "${WORKER_SNAPSHOT_ID}" \
  --timeout "${SANDBOX_TIMEOUT_SECONDS}" \
  --network-policy=allow-all \
  --env-file "${ENV_FILE}" \
  -o json)" || fail "create returned non-zero"
SANDBOX_ID="$(printf '%s' "${CREATE}" | json_id)"
[[ "${SANDBOX_ID}" =~ ^sbx-[A-Za-z0-9_-]+$ ]] || fail "unexpected sandbox id"
printf '%s\t%s\n' "${CURSOR_REQUEST_ID}" "${SANDBOX_ID}" >> "${STATE_DIR}/claims.tsv"
echo "sandbox ${SANDBOX_ID} for ${CURSOR_REQUEST_ID}"

wait_until_running "${SANDBOX_ID}" || fail "sandbox ${SANDBOX_ID} did not reach running"
rm -f "${ENV_FILE}"
ENV_FILE=""

# The sandbox shell expands CURSOR_AUTH_TOKEN; the token never appears in this command line.
"${RENDER_BIN}" ea sandboxes exec "${SANDBOX_ID}" -- bash -lc '
  set -euo pipefail
  umask 077
  mkdir -p /run/cursor /workspace
  printf "%s" "$CURSOR_AUTH_TOKEN" > /run/cursor/token
  unset CURSOR_AUTH_TOKEN
  nohup agent worker \
    --pool "$CURSOR_POOL" \
    --worker-dir /workspace \
    --idle-release-timeout "$CURSOR_WORKER_IDLE_RELEASE_TIMEOUT" \
    --clone-git-repos \
    --auth-token-file /run/cursor/token \
    start >> /var/log/cursor-worker.log 2>&1 < /dev/null &
  echo $! > /var/run/cursor-worker.pid
' || fail "worker start exec failed"

sleep 5
"${RENDER_BIN}" ea sandboxes exec "${SANDBOX_ID}" -- bash -lc \
  'ps -p "$(cat /var/run/cursor-worker.pid)" >/dev/null' \
  || fail "worker exited during startup; see /var/log/cursor-worker.log"

# Stop the sandbox after three consecutive checks find no worker process.
nohup bash -c '
  misses=0
  while [ "$misses" -lt 3 ]; do
    sleep 15
    if "$0" ea sandboxes exec "$1" -- bash -lc "ps -p \"\$(cat /var/run/cursor-worker.pid)\" >/dev/null" >/dev/null 2>&1; then
      misses=0
    else
      misses=$((misses + 1))
    fi
  done
  if "$0" ea sandboxes stop "$1" --confirm >/dev/null 2>&1; then
    echo "stop request accepted for $1"
  else
    echo "stop request failed for $1; manual cleanup required" >&2
    exit 1
  fi
' "${RENDER_BIN}" "${SANDBOX_ID}" >> "${STATE_DIR}/monitor.log" 2>&1 < /dev/null &

exit 0
