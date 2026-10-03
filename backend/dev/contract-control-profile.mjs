/** Boot the real project profile through the actual SDK; never send model prompts. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import net from 'node:net'
import { createServer } from 'node:http'
import { randomBytes } from 'node:crypto'
import { performance, monitorEventLoopDelay } from 'node:perf_hooks'
import test from 'node:test'
import { DeepSeekHarness } from '@deepseek-ai/dsh-sdk-client'
import { prepareHarnessHome } from '../integrations.js'
import { backendDir, pythonEnvironment, workspaceRoot } from '../harness/runtime.mjs'

async function freePort() {
  const server = net.createServer()
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const port = server.address().port
  await new Promise(resolve => server.close(resolve))
  return port
}

async function fixture(t, enabled) {
  const started = performance.now()
  const label = enabled ? 'enabled' : 'disabled'
  const lag = monitorEventLoopDelay({ resolution: 100 })
  lag.enable()
  const trace = stage => process.stderr.write(`[control-profile] ${label} ${stage} elapsedMs=${Math.round(performance.now() - started)}\n`)
  const phase = async (name, run) => {
    trace(`${name}.begin`)
    try { const result = await run(); trace(`${name}.done`); return result }
    catch (error) { trace(`${name}.failed:${error.name}`); throw error }
  }
  const directory = fs.mkdtempSync(path.join(workspaceRoot, '.run', 'control-profile-contract-'))
  const home = path.join(directory, 'harness-home')
  let modelRequests = 0
  const modelServer = createServer((_req, res) => {
    modelRequests++
    res.writeHead(503, { 'content-type': 'application/json' })
    res.end('{"error":"This profile contract forbids model requests"}')
  })
  await new Promise(resolve => modelServer.listen(0, '127.0.0.1', resolve))
  const modelURL = `http://127.0.0.1:${modelServer.address().port}/v1`
  const port = await freePort()
  const token = enabled ? randomBytes(32).toString('hex') : undefined
  const parentControlPort = process.env.HARNESS_CONTROL_PORT
  const parentControlToken = process.env.HARNESS_CONTROL_TOKEN
  // SDK env replaces the parent entirely. Forward only basic OS execution
  // settings, never real service/model credentials or control configuration.
  const baseEnv = Object.fromEntries(['PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'TZ']
    .filter(key => process.env[key] !== undefined).map(key => [key, process.env[key]]))
  const { env } = pythonEnvironment(workspaceRoot, {
    ...baseEnv,
    DSH_TELEMETRY_MODE: 'DISABLED',
    LLM_PROVIDER: 'aliyun', LLM_MODEL: 'qwen3.8-flash',
    LLM_BASE_URL: modelURL, LLM_API_KEY: 'profile-contract-fixture-key',
    VLM_MODEL: 'qwen3.8-omni-flash', VLM_BASE_URL: modelURL,
    VLM_API_KEY: 'profile-contract-fixture-vision-key',
    HARNESS_CONTROL_PORT: String(port),
    ...(enabled ? { HARNESS_CONTROL_TOKEN: token } : {}),
  })
  // Use the production composition helper and original profile symlink.
  // createProjectHarness currently inherits process.env; build its same SDK
  // options explicitly so this test never mutates the running server's env.
  const patch = prepareHarnessHome(home, backendDir, { profile: 'harness' })
  // Provider settings belong to this disposable home. Replace generated
  // parent-derived endpoints with the local sentinel, retaining real YAML.
  fs.writeFileSync(path.join(home, 'settings.yaml'), JSON.stringify({
    'agent-presets': { default: 'cordis' },
    'agent-default-model': { provider: 'aliyun', model: 'qwen3.8-flash' },
    'llm-pi-ai': { providers: {
      aliyun: { baseURL: modelURL, api: 'openai-completions', apiKeyEnv: 'LLM_API_KEY',
        models: [{ id: 'qwen3.8-flash', name: 'qwen3.8-flash', input: ['text'], contextWindow: 32768, maxTokens: 4096 }] },
      'aliyun-vision': { baseURL: modelURL, api: 'openai-completions', apiKeyEnv: 'VLM_API_KEY',
        models: [{ id: 'qwen3.8-omni-flash', name: 'qwen3.8-omni-flash', input: ['text', 'image'], contextWindow: 32768, maxTokens: 4096 }] },
    } },
  }, null, 2) + '\n')
  const harness = new DeepSeekHarness({
    profile: 'harness', cwd: workspaceRoot, processCwd: workspaceRoot,
    dshHome: home, patches: [patch], env,
    provider: 'aliyun', model: 'qwen3.8-flash', maxTokens: 1024,
    initializeTimeoutMs: 15000,
    // Keep failed initialization plus the SDK's complete EOF/TERM/KILL
    // cleanup inside the unchanged 25s test deadline. The SDK defaults
    // (6s EOF + 3s per termination stage) can otherwise hide its first error
    // behind a whole-test timeout when initialize has already taken 15s.
    shutdownTimeoutMs: 1000, disposeEofGraceMs: 1000, disposeGraceMs: 1000,
  })
  let closing
  const close = () => closing ??= phase('sdk.close', () => harness.close())
  t.after(async () => {
    try { await close() }
    finally {
      modelServer.closeAllConnections()
      await new Promise(resolve => modelServer.close(resolve))
      fs.rmSync(directory, { recursive: true, force: true })
      lag.disable()
      trace(`cleanup.done:eventLoopMaxMs=${Math.round(lag.max / 1e6)}`)
    }
    assert.ok(process.env.HARNESS_CONTROL_PORT === parentControlPort, 'Parent control port changed')
    assert.ok(process.env.HARNESS_CONTROL_TOKEN === parentControlToken, 'Parent control token changed')
    assert.equal(modelRequests, 0, 'Startup/close must not call a model')
  })
  const actualProfile = path.join(backendDir, 'dsh/home/profiles/harness')
  assert.equal(fs.realpathSync(path.join(home, 'profiles/harness')), fs.realpathSync(actualProfile))
  const manifest = JSON.parse(fs.readFileSync(path.join(actualProfile, 'package.json'), 'utf8'))
  assert.ok(manifest.dsh.profile.bundles.includes('ocean-harness-control'))
  assert.ok(!('HARNESS_CONTROL_TOKEN' in env) === !enabled)
  trace('fixture.ready')
  return { harness, start: () => phase('sdk.start', () => harness.start()), close,
    url: `http://127.0.0.1:${port}/cancel`, token, requests: () => modelRequests }
}

test('real Harness profile starts and closes with cancellation plugin disabled when token is absent', { timeout: 25000 }, async t => {
  const f = await fixture(t, false)
  await f.start()
  await assert.rejects(fetch(f.url, { method: 'POST', signal: AbortSignal.timeout(500) }))
  assert.equal(f.requests(), 0)
  await f.close()
  await f.harness.close()
})

test('real Harness profile loads authenticated cancellation plugin and closes its listener', { timeout: 25000 }, async t => {
  const f = await fixture(t, true)
  await f.start()
  const unauthorized = await fetch(f.url, {
    method: 'POST', headers: { 'content-type': 'application/json', authorization: 'Bearer invalid' },
    body: JSON.stringify({ sessionId: 'profile-contract-unattached' }), signal: AbortSignal.timeout(2000),
  })
  assert.equal(unauthorized.status, 401)
  assert.equal((await unauthorized.json()).status, 'unauthorized')
  const response = await fetch(f.url, {
    method: 'POST', headers: { 'content-type': 'application/json', authorization: `Bearer ${f.token}` },
    body: JSON.stringify({ sessionId: 'profile-contract-unattached' }), signal: AbortSignal.timeout(2000),
  })
  assert.equal(response.status, 404)
  assert.equal((await response.json()).status, 'session_not_found')
  assert.equal(f.requests(), 0)
  await f.close()
  await assert.rejects(fetch(f.url, { method: 'POST', signal: AbortSignal.timeout(500) }))
})
