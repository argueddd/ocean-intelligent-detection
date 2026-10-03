import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { pythonEnvironment } from '../harness/runtime.mjs'
import { prepareHarnessHome } from '../integrations.js'
import { runHarnessTask } from '../harness/task.mjs'

function temporary(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ocean-harness-contract-'))
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }))
  return dir
}

test('missing project venv fails instead of executing a system interpreter', (t) => {
  assert.throws(() => pythonEnvironment(temporary(t)), /setup-python/)
})

test('project Python overrides inherited Python paths without mutating the parent', (t) => {
  const root = temporary(t)
  const venv = path.join(root, '.venv')
  const bin = path.join(venv, process.platform === 'win32' ? 'Scripts' : 'bin')
  fs.mkdirSync(bin, { recursive: true })
  fs.writeFileSync(path.join(venv, 'pyvenv.cfg'), '')
  const executable = path.join(bin, process.platform === 'win32' ? 'python.exe' : 'python')
  fs.writeFileSync(executable, '', { mode: 0o755 })
  const parent = { PATH: '/system/bin', PYTHONHOME: '/other/python', PYTHONPATH: '/other/packages', VIRTUAL_ENV: '/other/venv' }
  const { python, env } = pythonEnvironment(root, parent)
  assert.equal(python, executable)
  assert.equal(env.HARNESS_PYTHON, executable)
  assert.equal(env.VIRTUAL_ENV, venv)
  assert.equal(env.PATH.split(path.delimiter)[0], bin)
  assert.equal(env.PYTHONHOME, undefined)
  assert.equal(env.PYTHONPATH, undefined)
  assert.equal(parent.PYTHONHOME, '/other/python')
  assert.equal(env.MPLBACKEND, 'Agg')
})

test('standalone profile requires no knowledge plugins and does not open a KB webserver', (t) => {
  const root = temporary(t)
  const profile = path.join(root, 'dsh/home/profiles/harness')
  fs.mkdirSync(profile, { recursive: true })
  fs.writeFileSync(path.join(profile, 'package.json'), JSON.stringify({ dsh: { profile: { bundles: [] } } }))
  const home = path.join(root, 'runtime')
  const patch = prepareHarnessHome(home, root, { profile: 'harness' })
  assert.deepEqual(JSON.parse(fs.readFileSync(patch, 'utf8')), [])
  assert.deepEqual(fs.readdirSync(path.join(profile, 'node_modules')), [])
  assert.equal(fs.realpathSync(path.join(home, 'profiles')), fs.realpathSync(path.join(root, 'dsh/home/profiles')))
})

test('legacy profile keeps manifest-linked dependencies and its webserver on repeated setup', (t) => {
  const root = temporary(t)
  const profile = path.join(root, 'dsh/home/profiles/rag-kb')
  const plugin = path.join(root, 'dsh/local-plugin')
  fs.mkdirSync(profile, { recursive: true })
  fs.mkdirSync(plugin, { recursive: true })
  fs.writeFileSync(path.join(profile, 'package.json'), JSON.stringify({ dependencies: { 'local-plugin': 'link:../../../local-plugin' } }))
  const home = path.join(root, 'runtime')
  prepareHarnessHome(home, root, { profile: 'rag-kb' })
  const patch = prepareHarnessHome(home, root, { profile: 'rag-kb' })
  assert.equal(fs.realpathSync(path.join(profile, 'node_modules/local-plugin')), fs.realpathSync(plugin))
  assert.equal(JSON.parse(fs.readFileSync(patch, 'utf8'))[0].id, 'webserver')
})

test('identical home preparation does not rewrite watched configuration files', (t) => {
  const root = temporary(t)
  const profile = path.join(root, 'dsh/home/profiles/harness')
  fs.mkdirSync(profile, { recursive: true })
  fs.writeFileSync(path.join(profile, 'package.json'), '{}')
  const home = path.join(root, 'runtime')
  const patch = prepareHarnessHome(home, root, { profile: 'harness' })
  const files = [patch, path.join(home, 'settings.yaml')]
  for (const file of files) fs.utimesSync(file, 100, 100)
  prepareHarnessHome(home, root, { profile: 'harness' })
  for (const file of files) assert.equal(fs.statSync(file).mtimeMs, 100000)
})

function stalledHarness(event) {
  let rejectActivity
  const harness = {
    closeCount: 0,
    session() { return {
      id: 'root',
      run(_prompt, options) {
        return new Promise((_resolve, reject) => {
          rejectActivity = reject
          if (event) queueMicrotask(() => options.onNotification({ method: 'session.event', params: { sessionId: 'root', event } }))
        })
      },
    } },
    async close() { this.closeCount++; rejectActivity?.(new Error('transport closed')) },
  }
  return harness
}

test('root abort closes runtime even if the SDK never publishes idle', async () => {
  const harness = stalledHarness({ type: 'turn/end', data: { reason: { kind: 'aborted', reason: { kind: 'disposed' } } } })
  await assert.rejects(runHarnessTask(harness, 'task', { timeoutMs: 1000 }), /aborted/)
  assert.equal(harness.closeCount, 1)
})

test('root model error reports the original cause and closes the owned runtime', async () => {
  const harness = stalledHarness({ type: 'turn/end', data: { reason: { kind: 'error', error: { message: 'provider unavailable' } } } })
  await assert.rejects(runHarnessTask(harness, 'task', { timeoutMs: 1000 }), /provider unavailable/)
  assert.equal(harness.closeCount, 1)
})

test('whole task deadline closes a runtime that produces no terminal event', async () => {
  const harness = stalledHarness()
  await assert.rejects(runHarnessTask(harness, 'task', { timeoutMs: 20 }), /超过 20ms/)
  assert.equal(harness.closeCount, 1)
})

test('a descendant failure does not cancel a successful root session', async () => {
  let closed = 0
  const result = { finalResponse: 'done', events: [] }
  const harness = {
    session() { return { id: 'root', async run(_prompt, options) {
      options.onNotification({ method: 'session.event', params: { sessionId: 'child', event: { type: 'turn/end', data: { reason: { kind: 'error' } } } } })
      return result
    } } },
    async close() { closed++ },
  }
  assert.equal(await runHarnessTask(harness, 'task', { timeoutMs: 1000 }), result)
  assert.equal(closed, 0)
})
