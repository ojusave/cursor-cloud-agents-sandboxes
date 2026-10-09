import { execFileSync } from 'node:child_process'

export const projectDir = new URL('../../', import.meta.url)
export const cursorDir = new URL('../', import.meta.url)

/** Print one line to stdout. */
export function log(line: string): void {
  process.stdout.write(`${line}\n`)
}

/** Run a `render ea sandboxes` subcommand and return its stdout. */
export function sandboxes(...args: string[]): string {
  return execFileSync('render', ['ea', 'sandboxes', ...args], {
    encoding: 'utf8',
    timeout: 120_000,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
}

/** Return a sandbox's status, or "missing" if the workspace has no such sandbox. */
export function sandboxStatus(id: string): string {
  const rows = JSON.parse(sandboxes('list', '--all', '-o', 'json')) ?? []
  return rows.find((row: { id: string }) => row.id === id)?.status ?? 'missing'
}

/** Wait up to two minutes for a sandbox to accept commands. */
export async function waitRunning(id: string): Promise<void> {
  for (let attempt = 0; attempt < 60; attempt++) {
    const status = sandboxStatus(id)
    if (status === 'running') return
    if (status === 'errored' || status === 'terminated') {
      throw new Error(`sandbox ${id} is ${status}`)
    }
    await new Promise((resolve) => setTimeout(resolve, 2000))
  }
  throw new Error(`sandbox ${id} did not reach running`)
}

/** Request a stop and confirm a terminal state, preserving an error status. */
export async function stopSandbox(id: string): Promise<string> {
  if (sandboxStatus(id) !== 'terminated')
    sandboxes('stop', id, '--confirm', '-o', 'json')
  for (let attempt = 0; attempt < 30; attempt++) {
    const status = sandboxStatus(id)
    if (status === 'terminated' || status === 'errored') return status
    await new Promise((resolve) => setTimeout(resolve, 2000))
  }
  throw new Error(`sandbox ${id} did not reach a terminal state`)
}

export class CursorApiError extends Error {
  constructor(
    readonly status: number,
    body: string
  ) {
    super(`Cursor API returned ${status}: ${body.slice(0, 500)}`)
  }
}

/** Call the Cursor Cloud Agents API with the user API key. */
// Helpers use the user key; the controller uses a separate service account key.
export async function cursorApi(method: string, path: string, body?: unknown) {
  const key = process.env.CURSOR_USER_API_KEY
  if (!key) throw new Error('Set CURSOR_USER_API_KEY first.')
  const base = process.env.CURSOR_API_ENDPOINT ?? 'https://api.cursor.com'
  const response = await fetch(`${base}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${key}`,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(30_000),
  })
  const text = await response.text()
  if (!response.ok) throw new CursorApiError(response.status, text)
  return text ? JSON.parse(text) : {}
}
