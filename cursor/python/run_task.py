import json
import os
import time
from pathlib import Path

from lib import CURSOR_DIR, PROJECT_DIR, CursorApiError, cursor_api

repo_url = os.environ.get("TASK_REPO_URL")
if not repo_url:
    raise SystemExit("Set TASK_REPO_URL first.")
pool = os.environ.get("CURSOR_POOL", "render-sandboxes")
terminal = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}

# Map the shared task paths to the repository Cursor will clone.
prompt = (CURSOR_DIR / "task-note.txt").read_text() + (PROJECT_DIR / "prompt.txt").read_text()
created = cursor_api("POST", "/v1/agents", {
    "prompt": {"text": prompt},
    "env": {"type": "pool", "name": pool},
    "repos": [{"url": repo_url, "startingRef": os.environ.get("TASK_REPO_REF", "main")}],
})
agent_id = created["agent"]["id"]
run_id = (created.get("run") or {}).get("id") or created["agent"]["latestRunId"]
# Save IDs before polling so cleanup can still run after an error or timeout.
Path("agent.json").write_text(json.dumps({"agentId": agent_id, "runId": run_id}, indent=2) + "\n")
print(f"Agent {agent_id} created. Follow it at {created['agent'].get('url')}")

# Polling observes the remote run; reaching this deadline does not cancel it.
deadline = time.monotonic() + 30 * 60
last_status = ""
failures = 0
while True:
    try:
        run = cursor_api("GET", f"/v1/agents/{agent_id}/runs/{run_id}")
        failures = 0
    except (CursorApiError, OSError) as error:
        if isinstance(error, CursorApiError) and error.status < 500:
            raise
        failures += 1
        if failures >= 5:
            raise
        time.sleep(10)
        continue
    if run["status"] != last_status:
        print(f"Run status: {run['status']}")
    last_status = run["status"]
    if run["status"] in terminal:
        break
    if time.monotonic() > deadline:
        raise SystemExit("The run is still active after 30 minutes.")
    time.sleep(10)

branch = next(
    (entry["branch"] for entry in (run.get("git") or {}).get("branches", []) if entry.get("branch")),
    None,
)
Path("run.json").write_text(json.dumps({**run, "branch": branch}, indent=2) + "\n")
if run.get("result"):
    print(f"\n{run['result']}\n")
if run["status"] != "FINISHED":
    raise SystemExit(f"The run ended with {run['status']}.")
if not branch:
    raise SystemExit("The run finished without pushing a branch.")
print(f"Pushed branch: {branch}")
