/** Real SDK cancellation contracts. Deterministic in-process adapter; no network/model calls. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { randomBytes, randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import test from 'node:test'
import { Context } from '@deepseek-ai/cordis'
import { AgentRegistry } from '@deepseek-ai/dsh-agent'
import { AgentLoop } from '@deepseek-ai/dsh-agent-loop'
import { SessionStore } from '@deepseek-ai/dsh-session'
import { SessionProjectionRegistry } from '@deepseek-ai/dsh-session-projection'
import { LlmAdapter, LlmRuntime, createUserMessage } from '@deepseek-ai/dsh-llm'
import { SystemPrompt } from '@deepseek-ai/dsh-system-prompt'
import { ToolRuntime, defineContentToolFixture } from '@deepseek-ai/dsh-tools'
import { LocalJobRegistry } from '@deepseek-ai/dsh-jobs-local'
import { SandboxPolicyService } from '@deepseek-ai/dsh-sandbox-policy'
import { LocalSubprocessRuntime } from '@deepseek-ai/dsh-subprocess-local'
import { LocalSandboxProvider } from '@deepseek-ai/dsh-sandbox-local'
import { SandboxBashExecutor } from '@deepseek-ai/dsh-bash-sandbox'
import * as control from '../dsh/harness-control/lib/index.js'
import { pythonEnvironment, workspaceRoot } from '../harness/runtime.mjs'

const quote = value => "'" + String(value).replaceAll("'", "'\\''") + "'"
const skip = process.platform !== 'darwin' ? 'Real Seatbelt execution requires macOS' : false
const prompt = text => createUserMessage({ content: [{ type: 'text', text }], source: { kind: 'user' } })
function alive(pid) { try { process.kill(pid, 0); return true } catch (error) { if (error.code === 'ESRCH') return false; throw error } }
async function until(check, message, timeoutMs = 5000) {
  const end = Date.now() + timeoutMs
  while (Date.now() < end) { if (check()) return; await delay(10) }
  assert.fail(message)
}
async function freePort() {
  const server = net.createServer()
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const port = server.address().port
  await new Promise(resolve => server.close(resolve))
  return port
}

class OfflineAdapter extends LlmAdapter {
  calls = []
  async *stream(request) {
    this.calls.push(request)
    const message = [...request.messages].reverse().find(value => value.source?.kind === 'user')
    if (message?.content.some(block => block.type === 'text' && block.text === 'wait-model')) {
      await delay(120000, undefined, { signal: request.signal })
    }
    const hold = message?.content.some(block => block.type === 'text' && block.text === 'hold')
    if (hold) {
      const id = `call-${randomUUID()}`
      const block = { type: 'tool-call', id, name: 'contract_hold', arguments: {} }
      yield { type: 'block-start', index: 0, blockType: 'tool-call' }
      yield { type: 'tool-call-delta', index: 0, id, name: block.name, argumentsDelta: '{}' }
      yield { type: 'block-end', index: 0, block }
      yield { type: 'finish', reason: { kind: 'tool-calls' } }
    } else {
      yield { type: 'block-start', index: 0, blockType: 'text' }
      yield { type: 'text-delta', index: 0, text: 'offline follow-up completed' }
      yield { type: 'block-end', index: 0, block: { type: 'text', text: 'offline follow-up completed' } }
      yield { type: 'finish', reason: { kind: 'stop' } }
    }
  }
}

async function fixture(t, timeoutMs = 4000) {
  const root = fs.mkdtempSync(path.join(workspaceRoot, '.run', 'control-contract-'))
  const ctx = new Context()
  const pids = []
  t.after(async () => {
    // Stop every fixture-owned producer before disposing the service graph.
    for (const agent of ctx.agents?.list() || []) agent.cancel({ kind: 'user' })
    for (const agent of ctx.agents?.list() || []) for (const job of ctx.jobs?.list(agent) || []) if (job.ownerSession === agent.id && (job.status === 'running' || job.status === 'stopping')) ctx.jobs.kill(job.id, agent)
    for (const job of ctx.jobs?.list() || []) if (job.status === 'running' || job.status === 'stopping') ctx.jobs.kill(job.id)
    await Promise.all((ctx.agents?.list() || []).map(agent => agent.whenIdle()))
    for (const agent of ctx.agents?.list() || []) for (const job of ctx.jobs?.list(agent) || []) if (job.ownerSession === agent.id) await ctx.jobs.wait(job.id, 2000, agent)
    for (const job of ctx.jobs?.list() || []) await ctx.jobs.wait(job.id, 2000)
    await ctx.fiber.dispose()
    for (const pid of pids) {
      if (!alive(pid)) continue
      let command = ''
      try { command = execFileSync('/bin/ps', ['-p', String(pid), '-o', 'command='], { encoding: 'utf8' }) } catch {}
      if (command.includes(root)) { try { process.kill(pid, 'SIGKILL') } catch {} }
    }
    fs.rmSync(root, { recursive: true, force: true })
  })
  await ctx.plugin(SessionProjectionRegistry)
  await ctx.plugin(SessionStore)
  await ctx.plugin(AgentRegistry)
  await ctx.plugin(LlmRuntime)
  await ctx.plugin(SystemPrompt, {})
  await ctx.plugin(ToolRuntime)
  await ctx.plugin(AgentLoop, { agents: [] })
  await ctx.plugin(LocalJobRegistry, {})
  ctx.jobs.attachController('control-contract')
  await ctx.plugin(SandboxPolicyService, { mode: 'workspace-write', workspaceRoot })
  await ctx.plugin(LocalSubprocessRuntime)
  await ctx.plugin(LocalSandboxProvider, {})
  await ctx.plugin(SandboxBashExecutor, { cwd: workspaceRoot, timeoutMs: 120000, maxTimeoutMs: 120000, graceMs: 50 })
  const adapter = new OfflineAdapter()
  ctx.llm.registerAdapter(['offline-control-contract'], adapter)
  const env = pythonEnvironment(workspaceRoot, { PATH: process.env.PATH || '' }).env
  const script = path.join(root, 'hold.py')
  fs.writeFileSync(script, [
    'import json,os,pathlib,signal,subprocess,sys,time',
    'signal.signal(signal.SIGTERM,signal.SIG_IGN)',
    'child=subprocess.Popen([sys.executable,"-c","import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(120)",sys.argv[1]])',
    'pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid]))',
    'time.sleep(120)', '',
  ].join('\n'))
  const record = label => path.join(root, `${label}-pids.json`)
  const command = label => `exec python ${quote(script)} ${quote(record(label))}`
  const executions = new Map()
  ctx.tools.register(defineContentToolFixture({
    name: 'contract_hold', description: 'Offline cancellation contract process tree', parameters: {},
    async execute(_args, exec) {
      const result = await ctx.shell.run(ctx.shell.resolve({ command: command(exec.agent.id), env, signal: exec.signal }))
      executions.set(exec.agent.id, { result, signal: exec.signal })
      return [{ type: 'text', text: 'process tree ended' }]
    },
  }))
  const statuses = []
  ctx.on('agent/status', ({ agent, status }) => statuses.push({ id: agent.id, status }))
  const port = await freePort()
  const token = randomBytes(32).toString('hex')
  const previous = { port: process.env.HARNESS_CONTROL_PORT, token: process.env.HARNESS_CONTROL_TOKEN }
  process.env.HARNESS_CONTROL_PORT = String(port)
  process.env.HARNESS_CONTROL_TOKEN = token
  let plugin
  try { plugin = await ctx.plugin(control, { timeoutMs }) }
  finally {
    if (previous.port === undefined) delete process.env.HARNESS_CONTROL_PORT; else process.env.HARNESS_CONTROL_PORT = previous.port
    if (previous.token === undefined) delete process.env.HARNESS_CONTROL_TOKEN; else process.env.HARNESS_CONTROL_TOKEN = previous.token
  }
  const url = `http://127.0.0.1:${port}/cancel`
  async function request(body, options = {}) {
    const response = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json', authorization: `Bearer ${token}`, ...options.headers }, body: JSON.stringify(body), ...options })
    return { code: response.status, data: await response.json() }
  }
  async function agent(id, parentAgent, meta) {
    return (await ctx.agents.create({ sessionId: id, parentAgent, meta: { cwd: workspaceRoot, ...meta }, agentOptions: { provider: 'offline-control-contract', model: 'deterministic' } })).agent
  }
  async function started(label) {
    let tree
    await until(() => {
      try { tree = JSON.parse(fs.readFileSync(record(label), 'utf8')) } catch { return false }
      return Array.isArray(tree) && tree.length === 2 && tree.every(Number.isSafeInteger)
    }, `No real Python startup record for ${label}`)
    pids.push(...tree)
    assert.ok(tree.every(alive))
    return tree
  }
  function background(label, owner) {
    return ctx.jobs.start({ kind: 'bash', label, owner, run() {
      const abort = new AbortController()
      const done = ctx.shell.run(ctx.shell.resolve({ command: command(label), env, signal: abort.signal })).then(result => ({ status: result.aborted ? 'killed' : result.exitCode === 0 ? 'completed' : 'failed' }))
      return { cancel: () => abort.abort({ kind: 'user' }), done }
    } })
  }
  return { root, ctx, plugin, url, request, agent, started, background, executions, statuses, adapter }
}

test('control environment rejects missing or invalid secrets/ports without echoing secrets', () => {
  assert.throws(() => control.environmentConfig({}), /HARNESS_CONTROL_PORT/)
  assert.throws(() => control.environmentConfig({ HARNESS_CONTROL_PORT: '3091' }), /HARNESS_CONTROL_TOKEN/)
  assert.throws(() => control.environmentConfig({ HARNESS_CONTROL_PORT: '3091', HARNESS_CONTROL_TOKEN: 'bad secret' }), error => !error.message.includes('bad secret'))
  for (const port of ['0', '65536', '1.5', 'NaN']) assert.throws(() => control.environmentConfig({ HARNESS_CONTROL_PORT: port, HARNESS_CONTROL_TOKEN: 'test-secret' }))
  assert.deepEqual(control.environmentConfig({ HARNESS_CONTROL_PORT: '3091', HARNESS_CONTROL_TOKEN: 'test-secret' }), { port: 3091, token: 'test-secret', timeoutMs: 30000 })
  assert.deepEqual(control.inject, ['agents', 'jobs'])
})

test('authenticated loopback cancellation drains real Agent turns, tool process trees and owned jobs only', { skip, timeout: 30000 }, async t => {
  const f = await fixture(t)
  const root = await f.agent('target-root')
  const child = await f.agent('target-child', root)
  const grandchild = await f.agent('target-grandchild', child)
  // Durable lineage alone must not make this independent runtime root a target.
  const other = await f.agent('other-root', undefined, { parentSession: root.id })

  await t.test('invalid token, malformed body and missing session leave the agents untouched', async () => {
    assert.equal((await f.request({ sessionId: root.id }, { headers: { authorization: 'Bearer wrong' } })).code, 401)
    assert.equal((await f.request({ sessionId: '' })).code, 400)
    assert.equal((await f.request({ sessionId: root.id, all: true })).code, 400)
    const missing = await f.request({ sessionId: 'unknown-session' })
    assert.equal(missing.code, 404)
    assert.equal(missing.data.status, 'session_not_found')
    const method = await f.request(undefined, { method: 'GET', body: undefined })
    assert.equal(method.code, 405)
    assert.equal(root.status, 'idle')
  })

  const targetPids = []
  const otherPids = []
  for (const agent of [root, child, grandchild, other]) {
    agent.followup(prompt('hold'))
    const tree = await f.started(agent.id)
    ;(agent === other ? otherPids : targetPids).push(...tree)
    assert.equal(agent.status, 'running')
  }
  const rootJob = f.background('root-background', root)
  const childJob = f.background('child-background', child)
  const otherJob = f.background('other-background', other)
  const unownedJob = f.background('unowned-background')
  targetPids.push(...await f.started('root-background'), ...await f.started('child-background'))
  otherPids.push(...await f.started('other-background'), ...await f.started('unowned-background'))
  const pending = prompt('parked context')
  root.inject(pending)

  await t.test('concurrent cancellation converges to idle and kills foreground/background descendants', async () => {
    const replies = await Promise.all([f.request({ sessionId: root.id }), f.request({ sessionId: root.id })])
    for (const reply of replies) {
      assert.equal(reply.code, 200, JSON.stringify(reply.data))
      assert.equal(reply.data.status, 'cancelled')
      assert.equal(reply.data.agentStatus, 'idle')
      assert.deepEqual(new Set(reply.data.cancelledSessionIds), new Set([root.id, child.id, grandchild.id]))
      assert.deepEqual(new Set(reply.data.cancelledJobIds), new Set([rootJob, childJob]))
    }
    await until(() => targetPids.every(pid => !alive(pid)), 'Real target Python processes survived successful cancellation')
    for (const agent of [root, child, grandchild]) {
      assert.equal(agent.status, 'idle')
      assert.equal(f.ctx.agents.get(agent.id), agent)
      assert.equal(f.executions.get(agent.id).result.aborted, true)
      assert.equal(f.executions.get(agent.id).signal.aborted, true)
      assert.ok(f.statuses.some(value => value.id === agent.id && value.status === 'idle'))
    }
    assert.equal(f.ctx.jobs.get(rootJob, root).status, 'killed')
    assert.equal(f.ctx.jobs.get(childJob, child).status, 'killed')
    assert.ok(root.inbox.nextStep.some(message => message.id === pending.id), 'keepInbox lost parked context')
  })

  await t.test('unrelated session and unowned jobs continue running', () => {
    assert.equal(other.status, 'running')
    assert.equal(f.ctx.jobs.get(otherJob, other).status, 'running')
    assert.equal(f.ctx.jobs.get(unownedJob).status, 'running')
    assert.ok(otherPids.every(alive))
  })

  await t.test('same session accepts a follow-up after cancellation and repeat idle cancel is harmless', async () => {
    const before = f.adapter.calls.length
    root.followup(prompt('resume'))
    await root.whenIdle()
    assert.ok(f.adapter.calls.length > before)
    assert.equal(root.status, 'idle')
    assert.ok(root.session.snapshotEvents().some(event => event.type === 'assistant/message' && event.data.message.content.some(block => block.type === 'text' && block.text === 'offline follow-up completed')))
    const repeat = await f.request({ sessionId: root.id })
    assert.equal(repeat.code, 200)
    assert.equal(repeat.data.status, 'idle')
    assert.deepEqual(repeat.data.cancelledJobIds, [])
  })

  await t.test('plugin disposal closes listener while retaining the shared runtime and other session', async () => {
    await f.plugin.dispose()
    await assert.rejects(fetch(f.url, { method: 'POST' }))
    assert.equal(f.ctx.agents.get(root.id), root)
    assert.equal(other.status, 'running')
    assert.ok(otherPids.every(alive))
  })
})

test('non-cooperating maintenance returns timeout without falsely claiming idle', { skip, timeout: 10000 }, async t => {
  const f = await fixture(t, 40)
  const agent = await f.agent('uncooperative')
  let release
  let aborted = false
  const maintenance = agent.runMaintenance(async signal => {
    signal.addEventListener('abort', () => { aborted = true }, { once: true })
    await new Promise(resolve => { release = resolve })
  })
  try {
    const response = await f.request({ sessionId: agent.id })
    assert.equal(response.code, 504)
    assert.equal(response.data.status, 'cancel_timeout')
    assert.equal(response.data.ok, false)
    assert.equal(aborted, true)
  } finally { release() }
  await maintenance
  await agent.whenIdle()
  assert.equal((await f.request({ sessionId: agent.id })).data.status, 'idle')
})

test('a real AgentLoop model-stream wait is cancelled and the same session resumes', { skip, timeout: 10000 }, async t => {
  const f = await fixture(t)
  const agent = await f.agent('model-stream-wait')
  agent.followup(prompt('wait-model'))
  await until(() => f.adapter.calls.length > 0, 'The real LlmRuntime did not dispatch the offline model stream')
  const request = f.adapter.calls[0]
  assert.equal(agent.status, 'running')
  assert.equal(request.signal.aborted, false)
  const response = await f.request({ sessionId: agent.id })
  assert.equal(response.code, 200)
  assert.equal(response.data.status, 'cancelled')
  assert.equal(request.signal.aborted, true)
  assert.equal(agent.status, 'idle')
  const turn = agent.session.snapshotEvents().filter(event => event.type === 'turn/end').at(-1)
  assert.equal(turn.data.reason.kind, 'aborted')
  assert.equal(turn.data.reason.reason.kind, 'user')
  agent.followup(prompt('resume'))
  await agent.whenIdle()
  assert.equal(f.adapter.calls.length, 2)
  assert.equal(agent.status, 'idle')
})

test('disposing the bridge releases an in-flight HTTP wait without disposing its session', { skip, timeout: 10000 }, async t => {
  const f = await fixture(t, 4000)
  const agent = await f.agent('shutdown-wait')
  let release
  let aborted = false
  const maintenance = agent.runMaintenance(async signal => {
    signal.addEventListener('abort', () => { aborted = true }, { once: true })
    await new Promise(resolve => { release = resolve })
  })
  const response = f.request({ sessionId: agent.id }).then(value => value, () => ({ code: 'connection_closed' }))
  try {
    await until(() => aborted, 'Bridge did not reach the real active Agent')
    await f.plugin.dispose()
    const result = await response
    assert.ok(result.code === 'connection_closed' || result.code === 503)
    assert.equal(f.ctx.agents.get(agent.id), agent)
    await assert.rejects(fetch(f.url, { method: 'POST' }))
  } finally { release(); await maintenance }
})
