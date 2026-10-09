import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  CursorApiError,
  cursorApi,
  cursorDir,
  log,
  stopSandbox,
} from './lib.ts'

const { agentId } = JSON.parse(readFileSync('agent.json', 'utf8'))
let failed = false

// Continue to Render cleanup even if the Cursor API is unavailable.
for (const [method, path] of [
  ['POST', `/v1/agents/${agentId}/archive`],
  ['DELETE', `/v1/agents/${agentId}`],
]) {
  try {
    await cursorApi(method, path)
  } catch (error) {
    if (error instanceof CursorApiError && error.status === 404) continue
    console.error(`${method} ${path}: ${(error as Error).message}`)
    failed = true
  }
}
if (!failed) log(`Cursor agent ${agentId} archived and deleted.`)

// Select only sandbox IDs recorded for this agent, leaving other runs alone.
const claims = fileURLToPath(new URL('claims.tsv', cursorDir))
const sandboxIds = existsSync(claims)
  ? readFileSync(claims, 'utf8')
      .split('\n')
      .map((line) => line.split('\t'))
      .filter(([request, sandbox]) => request === agentId && sandbox)
      .map(([, sandbox]) => sandbox)
  : []
if (sandboxIds.length === 0) log(`No worker sandbox recorded for ${agentId}.`)
for (const id of sandboxIds) {
  try {
    const status = await stopSandbox(id)
    log(`Worker sandbox ${id} is ${status}.`)
    if (status !== 'terminated' && status !== 'errored') failed = true
  } catch (error) {
    console.error(`stop ${id}: ${(error as Error).message}`)
    failed = true
  }
}
if (failed) process.exit(1)
