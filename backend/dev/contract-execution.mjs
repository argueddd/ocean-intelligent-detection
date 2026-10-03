/**
 * Real local execution contracts, with no model requests and no fake runners.
 * Requires the project's installed .venv and a macOS host with sandbox-exec.
 * Uses the same SDK sandbox/bash/subprocess services as the Harness profile.
 * Run: /opt/homebrew/bin/node backend/dev/contract-execution.mjs
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import test from 'node:test'
import { Context } from '@deepseek-ai/cordis'
import { SessionProjectionRegistry } from '@deepseek-ai/dsh-session-projection'
import { SandboxPolicyService } from '@deepseek-ai/dsh-sandbox-policy'
import { LocalSubprocessRuntime } from '@deepseek-ai/dsh-subprocess-local'
import { LocalSandboxProvider } from '@deepseek-ai/dsh-sandbox-local'
import { SandboxBashExecutor } from '@deepseek-ai/dsh-bash-sandbox'
import { pythonEnvironment, workspaceRoot } from '../harness/runtime.mjs'

const quote = (value) => "'" + String(value).replaceAll("'", "'\\''") + "'"
const skipReason = process.platform !== 'darwin'
  ? 'This real Seatbelt execution contract requires macOS; it does not emulate a Linux sandbox.'
  : !fs.existsSync(path.join(workspaceRoot, '.venv', 'pyvenv.cfg'))
    ? 'Run ./setup-python.sh first; this contract never falls back to system Python.'
    : false

async function stack() {
  const ctx = new Context()
  try {
    await ctx.plugin(SessionProjectionRegistry)
    await ctx.plugin(SandboxPolicyService, { mode: 'workspace-write', workspaceRoot })
    await ctx.plugin(LocalSubprocessRuntime)
    await ctx.plugin(LocalSandboxProvider, {})
    await ctx.plugin(SandboxBashExecutor, {
      cwd: workspaceRoot,
      timeoutMs: 5000,
      maxTimeoutMs: 10000,
      maxOutputBytes: 65536,
      maxSpillBytes: 1048576,
      graceMs: 150,
    })
    return ctx
  } catch (error) {
    await ctx.fiber.dispose()
    throw error
  }
}

function alive(pid) {
  try { process.kill(pid, 0); return true }
  catch (error) { if (error.code === 'ESRCH') return false; throw error }
}

async function waitUntil(predicate, description, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (predicate()) return
    await delay(25)
  }
  assert.fail(description)
}

async function processesExited(pids) {
  await waitUntil(() => pids.every((pid) => !alive(pid)), `SDK left live Python processes: ${pids.filter(alive).join(', ')}`)
}

test('project Python executes through real SDK sandbox, Bash and managed subprocess services', { skip: skipReason, timeout: 30000 }, async (t) => {
  // Only execution settings are explicitly forwarded. Credentials remain subject
  // to the subprocess provider's ordinary environment scrub.
  const { python, env } = pythonEnvironment(workspaceRoot, { PATH: process.env.PATH || '' })
  const runRoot = fs.mkdtempSync(path.join(workspaceRoot, '.run', 'execution-contract-'))
  const outside = fs.mkdtempSync(path.join(path.dirname(workspaceRoot), '.harness-execution-deny-'))
  let ctx
  const recordedProcesses = []
  t.after(async () => {
    await ctx?.fiber.dispose()
    // Failure cleanup is restricted to processes carrying this fixture's unique
    // path, so a reused PID can never cause an unrelated process to be killed.
    for (const pid of recordedProcesses) {
      if (!alive(pid)) continue
      let command = ''
      try { command = execFileSync('/bin/ps', ['-p', String(pid), '-o', 'command='], { encoding: 'utf8' }) } catch {}
      if (command.includes(runRoot)) { try { process.kill(pid, 'SIGKILL') } catch {} }
    }
    fs.rmSync(runRoot, { recursive: true, force: true })
    fs.rmSync(outside, { recursive: true, force: true })
  })
  ctx = await stack()
  const run = (command, overrides = {}) => ctx.shell.run(ctx.shell.resolve({ command, env, ...overrides }))
  const py = (source, overrides) => run(`python -c ${quote(source)}`, overrides)
  function success(result) {
    assert.equal(result.exitCode, 0, result.stderr.text)
    assert.equal(result.timedOut, false)
    assert.equal(result.aborted, false)
    assert.equal(result.sandbox.mode, 'workspace-write')
    assert.equal(result.sandbox.enforcement, 'full')
  }
  async function recovery() {
    const result = await py('import numpy as np; print(int(np.arange(4).sum()))')
    success(result)
    assert.equal(result.stdout.text.trim(), '6')
  }

  await t.test('python and python3 resolve to the project virtual environment', async () => {
    const source = 'import sys,json,numpy,scipy,matplotlib; print(json.dumps({"executable":sys.executable,"prefix":sys.prefix,"versions":[numpy.__version__,scipy.__version__,matplotlib.__version__]}))'
    for (const command of ['python', 'python3']) {
      const result = await run(`${command} -c ${quote(source)}`)
      success(result)
      const info = JSON.parse(result.stdout.text)
      assert.equal(path.dirname(info.executable), path.dirname(python))
      assert.equal(info.prefix, path.join(workspaceRoot, '.venv'))
      assert.equal(info.versions.length, 3)
    }
  })

  await t.test('Chinese names, spaces and quoted arguments preserve script and artifact paths', async () => {
    const directory = path.join(runRoot, '中文 数据目录')
    const script = path.join(directory, "分析 脚本's.py")
    const artifact = path.join(directory, '分析 结果.json')
    fs.mkdirSync(directory)
    fs.writeFileSync(script, 'import json,pathlib,sys\npathlib.Path(sys.argv[1]).write_text(json.dumps({"argument":sys.argv[2],"cwd":str(pathlib.Path.cwd()),"prefix":sys.prefix},ensure_ascii=False),encoding="utf-8")\n')
    const result = await run(`python ${quote(script)} ${quote(artifact)} ${quote("弱线谱 参数's")}`, { workdir: directory })
    success(result)
    const report = JSON.parse(fs.readFileSync(artifact, 'utf8'))
    assert.equal(report.argument, "弱线谱 参数's")
    assert.equal(report.cwd, directory)
    assert.equal(report.prefix, env.VIRTUAL_ENV)
  })

  await t.test('nonzero exit keeps stdout/stderr and the next execution succeeds', async () => {
    const result = await py('import sys; print("before failure"); print("expected diagnostic",file=sys.stderr); sys.exit(37)')
    assert.equal(result.exitCode, 37)
    assert.match(result.stdout.text, /before failure/)
    assert.match(result.stderr.text, /expected diagnostic/)
    assert.equal(result.sandbox.denied, false)
    await recovery()
  })

  await t.test('missing dependencies remain observable and do not poison later execution', async () => {
    const result = await py('import ocean_execution_contract_missing_package_4729')
    assert.equal(result.exitCode, 1)
    assert.match(result.stderr.text, /ModuleNotFoundError/)
    assert.match(result.stderr.text, /ocean_execution_contract_missing_package_4729/)
    assert.equal(result.sandbox.denied, false)
    await recovery()
  })

  const sleeper = path.join(runRoot, 'hold-process-tree.py')
  fs.writeFileSync(sleeper, [
    'import json,os,pathlib,signal,subprocess,sys,time',
    'signal.signal(signal.SIGTERM,signal.SIG_IGN)',
    'child=subprocess.Popen([sys.executable,"-c","import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(120)",sys.argv[1]])',
    'pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid]))',
    'time.sleep(120)',
    '',
  ].join('\n'))
  function sleepingCommand(record) { return `exec python ${quote(sleeper)} ${quote(record)}` }
  async function recordPids(record) {
    let pids
    await waitUntil(() => {
      try { pids = JSON.parse(fs.readFileSync(record, 'utf8')) } catch { return false }
      return Array.isArray(pids) && pids.length === 2 && pids.every((pid) => Number.isInteger(pid) && pid > 0)
    }, 'Python process did not create its complete startup record')
    recordedProcesses.push(...pids)
    return pids
  }

  await t.test('SDK timeout kills real Python and its child despite ignored SIGTERM', async () => {
    const record = path.join(runRoot, 'timeout-pids.json')
    const result = await run(sleepingCommand(record), { timeoutMs: 1000 })
    const pids = await recordPids(record)
    assert.equal(result.timedOut, true)
    assert.equal(result.aborted, false)
    assert.equal(result.timeoutMs, 1000)
    assert.equal(result.exitCode, null)
    assert.equal(result.signal, 'SIGKILL')
    await processesExited(pids)
    await recovery()
  })

  await t.test('AbortSignal cancellation kills the running Python process tree and execution recovers', async () => {
    const record = path.join(runRoot, 'abort-pids.json')
    const controller = new AbortController()
    const execution = run(sleepingCommand(record), { signal: controller.signal })
    const pids = await recordPids(record)
    assert.ok(pids.every(alive), 'Cancellation must target actual running processes')
    controller.abort(new Error('execution contract cancellation'))
    const result = await execution
    assert.equal(result.aborted, true)
    assert.equal(result.timedOut, false)
    assert.equal(result.exitCode, null)
    assert.equal(result.signal, 'SIGKILL')
    await processesExited(pids)
    await recovery()
  })

  await t.test('project-outside writes fail closed and retain SDK denial classification', async () => {
    const target = path.join(outside, 'denied.txt')
    const result = await py(`from pathlib import Path; Path(${JSON.stringify(target)}).write_text("must not exist")`)
    assert.equal(result.exitCode, 1)
    assert.match(result.stderr.text, /PermissionError|Operation not permitted/)
    assert.equal(result.sandbox.denied, true)
    assert.equal(result.sandbox.enforcement, 'full')
    assert.equal(fs.existsSync(target), false)
    await recovery()
  })

  await t.test('SDK context disposal terminates and joins background Python children', async () => {
    const background = await stack()
    const record = path.join(runRoot, 'dispose-pids.json')
    try {
      const job = await background.shell.start(background.shell.resolve({ command: sleepingCommand(record), env }))
      const pids = await recordPids(record)
      assert.ok(pids.every(alive))
      await background.fiber.dispose()
      await job.done
      assert.equal(job.status, 'killed')
      assert.equal(job.signal, 'SIGKILL')
      await processesExited(pids)
    } finally {
      await background.fiber.dispose()
    }
  })
})
