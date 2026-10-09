"""Contract tests for the Cursor guide helpers, with a fake Cursor API and Render CLI.

Run: python3 -m pytest -q
"""
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get(
    "STARTER_DIR",
    str(HERE.parent),
))
LANGUAGES = {
    "typescript": ["npx", "--no-install", "tsx"],
    "python": ["python3"],
}
SUFFIX = {"typescript": ".ts", "python": ".py"}
FIXED = (SOURCE / "fixture/total.mjs").read_text().replace("amounts.slice(0, -1)", "amounts")


class FakeCursor:
    def __init__(self):
        self.requests = []
        self.scenario = "finished"
        self.polls = 0
        self.missing = set()

    def respond(self, method, path, body):
        self.requests.append((method, path, body))
        agent = "bc-test-1"
        run = "run-test-1"
        if method == "POST" and path == "/v1/agents":
            return 201, {
                "agent": {"id": agent, "latestRunId": run, "url": f"https://cursor.com/agents/{agent}"},
                "run": {"id": run, "agentId": agent, "status": "CREATING"},
            }
        if method == "GET" and path == f"/v1/agents/{agent}/runs/{run}":
            self.polls += 1
            if self.scenario == "flaky" and self.polls == 1:
                return 503, {"error": "unavailable"}
            if self.polls < 2:
                return 200, {"id": run, "status": "RUNNING"}
            status = "ERROR" if self.scenario == "error" else "FINISHED"
            git = {} if self.scenario == "no_branch" else {
                "git": {"branches": [{"repoUrl": "github.com/acme/task", "branch": "cursor/fix-total"}]}
            }
            return 200, {"id": run, "status": status, "result": "Fixed total.mjs.", **git}
        if path in self.missing:
            return 404, {"error": "not_found"}
        if path in {f"/v1/agents/{agent}/archive", f"/v1/agents/{agent}"}:
            return 200, {}
        return 404, {"error": "unexpected"}


@pytest.fixture
def cursor_api():
    fake = FakeCursor()

    class Handler(BaseHTTPRequestHandler):
        def handle_one(self):
            assert self.headers["Authorization"] == "Bearer test-user-key"
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            status, payload = fake.respond(self.command, self.path, body)
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_DELETE = handle_one

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fake.url = f"http://127.0.0.1:{server.server_port}"
    yield fake
    server.shutdown()


@pytest.fixture
def starter(tmp_path):
    root = tmp_path / "starter"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("node_modules", "__pycache__", ".git", ".venv", ".pytest_cache"))
    (root / "cursor/typescript/node_modules").symlink_to(SOURCE / "cursor/typescript/node_modules")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "render").symlink_to(HERE / "fake_render.py")
    render_dir = tmp_path / "render"
    render_dir.mkdir()
    return {"root": root, "bin": bin_dir, "render": render_dir, "tmp": tmp_path}


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def make_repo(starter, total=FIXED, report=None, tests=None):
    tmp = starter["tmp"]
    origin = tmp / "origin.git"
    git(tmp, "init", "--bare", "-b", "main", str(origin))
    repo = starter["root"] / "cursor/task-repo"
    shutil.copytree(starter["root"] / "fixture", repo)
    git(repo, "init", "-b", "main")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "--allow-empty", "-m", "init")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-m", "fixture")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "-b", "cursor/fix-total")
    (repo / "total.mjs").write_text(total)
    (repo / "outputs").mkdir()
    (repo / "outputs/report.json").write_text(report or '{"total":42,"row_count":3}\n')
    if tests is not None:
        (repo / "test_total.mjs").write_text(tests)
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-m", "fix")
    git(repo, "push", "-q", "origin", "cursor/fix-total")
    git(repo, "checkout", "-q", "main")


