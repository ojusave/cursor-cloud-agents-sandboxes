#!/usr/bin/env python3
"""Minimal stand-in for `render ea sandboxes` backed by local directories."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

state_dir = Path(os.environ["FAKE_RENDER_DIR"])
state_file = state_dir / "sandboxes.json"
log_file = state_dir / "calls.log"


def load():
    return json.loads(state_file.read_text()) if state_file.exists() else {}


def save(rows):
    state_file.write_text(json.dumps(rows))


def root(sandbox_id):
    path = state_dir / sandbox_id
    path.mkdir(exist_ok=True)
    return path


def local_path(spec):
    sandbox_id, _, remote = spec.partition(":")
    return root(sandbox_id) / remote.lstrip("/")


args = sys.argv[1:]
with log_file.open("a") as log:
    log.write(json.dumps(args) + "\n")
assert args[:2] == ["ea", "sandboxes"], args
command, rest = args[2], args[3:]
rows = load()

if command == "create":
    sandbox_id = f"sbx-fake{len(rows) + 1}"
    rows[sandbox_id] = {"id": sandbox_id, "status": "running", "args": rest}
    save(rows)
    print(json.dumps({"id": sandbox_id, "status": "creating"}))
elif command == "list":
    print(json.dumps(list(rows.values())))
elif command == "stop":
    if os.environ.get("FAKE_RENDER_STOP_FAIL") == "1":
        sys.exit("stop failed")
    if rows[rest[0]]["status"] != "errored" and os.environ.get("FAKE_RENDER_STOP_STUCK") != "1":
        rows[rest[0]]["status"] = "terminated"
    save(rows)
    print(json.dumps({"id": rest[0], "status": rows[rest[0]]["status"]}))
elif command == "copy":
    source, target = rest[0], rest[1]
    if ":" in source and source.startswith("sbx-"):
        shutil.copy(local_path(source), target)
    else:
        destination = local_path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        workspace = str(root(target.partition(":")[0]) / "workspace")
        destination.write_text(Path(source).read_text().replace("/workspace", workspace))
elif command == "exec":
    sandbox_id = rest[0]
    if rows.get(sandbox_id, {}).get("status") != "running":
        sys.exit(1)
    remote = rest[rest.index("--") + 1:]
    workspace = str(root(sandbox_id) / "workspace")
    remote = [part.replace("/workspace", workspace) for part in remote]
    if os.environ.get("FAKE_RENDER_DENY_EXEC") == "1":
        sys.exit(1)
    sys.exit(subprocess.run(remote).returncode)
else:
    sys.exit(f"unsupported fake command {command}")
