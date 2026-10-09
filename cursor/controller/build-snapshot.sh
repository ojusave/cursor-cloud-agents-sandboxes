#!/usr/bin/env bash
# Build a Render Sandbox snapshot that contains the Cursor CLI, then prove a
# sandbox restored from it can run the worker tools.
set -euo pipefail

RENDER_BIN="${RENDER_BIN:-render}"
SANDBOX_ID=""

stop_sandbox() {
  if [ -n "${SANDBOX_ID}" ]; then
    "${RENDER_BIN}" ea sandboxes stop "${SANDBOX_ID}" --confirm -o json >/dev/null 2>&1 || true
    SANDBOX_ID=""
  fi
}
trap stop_sandbox EXIT

json_field() {
  python3 -c 'import json,sys
raw=sys.stdin.read()
start=raw.find("{")
if start < 0:
    raise SystemExit("missing JSON")
print(json.JSONDecoder().raw_decode(raw, start)[0][sys.argv[1]])' "$1"
}

wait_running() {
  local status="" _
  for _ in $(seq 1 60); do
    status="$("${RENDER_BIN}" ea sandboxes list --all -o json \
      | SID="$1" python3 -c 'import json,os,sys
rows=json.load(sys.stdin) or []
print(next((r["status"] for r in rows if r.get("id")==os.environ["SID"]), "missing"))')"
    case "${status}" in
      running) return 0 ;;
      errored|terminated) echo "sandbox $1 is ${status}" >&2; return 1 ;;
    esac
    sleep 2
  done
  echo "sandbox $1 did not reach running" >&2
  return 1
}

create_sandbox() {
  "${RENDER_BIN}" ea sandboxes create --timeout=1800 --network-policy=allow-all "$@" -o json \
    | json_field id
}

SANDBOX_ID="$(create_sandbox)"
echo "building in ${SANDBOX_ID}"
wait_running "${SANDBOX_ID}"
"${RENDER_BIN}" ea sandboxes exec "${SANDBOX_ID}" -- bash -lc '
  set -euo pipefail
  curl https://cursor.com/install -fsS | bash
  ln -sfn "$HOME/.local/bin/agent" /usr/local/bin/agent
  mkdir -p /workspace
'

SNAPSHOT_ID="$("${RENDER_BIN}" ea sandboxes snapshots create "${SANDBOX_ID}" --kind filesystem -o json \
  | json_field id)"
for _ in $(seq 1 90); do
  status="$("${RENDER_BIN}" ea sandboxes snapshots get "${SNAPSHOT_ID}" -o json | json_field status)"
  [ "${status}" = available ] && break
  [ "${status}" = failed ] && { echo "snapshot ${SNAPSHOT_ID} failed" >&2; exit 1; }
  sleep 2
done
[ "${status}" = available ] || { echo "snapshot ${SNAPSHOT_ID} is still ${status}" >&2; exit 1; }
stop_sandbox

SANDBOX_ID="$(create_sandbox --snapshot-id "${SNAPSHOT_ID}")"
echo "checking restore in ${SANDBOX_ID}"
wait_running "${SANDBOX_ID}"
"${RENDER_BIN}" ea sandboxes exec "${SANDBOX_ID}" -- bash -lc \
  'agent --version && git --version && node --version && test -d /workspace'
stop_sandbox

echo "worker snapshot ready"
echo "export WORKER_SNAPSHOT_ID='${SNAPSHOT_ID}'"