def run(starter, cursor_api, language, script, check=True):
    env = {
        **os.environ,
        "PATH": f"{starter['bin']}:{os.environ['PATH']}",
        "FAKE_RENDER_DIR": str(starter["render"]),
        "CURSOR_USER_API_KEY": "test-user-key",
        "CURSOR_API_ENDPOINT": cursor_api.url,
        "TASK_REPO_URL": "https://github.com/acme/task",
    }
    cwd = starter["root"] / "cursor" / language
    result = subprocess.run(
        [*LANGUAGES[language], script + SUFFIX[language]],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=180,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def sandboxes(starter):
    path = starter["render"] / "sandboxes.json"
    return json.loads(path.read_text()) if path.exists() else {}


@pytest.mark.parametrize("language", LANGUAGES)
def test_full_path(starter, cursor_api, language):
    make_repo(starter)
    cursor_api.scenario = "flaky"
    out = run(starter, cursor_api, language, "run_task").stdout
    method, path, body = cursor_api.requests[0]
    assert (method, path) == ("POST", "/v1/agents")
    assert body["env"] == {"type": "pool", "name": "render-sandboxes"}
    assert body["repos"] == [{"url": "https://github.com/acme/task", "startingRef": "main"}]
    note = (SOURCE / "cursor/task-note.txt").read_text()
    assert body["prompt"]["text"] == note + (SOURCE / "prompt.txt").read_text()
    assert "Pushed branch: cursor/fix-total" in out

    out = run(starter, cursor_api, language, "verify_result").stdout
    assert "pass 4" in out and "Verified report: total=42, row_count=3" in out
    results = starter["root"] / "cursor" / language / "results"
    assert json.loads((results / "report.json").read_text()) == {"total": 42, "row_count": 3}
    assert (results / "total.mjs").read_text() == FIXED
    rows = sandboxes(starter)
    assert len(rows) == 1
    (row,) = rows.values()
    assert "--network-policy=deny-all" in row["args"] and row["status"] == "terminated"

    worker = "sbx-worker1"
    rows[worker] = {"id": worker, "status": "running", "args": []}
    (starter["render"] / "sandboxes.json").write_text(json.dumps(rows))
    (starter["root"] / "cursor/claims.tsv").write_text(f"bc-other\tsbx-other\nbc-test-1\t{worker}\n")
    out = run(starter, cursor_api, language, "cleanup").stdout
    assert "archived and deleted" in out and f"Worker sandbox {worker} is terminated." in out
    calls = [(m, p) for m, p, _ in cursor_api.requests[-2:]]
    assert calls == [("POST", "/v1/agents/bc-test-1/archive"), ("DELETE", "/v1/agents/bc-test-1")]
    assert sandboxes(starter)[worker]["status"] == "terminated"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("scenario", ["error", "no_branch"])
def test_run_failures(starter, cursor_api, language, scenario):
    cursor_api.scenario = scenario
    result = run(starter, cursor_api, language, "run_task", check=False)
    assert result.returncode != 0
    assert (starter["root"] / "cursor" / language / "agent.json").exists()


BROKEN = (SOURCE / "fixture/total.mjs").read_text()
WEAK_TESTS = "import test from 'node:test';\ntest('ok', () => {});\n"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("branch", [
    {"report": '{"total":30,"row_count":3}\n'},
    {"total": BROKEN, "tests": WEAK_TESTS},
])
def test_verification_rejects_bad_results(starter, cursor_api, language, branch):
    make_repo(starter, **branch)
    workdir = starter["root"] / "cursor" / language
    (workdir / "run.json").write_text(json.dumps({"status": "FINISHED", "branch": "cursor/fix-total"}))
    result = run(starter, cursor_api, language, "verify_result", check=False)
    assert result.returncode != 0
    if "tests" in branch:
        assert "The branch changed test_total.mjs. Verification uses the original." in result.stdout
    assert all(row["status"] == "terminated" for row in sandboxes(starter).values())


@pytest.mark.parametrize("language", LANGUAGES)
def test_cleanup_stops_sandbox_when_cursor_call_fails(starter, cursor_api, language, monkeypatch):
    workdir = starter["root"] / "cursor" / language
    (workdir / "agent.json").write_text(json.dumps({"agentId": "bc-test-1", "runId": "run-test-1"}))
    rows = {"sbx-worker1": {"id": "sbx-worker1", "status": "running", "args": []}}
    (starter["render"] / "sandboxes.json").write_text(json.dumps(rows))
    (starter["root"] / "cursor/claims.tsv").write_text("bc-test-1\tsbx-worker1\n")
    monkeypatch.setattr(cursor_api, "respond", lambda *args: (500, {"error": "down"}))
    result = run(starter, cursor_api, language, "cleanup", check=False)
    assert result.returncode != 0
    assert sandboxes(starter)["sbx-worker1"]["status"] == "terminated"


@pytest.mark.parametrize("language", LANGUAGES)
def test_cleanup_tolerates_deleted_agent(starter, cursor_api, language):
    workdir = starter["root"] / "cursor" / language
    (workdir / "agent.json").write_text(json.dumps({"agentId": "bc-test-1", "runId": "run-test-1"}))
    cursor_api.missing = {"/v1/agents/bc-test-1/archive", "/v1/agents/bc-test-1"}
    out = run(starter, cursor_api, language, "cleanup").stdout
    assert "No worker sandbox recorded for bc-test-1." in out


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("status", ["errored", "terminated", "missing"])
def test_cleanup_terminal_states(starter, cursor_api, language, status):
    workdir = starter["root"] / "cursor" / language
    (workdir / "agent.json").write_text(json.dumps({"agentId": "bc-test-1"}))
    rows = {} if status == "missing" else {
        "sbx-worker1": {"id": "sbx-worker1", "status": status, "args": []}
    }
    (starter["render"] / "sandboxes.json").write_text(json.dumps(rows))
    (starter["root"] / "cursor/claims.tsv").write_text("bc-test-1\tsbx-worker1\n")
    result = run(starter, cursor_api, language, "cleanup", check=False)
    assert (result.returncode == 0) == (status != "missing"), result.stdout + result.stderr
    if status != "missing":
        assert f"Worker sandbox sbx-worker1 is {status}." in result.stdout
    if status == "errored":
        calls = [json.loads(line) for line in (starter["render"] / "calls.log").read_text().splitlines()]
        assert any(call[2:4] == ["stop", "sbx-worker1"] for call in calls)


@pytest.mark.parametrize("language", LANGUAGES)
def test_cleanup_does_not_hide_stop_failure(starter, cursor_api, language, monkeypatch):
    workdir = starter["root"] / "cursor" / language
    (workdir / "agent.json").write_text(json.dumps({"agentId": "bc-test-1"}))
    rows = {"sbx-worker1": {"id": "sbx-worker1", "status": "errored", "args": []}}
    (starter["render"] / "sandboxes.json").write_text(json.dumps(rows))
    (starter["root"] / "cursor/claims.tsv").write_text("bc-test-1\tsbx-worker1\n")
    monkeypatch.setenv("FAKE_RENDER_STOP_FAIL", "1")
    result = run(starter, cursor_api, language, "cleanup", check=False)
    assert result.returncode != 0
    assert "Worker sandbox sbx-worker1 is errored." not in result.stdout


@pytest.mark.parametrize("language", LANGUAGES)
def test_stop_rejects_sandbox_that_stays_running(starter, cursor_api, language, monkeypatch):
    rows = {"sbx-worker1": {"id": "sbx-worker1", "status": "running", "args": []}}
    (starter["render"] / "sandboxes.json").write_text(json.dumps(rows))
    monkeypatch.setenv("FAKE_RENDER_STOP_STUCK", "1")
    workdir = starter["root"] / "cursor" / language
    # Skip only the polling delays, preserving the real CLI calls and state checks.
    if language == "python":
        harness = 'import lib\nlib.time.sleep = lambda _: None\nlib.stop_sandbox("sbx-worker1")\n'
    else:
        harness = '''import { stopSandbox } from './lib.ts'
(globalThis as any).setTimeout = (callback: () => void) => { callback(); return 0 }
await stopSandbox('sbx-worker1')
'''
    (workdir / ("stop_test" + SUFFIX[language])).write_text(harness)
    result = run(starter, cursor_api, language, "stop_test", check=False)
    assert result.returncode != 0
    assert "did not reach a terminal state" in result.stderr
