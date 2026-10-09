import { readFileSync, writeFileSync } from 'node:fs'
import { CursorApiError, cursorApi, cursorDir, log, projectDir } from './lib.ts'

const repoUrl = process.env.TASK_REPO_URL
if (!repoUrl) throw new Error('Set TASK_REPO_URL first.')
const pool = process.env.CURSOR_POOL ?? 'render-sandboxes'
const terminal = new Set(['FINISHED', 'ERROR', 'CANCELLED', 'EXPIRED'])

// Map the shared task paths to the repository Cursor will clone.
const prompt =
  readFileSync(new URL('task-note.txt', cursorDir), 'utf8') +
  readFileSync(new URL('prompt.txt', projectDir), 'utf8')
const created = await cursorApi('POST', '/v1/agents', {
  prompt: { text: prompt },
  env: { type: 'pool', name: pool },
  repos: [{ url: repoUrl, startingRef: process.env.TASK_REPO_REF ?? 'main' }],
})
const agentId: string = created.agent.id
const runId: string = created.run?.id ?? created.agent.latestRunId
// Save IDs before polling so cleanup can still run after an error or timeout.
writeFileSync('agent.json', `${JSON.stringify({ agentId, runId }, null, 2)}\n`)
log(`Agent ${agentId} created. Follow it at ${created.agent.url}`)

// Polling observes the remote run; reaching this deadline does not cancel it.
const deadline = Date.now() + 30 * 60_000
let run: {
  status: string
  result?: string
  git?: { branches?: { branch?: string }[] }
}
let lastStatus = ''
let failures = 0
for (;;) {
  try {
    run = await cursorApi('GET', `/v1/agents/${agentId}/runs/${runId}`)
    failures = 0
  } catch (error) {
    if (error instanceof CursorApiError && error.status < 500) throw error
    if (++failures >= 5) throw error
    await new Promise((resolve) => setTimeout(resolve, 10_000))
    continue
  }
  if (run.status !== lastStatus) log(`Run status: ${run.status}`)
  lastStatus = run.status
  if (terminal.has(run.status)) break
  if (Date.now() > deadline)
    throw new Error('The run is still active after 30 minutes.')
  await new Promise((resolve) => setTimeout(resolve, 10_000))
}

const branch = run.git?.branches?.find((entry) => entry.branch)?.branch
writeFileSync('run.json', `${JSON.stringify({ ...run, branch }, null, 2)}\n`)
if (run.result) log(`\n${run.result}\n`)
if (run.status !== 'FINISHED')
  throw new Error(`The run ended with ${run.status}.`)
if (!branch) throw new Error('The run finished without pushing a branch.')
log(`Pushed branch: ${branch}`)
