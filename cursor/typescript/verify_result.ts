import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { log, projectDir, sandboxes, stopSandbox, waitRunning } from './lib.ts'

const { branch } = JSON.parse(readFileSync('run.json', 'utf8'))
if (!branch) throw new Error('run.json has no pushed branch.')
const repoDir = process.env.TASK_REPO_DIR ?? '../task-repo'
const git = (...args: string[]) =>
  execFileSync('git', ['-C', repoDir, ...args], {
    encoding: 'utf8',
    timeout: 60_000,
  })
const local = (path: string) => fileURLToPath(new URL(path, projectDir))

// Fetch the reported branch without changing the local checkout.
git('fetch', '--quiet', 'origin', branch)
mkdirSync('results', { recursive: true })
writeFileSync('results/total.mjs', git('show', 'FETCH_HEAD:total.mjs'))
writeFileSync(
  'results/report.json',
  git('show', 'FETCH_HEAD:outputs/report.json')
)
for (const name of ['orders.csv', 'test_total.mjs']) {
  if (
    git('show', `FETCH_HEAD:${name}`) !==
    readFileSync(local(`fixture/${name}`), 'utf8')
  ) {
    log(`The branch changed ${name}. Verification uses the original.`)
  }
}
log(`Retrieved total.mjs and outputs/report.json from ${branch}.`)

const created = JSON.parse(
  sandboxes(
    'create',
    '--timeout=600',
    '--network-policy=deny-all',
    '-o',
    'json'
  )
)
const id: string = created.id
log(`Verifying in ${id}`)
try {
  await waitRunning(id)
  sandboxes('exec', id, '--', 'mkdir', '-p', '/workspace/outputs')
  // Use original inputs and tests, even if the agent changed its copies.
  const uploads: [string, string][] = [
    [local('fixture/orders.csv'), '/workspace/orders.csv'],
    [local('fixture/test_total.mjs'), '/workspace/test_total.mjs'],
    [local('verify.mjs'), '/workspace/verify.mjs'],
    ['results/total.mjs', '/workspace/total.mjs'],
    ['results/report.json', '/workspace/outputs/report.json'],
  ]
  for (const [from, to] of uploads) sandboxes('copy', from, `${id}:${to}`)
  try {
    process.stdout.write(
      sandboxes(
        'exec',
        id,
        '--',
        'bash',
        '-lc',
        'cd /workspace && node --test test_total.mjs && node verify.mjs'
      )
    )
  } catch (error) {
    const failed = error as { stdout?: string; stderr?: string }
    process.stdout.write(failed.stdout ?? '')
    process.stderr.write(failed.stderr ?? '')
    throw new Error(
      'Verification failed. Inspect results/total.mjs and results/report.json.'
    )
  }
// Attempt sandbox cleanup even when verification fails.
} finally {
  log(`Verification sandbox ${id} is ${await stopSandbox(id)}.`)
}
