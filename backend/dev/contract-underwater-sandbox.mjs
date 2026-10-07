/** 正式 Skill 的行为测试通过 SDK 文件沙箱和项目 .venv 执行，不请求模型。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { Context } from '@deepseek-ai/cordis'
import { SessionProjectionRegistry } from '@deepseek-ai/dsh-session-projection'
import { SandboxPolicyService } from '@deepseek-ai/dsh-sandbox-policy'
import { LocalSubprocessRuntime } from '@deepseek-ai/dsh-subprocess-local'
import { LocalSandboxProvider } from '@deepseek-ai/dsh-sandbox-local'
import { SandboxBashExecutor } from '@deepseek-ai/dsh-bash-sandbox'
import { workspaceRoot, pythonEnvironment } from '../harness/runtime.mjs'

const quote = value => "'" + String(value).replaceAll("'", "'\\''") + "'"
const skip = process.platform !== 'darwin' ? '真实 Seatbelt 集成测试需要 macOS。' : false
test('正式水声 Skill 的行为测试使用真实 SDK sandbox 和项目 Python', { skip, timeout: 180000 }, async t => {
  const dir = fs.mkdtempSync(path.join(workspaceRoot, '.run', 'underwater-sandbox-'))
  const { python, env } = pythonEnvironment(workspaceRoot, { PATH: process.env.PATH, TMPDIR: dir })
  const ctx = new Context()
  t.after(() => ctx.fiber.dispose())
  await ctx.plugin(SessionProjectionRegistry)
  await ctx.plugin(SandboxPolicyService, { mode: 'workspace-write', workspaceRoot })
  await ctx.plugin(LocalSubprocessRuntime)
  await ctx.plugin(LocalSandboxProvider, {})
  await ctx.plugin(SandboxBashExecutor, { cwd: workspaceRoot, timeoutMs: 90000, maxTimeoutMs: 120000, maxOutputBytes: 1048576 })
  const summary = { python, sandbox: 'workspace-write', suites: [] }
  for (const [name, command] of [
    ['provided-skill-tests', `${quote(python)} -m unittest discover -s ${quote(path.join(workspaceRoot, 'skills/underwater-data-inspection/tests'))} -v`],
    ['independent-forward-tests', `${quote(python)} ${quote(path.join(workspaceRoot, 'backend/dev/contract-underwater-inspection.py'))} -v`],
    ['beamforming-provided-tests', `${quote(python)} -B -W error::RuntimeWarning -m unittest discover -s ${quote(path.join(workspaceRoot, 'skills/underwater-beamforming/tests'))} -v`],
    ['beamforming-handoff-tests', `${quote(python)} -B -W error::RuntimeWarning ${quote(path.join(workspaceRoot, 'backend/dev/contract-beamforming.py'))} -v`],
    ['beamforming-evaluation-tests', `${quote(python)} -B -W error::RuntimeWarning -m unittest discover -s ${quote(path.join(workspaceRoot, 'skills/underwater-beamforming-evaluation/tests'))} -v`],
    ['beamforming-evaluation-integration-tests', `${quote(python)} -B -W error::RuntimeWarning ${quote(path.join(workspaceRoot, 'backend/dev/contract-beamforming-evaluation.py'))} -v`],
    ['line-spectrum-evaluation-tests', `${quote(python)} -B -W error::RuntimeWarning -m unittest discover -s ${quote(path.join(workspaceRoot, 'skills/underwater-line-spectrum-evaluation/tests'))} -v`],
    ['line-spectrum-integration-tests', `${quote(python)} -B -W error::RuntimeWarning ${quote(path.join(workspaceRoot, 'backend/dev/contract-line-spectrum.py'))} -v`],
    ['line-spectrum-tracking-tests', `${quote(python)} -B -W error::RuntimeWarning -m unittest discover -s ${quote(path.join(workspaceRoot, 'skills/underwater-line-spectrum-tracking/tests'))} -v`],
    ['line-spectrum-tracking-evaluation-tests', `${quote(python)} -B -W error::RuntimeWarning -m unittest discover -s ${quote(path.join(workspaceRoot, 'skills/underwater-line-spectrum-tracking-evaluation/tests'))} -v`],
    ['line-spectrum-tracking-integration-tests', `${quote(python)} -B -W error::RuntimeWarning ${quote(path.join(workspaceRoot, 'backend/dev/contract-line-spectrum-tracking.py'))} -v`],
  ]) {
    await t.test(name, async () => {
      const result = await ctx.shell.run(ctx.shell.resolve({ command, env }))
      fs.writeFileSync(path.join(dir, name + '.log'), result.stdout.text + '\n' + result.stderr.text)
      assert.equal(result.exitCode, 0, result.stderr.text)
      assert.equal(result.timedOut, false)
      assert.equal(result.aborted, false)
      assert.equal(result.sandbox.enforcement, 'full')
      assert.equal(result.sandbox.mode, 'workspace-write')
      assert.match(result.stderr.text, /\nOK(?: \(skipped=\d+\))?\s*$/)
      const count = /Ran (\d+) tests?/.exec(result.stderr.text)
      assert.ok(count, '没有真实 unittest 运行统计')
      const skippedCount = Number(/OK \(skipped=(\d+)\)/.exec(result.stderr.text)?.[1] || 0)
      if (skippedCount) {
        assert.equal(name, 'beamforming-provided-tests', '本项目集成用例不得跳过')
        assert.equal(skippedCount, 1)
        assert.match(result.stderr.text, /v0\.4\.3 integration suite requires sibling inspection and handoff skills/)
      }
      summary.suites.push({ name, passed: true, testCount: Number(count[1]), skippedCount,
        passedCount: Number(count[1]) - skippedCount, enforcement: result.sandbox.enforcement })
      fs.writeFileSync(path.join(dir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
    })
  }
  console.log('真实沙箱测试证据：' + path.join(dir, 'summary.json'))
})
