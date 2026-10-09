import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
CURSOR_DIR = Path(__file__).resolve().parent.parent


def sandboxes(*args: str) -> str:
    """Run a `render ea sandboxes` subcommand and return its stdout."""
    return subprocess.run(
        ["render", "ea", "sandboxes", *args],
        check=True, capture_output=True, text=True, timeout=120,
    ).stdout


def sandbox_status(sandbox_id: str) -> str:
    """Return a sandbox's status, or "missing" if the workspace has no such sandbox."""
    rows = json.loads(sandboxes("list", "--all", "-o", "json")) or []
    return next((row["status"] for row in rows if row["id"] == sandbox_id), "missing")


def wait_running(sandbox_id: str) -> None:
    """Wait up to two minutes for a sandbox to accept commands."""
    for _ in range(60):
        status = sandbox_status(sandbox_id)
        if status == "running":
            return
        if status in ("errored", "terminated"):
            raise RuntimeError(f"sandbox {sandbox_id} is {status}")
        time.sleep(2)
    raise TimeoutError(f"sandbox {sandbox_id} did not reach running")


def stop_sandbox(sandbox_id: str) -> str:
    """Request a stop and confirm a terminal state, preserving an error status."""
    if sandbox_status(sandbox_id) != "terminated":
        sandboxes("stop", sandbox_id, "--confirm", "-o", "json")
    for _ in range(30):
        status = sandbox_status(sandbox_id)
        if status in ("terminated", "errored"):
            return status
        time.sleep(2)
    raise TimeoutError(f"sandbox {sandbox_id} did not reach a terminal state; last status: {status}")


class CursorApiError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Cursor API returned {status}: {body[:500]}")
        self.status = status


# Helpers use the user key; the controller uses a separate service account key.
def cursor_api(method: str, path: str, body=None):
    """Call the Cursor Cloud Agents API with the user API key."""
    key = os.environ.get("CURSOR_USER_API_KEY")
    if not key:
        raise RuntimeError("Set CURSOR_USER_API_KEY first.")
    base = os.environ.get("CURSOR_API_ENDPOINT", "https://api.cursor.com")
    request = urllib.request.Request(
        base + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode()
    except urllib.error.HTTPError as error:
        raise CursorApiError(error.code, error.read().decode(errors="replace")) from None
    return json.loads(text) if text else {}
