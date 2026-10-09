import json
import os
import subprocess
import sys
from pathlib import Path

from lib import PROJECT_DIR, sandboxes, stop_sandbox, wait_running

branch = json.loads(Path("run.json").read_text()).get("branch")
if not branch:
    raise SystemExit("run.json has no pushed branch.")
repo_dir = os.environ.get("TASK_REPO_DIR", "../task-repo")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", repo_dir, *args], check=True, capture_output=True, text=True, timeout=60,
    ).stdout


# Fetch the reported branch without changing the local checkout.
git("fetch", "--quiet", "origin", branch)
results = Path("results")
results.mkdir(exist_ok=True)
(results / "total.mjs").write_text(git("show", "FETCH_HEAD:total.mjs"))
(results / "report.json").write_text(git("show", "FETCH_HEAD:outputs/report.json"))
for name in ("orders.csv", "test_total.mjs"):
    if git("show", f"FETCH_HEAD:{name}") != (PROJECT_DIR / "fixture" / name).read_text():
        print(f"The branch changed {name}. Verification uses the original.")
print(f"Retrieved total.mjs and outputs/report.json from {branch}.")

sandbox_id = json.loads(
    sandboxes("create", "--timeout=600", "--network-policy=deny-all", "-o", "json")
)["id"]
print(f"Verifying in {sandbox_id}")
try:
    wait_running(sandbox_id)
    sandboxes("exec", sandbox_id, "--", "mkdir", "-p", "/workspace/outputs")
    # Use original inputs and tests, even if the agent changed its copies.
    uploads = [
        (PROJECT_DIR / "fixture/orders.csv", "/workspace/orders.csv"),
        (PROJECT_DIR / "fixture/test_total.mjs", "/workspace/test_total.mjs"),
        (PROJECT_DIR / "verify.mjs", "/workspace/verify.mjs"),
        (results / "total.mjs", "/workspace/total.mjs"),
        (results / "report.json", "/workspace/outputs/report.json"),
    ]
    for source, target in uploads:
        sandboxes("copy", str(source), f"{sandbox_id}:{target}")
    try:
        print(sandboxes(
            "exec", sandbox_id, "--", "bash", "-lc",
            "cd /workspace && node --test test_total.mjs && node verify.mjs",
        ), end="")
    except subprocess.CalledProcessError as error:
        print(error.stdout, end="")
        print(error.stderr, end="", file=sys.stderr)
        raise SystemExit(
            "Verification failed. Inspect results/total.mjs and results/report.json."
        ) from None
# Attempt sandbox cleanup even when verification fails.
finally:
    print(f"Verification sandbox {sandbox_id} is {stop_sandbox(sandbox_id)}.")
