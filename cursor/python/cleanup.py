import json
from pathlib import Path

from lib import CURSOR_DIR, CursorApiError, cursor_api, stop_sandbox

agent_id = json.loads(Path("agent.json").read_text())["agentId"]
failed = False

# Continue to Render cleanup even if the Cursor API is unavailable.
for method, path in (("POST", f"/v1/agents/{agent_id}/archive"), ("DELETE", f"/v1/agents/{agent_id}")):
    try:
        cursor_api(method, path)
    except Exception as error:
        if isinstance(error, CursorApiError) and error.status == 404:
            continue
        print(f"{method} {path}: {error}")
        failed = True
if not failed:
    print(f"Cursor agent {agent_id} archived and deleted.")

# Select only sandbox IDs recorded for this agent, leaving other runs alone.
claims = CURSOR_DIR / "claims.tsv"
sandbox_ids = []
if claims.exists():
    for line in claims.read_text().splitlines():
        request, _, sandbox = line.partition("\t")
        if request == agent_id and sandbox:
            sandbox_ids.append(sandbox)
if not sandbox_ids:
    print(f"No worker sandbox recorded for {agent_id}.")
for sandbox_id in sandbox_ids:
    try:
        status = stop_sandbox(sandbox_id)
    except Exception as error:
        print(f"stop {sandbox_id}: {error}")
        failed = True
        continue
    print(f"Worker sandbox {sandbox_id} is {status}.")
    if status not in ("terminated", "errored"):
        failed = True
raise SystemExit(1 if failed else 0)
