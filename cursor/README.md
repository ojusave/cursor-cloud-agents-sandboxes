# Run the Cursor example

Start with the [prerequisites](../README.md#prerequisites) and [clone command](../README.md#get-started) in the repository README. This walkthrough uses two terminals: the first starts workers, and the second submits the task, retrieves the result, and cleans up. Both start in your local copy of this repository.

The task is to repair the sample total from **30 to 42** and retrieve `total.mjs` and `report.json`. This starter has not yet completed a full live Cursor run.

## 1. Set up the starter

In the **first terminal**, start at the repository root and enter the directory containing the controller and helpers:

```shell
# Keep the first terminal here for setup and the controller.
cd cursor
```

The commands work in Bash or zsh; controller scripts run with Bash automatically. In each zsh terminal, run `setopt interactivecomments` before pasting blocks with `#` explanations.

```shell
# Make newly created claim records readable only by your account.
umask 077
# Complete the browser sign-in before running the next command.
render login
# Replace the placeholder with the workspace ID from Render Settings.
render workspace set '<your-workspace-id>'
```

`umask 077` prints no output. Find your workspace ID (`tea-...`) at the top of **Settings** in the [Render Dashboard](https://dashboard.render.com/). It selects where the controller creates and bills sandboxes. Continue after login succeeds and `render workspace set` confirms the intended workspace.

Install the [Cursor CLI](https://cursor.com/docs/cli/installation) and confirm it supports the controller options used here:

```shell
# Install Cursor's command-line program from its official installer.
curl https://cursor.com/install -fsS | bash
# Let this terminal find the installed agent command.
export PATH="$HOME/.local/bin:$PATH"
# Check that the controller supports the two options this example uses.
agent worker controller --help | grep -e '--spawn' -e '--session-token'
```

The help output must include both `--spawn` and `--session-token`. If either is missing, run `agent update` and check again before continuing.

Choose one helper language for the task. Python needs no additional packages. For TypeScript, install the packages recorded in its lockfile:

```shell
# Install TypeScript tools in their directory, then return to cursor/.
(cd typescript && npm ci)
```

Continue when the install command finishes successfully. Both paths still use Python for the shared controller.

## 2. Put the task in a GitHub repository

Cursor agents work on GitHub repositories, so copy the sample files from `fixture/` into a new private repository:

```shell
# Choose a new private repository in a GitHub account you can write to.
export GITHUB_REPO='<your-github-user-or-org>/render-cursor-task'
# Copy the sample files into a separate folder so the originals stay intact.
cp -R ../fixture task-repo
cd task-repo
# Record the original files on a branch named main.
git init -q -b main
git add .
git commit -qm "Add order total task"
# Create the private GitHub repository and upload this first version.
gh repo create "$GITHUB_REPO" --private --source . --remote origin --push
# Return the first terminal to cursor/.
cd ..
```

The `gh` command should finish with a repository URL and a successful push of `main`. Save that URL for the second terminal. If the Cursor GitHub App has access only to selected repositories, add this one now.

## 3. Build the worker snapshot

A filesystem snapshot saves the installed Cursor CLI so each new worker can start without reinstalling it:

```shell
# Prepare the worker tools once, save them, and check a restored copy.
./controller/build-snapshot.sh
```

The script installs the CLI in a temporary sandbox, saves a filesystem snapshot, and checks that a sandbox restored from it can run `agent`, `git`, and `node`. It attempts to stop both sandboxes. An excerpt from a recorded Render run is shown below; IDs vary:

```text
building in sbx-...
checking restore in sbx-...
2026.10.01-e373342
git version 2.39.5
v24.14.1
worker snapshot ready
export WORKER_SNAPSHOT_ID='snp-...'
```

Run the printed `export` line in this terminal. CLI and runtime versions can differ because the script installs the current Cursor release.

> If creation times out, check the [Render Dashboard](https://dashboard.render.com/) before retrying to avoid creating duplicate resources. Keep any returned sandbox and snapshot IDs for [cleanup](#7-clean-up), including after a failure.

## 4. Start the controller

In the first terminal, enter the service account key at the hidden prompt. Typing displays no characters; paste the key and press Enter. Start the controller and leave it running:

```shell
# Read the key without echoing it or putting its value in shell history.
printf 'Cursor service account key: '
read -rs CURSOR_API_KEY
printf '\n'
# Give the controller its key; the second name is used to release failed claims.
export CURSOR_API_KEY CURSOR_RELEASE_API_KEY="$CURSOR_API_KEY"
# Watch the named pool and start a sandbox for each reserved task.
agent worker controller \
  --spawn "$PWD/controller/spawn.sh" \
  --pool render-sandboxes \
  --session-token
```

`CURSOR_RELEASE_API_KEY` is a second name for the same service account key, used by the hook if startup fails. The controller registers the `render-sandboxes` pool and waits for requests; it does not start the sample task yet. For each claimed request, `controller/spawn.sh`:

1. Creates a sandbox from `WORKER_SNAPSHOT_ID`, passing the claim's session token in its environment.
2. Writes the token to `/run/cursor/token` and starts `agent worker --pool render-sandboxes --clone-git-repos --auth-token-file /run/cursor/token`.
3. Records the request ID and sandbox ID in `claims.tsv`.
4. Monitors the worker and requests termination after three consecutive failed checks. The worker stays available for follow-ups for 600 seconds after a session ends. The sandbox has a separate two-hour maximum lifetime.

If startup fails, the hook attempts to stop the sandbox and release the claim with `CURSOR_RELEASE_API_KEY`. Check the recorded sandbox and claim if either cleanup request fails. Worker sandboxes use the `allow-all` network policy because the worker connects out to Cursor and GitHub.

Both languages use the same Bash spawn script. Only the token for the reserved task enters the sandbox. Code running there can read that token from the environment or token file, so do not save a worker sandbox as a reusable snapshot.

## 5. Send the task

Open a **second terminal at the repository root**. Choose one language and stay in that directory through verification and cleanup:

| Language | Enter this directory |
| --- | --- |
| Python | `cd cursor/python` |
| TypeScript | `cd cursor/typescript` |

A new terminal does not inherit variables set in the first one. Set the task repository URL from step 2, then enter the **user API key** at the hidden prompt:

```shell
# Keep the saved run records private to your account.
umask 077
# Point the helper at the private repository containing the task.
export TASK_REPO_URL='https://github.com/<your-github-user-or-org>/render-cursor-task'
# Read the user key without echoing it or saving its value in shell history.
printf 'Cursor user API key: '
read -rs CURSOR_USER_API_KEY
printf '\n'
# Make the key available to the submission and cleanup helpers.
export CURSOR_USER_API_KEY
```

Run the submission helper for your language:

| Python | TypeScript |
| --- | --- |
| `python3 run_task.py` | `npx tsx run_task.ts` |

The helper creates an agent in the `render-sandboxes` pool for your repository's `main` branch. It prints the agent's Cursor URL, where you can follow the run. The controller terminal prints `sandbox sbx-... for bc-...` after creating the sandbox, before it checks readiness. That message alone does not confirm the worker connected.

The helper checks the run every 10 seconds for up to 30 minutes and saves `agent.json` and `run.json`. On the success path, the helper is written to print the following. This Cursor completion output has not yet been observed in a live run of this starter:

```text
Run status: FINISHED
Pushed branch: cursor/...
```

> A local timeout does not cancel the Cursor run. If you stop here, keep `agent.json` and run [cleanup](#7-clean-up). Continue to verification only after the helper reports a finished run and a pushed branch.

## 6. Verify and retrieve the result

In the **second terminal**, still in your chosen language directory, check the agent's work independently of its reply:

| Python | TypeScript |
| --- | --- |
| `python3 verify_result.py` | `npx tsx verify_result.ts` |

The helper fetches the pushed branch into `../task-repo` and saves its `total.mjs` and `outputs/report.json` in `results`. It then starts a new sandbox with the `deny-all` network policy. It copies in the original `orders.csv`, `test_total.mjs`, and `verify.mjs` with the branch's two files, and runs the tests and the check. It stops that sandbox before exiting.

Expected output after a correct repair (IDs abbreviated):

```text
Verified report: total=42, row_count=3
Verification sandbox sbx-... is terminated.
```

If the branch changed the CSV or the tests, the helper says so, and the check still uses the originals. View the retrieved report:

```shell
# Read the report downloaded into this language directory.
cat results/report.json
```

```json
{"total":42,"row_count":3}
```

`results/total.mjs` is the corrected program. Both files stay after cleanup.

## 7. Clean up

A finished run can leave its worker available for follow-up tasks. Cleanup ends the Cursor agent and stops its sandbox to release the compute resources. Stopping a sandbox destroys its filesystem; keep the retrieved files in `results` before proceeding.

Stop the controller in the **first terminal** with **Ctrl+C** so it cannot accept more requests. Then, in the **second terminal**, delete the agent and stop its recorded worker sandboxes:

| Python | TypeScript |
| --- | --- |
| `python3 cleanup.py` | `npx tsx cleanup.ts` |

The helper archives and deletes the agent, which ends its claim. It then stops each sandbox recorded for that agent in `claims.tsv` and confirms each has ended (`terminated` or `errored`). A timeout can leave a sandbox `errored` even after a successful stop request; this does not mean the agent completed its task. It attempts every step and exits with an error if any step fails.

In the **second terminal**, clear the user key after cleanup succeeds:

```shell
# Remove the user key from the second terminal's environment.
unset CURSOR_USER_API_KEY
```

In the **first terminal**, remove the snapshot when you no longer need it and clear the controller keys:

```shell
# Delete the saved worker image when it is no longer needed.
render ea sandboxes snapshots delete "$WORKER_SNAPSHOT_ID" --confirm
# Check the recorded sandbox IDs against their final status.
render ea sandboxes list --all
# Remove controller credentials from the first terminal's environment.
unset CURSOR_API_KEY CURSOR_RELEASE_API_KEY
```

Check the IDs in `claims.tsv` against the listing. Your test sandboxes should be `terminated`, or `errored` after a timeout; other workloads in the workspace may still be running. Retain `agent.json` and `claims.tsv` if cleanup fails so you can retry. `unset` prints no output and does not revoke the keys.

The task repository contains the original and agent-created branches. Keep it to inspect the fix, or delete it from the first terminal if you no longer need it:

```shell
# Optional: permanently delete this test repository and its remote branches.
gh repo delete "$GITHUB_REPO" --yes
```

Deletion removes the remote repository and its branches. If GitHub refuses it because the token lacks `delete_repo`, use `gh auth refresh -s delete_repo`. Local files in `results` remain. The pool also stays registered; remove it with Cursor's [pools API](https://cursor.com/docs/cloud-agent/self-hosted/pool#manage-pools) when no longer needed.

## Troubleshooting

| Problem | Check |
| --- | --- |
| `--spawn` or `--session-token` is missing | Run `agent update`, then check `agent worker controller --help` again. |
| The controller exits or rejects its key | `CURSOR_API_KEY` must be a service account key, and the team must have self-hosted workers and session tokens enabled. |
| The run stays queued | The controller is running and shows no `spawn failed` line. **Allow Self-Hosted Machines** is on. |
| `spawn failed: worker exited during startup` | The worker process exited or its status could not be checked. Inspect `/var/log/cursor-worker.log` while the sandbox is accessible; token authentication is one possible cause. The hook attempts to stop the sandbox and release the claim; confirm both before retrying. Check the team's session token setting and the service account. |
| The run stays queued after `sandbox sbx-...` appears | A failed clone leaves the run queued. Confirm GitHub token minting is on, and that the Cursor GitHub App and the user who started the run can access the repository. |
| The run finishes without a branch | Open the agent's URL to see what it did. Run cleanup, then send the task again. |
| Verification fails | Inspect `results/total.mjs` and `results/report.json`. A finished run alone does not establish success. |
| Sandboxes are still running after cleanup | Cleanup may have failed, or the resources may belong to another run. Match the IDs in `claims.tsv` to `render ea sandboxes list --all`, then stop only the sandboxes belonging to this test. |

## Run the controller on Render

To keep the pool available without your terminal, run the same controller command in a Render [background worker](https://render.com/docs/background-workers). Its image needs Bash, Python 3.10 or later, the Render CLI, the Cursor CLI, and `controller/spawn.sh`. Set `CURSOR_API_KEY`, `CURSOR_RELEASE_API_KEY`, `WORKER_SNAPSHOT_ID`, and `RENDER_API_KEY` as secret environment variables. Run one instance.

Each sandbox's stop monitor is a process on the controller host. A failed check can mean either worker exit or a failed connection; production monitoring should distinguish them. Persist claim-to-sandbox records across restarts, reconcile orphaned sandboxes, and refresh expired snapshots before relying on an unattended controller. After a redeploy, list running sandboxes and stop finished ones. Use a sandbox only for workers, not for the controller: a sandbox lives at most 24 hours. See [Sandboxes](https://render.com/docs/sandboxes) for current limits and Cursor's [controller reference](https://cursor.com/docs/cloud-agent/self-hosted/pool) for warm pools, hibernation, and claim release.

Return to the [source files](../README.md#source-files).
