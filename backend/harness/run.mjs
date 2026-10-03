import fs from 'node:fs'
import path from 'node:path'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { randomUUID } from 'node:crypto'
import { Context } from '@deepseek-ai/cordis'
import { LocalSandboxProvider } from '@deepseek-ai/dsh-sandbox-local'
import { backendDir, workspaceRoot, pythonEnvironment, createProjectHarness } from './runtime.mjs'
import { listProjectSkills } from './skills.mjs'
import { runHarnessTask } from './task.mjs'

try { process.loadEnvFile(path.join(backendDir, '.env')) } catch (e) { if (e.code !== 'ENOENT') throw e }
const execFileAsync = promisify(execFile)

async function checkRuntime() {
  const { python, env } = pythonEnvironment()
  const ctx = new Context()
  const sandbox = new LocalSandboxProvider(ctx, { runnerCommand: [], runnerFailureSignatures: [], probeTimeoutMs: 5000 })
  const outside = fs.mkdtempSync(path.join(path.dirname(workspaceRoot), '.harness-probe-'))
  try {
    const confined = await sandbox.confine([python, '-c', `
import sys, json, os
from pathlib import Path
import numpy, scipy, matplotlib
assert Path(sys.prefix) == Path(os.environ['VIRTUAL_ENV'])
assert Path(sys.executable) == Path(os.environ['HARNESS_PYTHON'])
marker = Path('.run/harness-runtime/write-probe.txt')
marker.write_text('workspace write works')
marker.unlink()
try:
    Path(sys.argv[1]).write_text('must be denied')
    blocked = False
except PermissionError:
    blocked = True
assert blocked, 'sandbox allowed an outside-workspace write'
print(json.dumps({'python': sys.executable, 'numpy': numpy.__version__, 'scipy': scipy.__version__, 'matplotlib': matplotlib.__version__, 'workspace_write': True, 'outside_write_blocked': blocked}))
`, path.join(outside, 'denied.txt')], { mode: 'workspace-write', workspaceRoot })
    const result = await execFileAsync(confined.argv[0], confined.argv.slice(1), { cwd: workspaceRoot, env, timeout: 30000, maxBuffer: 1024 * 1024 })
    console.log(JSON.stringify({ ...JSON.parse(result.stdout), runner: confined.argv[0], enforcement: confined.enforcement, profile: 'harness' }, null, 2))
  } finally { fs.rmSync(outside, { recursive: true, force: true }) }
}

const args = process.argv.slice(2)
if (args[0] === '--skills') {
  console.log(JSON.stringify(await listProjectSkills(workspaceRoot), null, 2))
} else if (args[0] === '--check') {
  await checkRuntime()
} else if (args.length && !['--help', '-h'].includes(args[0])) {
  const smoke = args[0] === '--smoke'
  const outputDir = smoke ? path.join('.run/harness-smoke', randomUUID()) : null
  const prompt = smoke
    ? `做一次真实 Python 执行验证。使用项目虚拟环境的解释器，编写并执行脚本：用 numpy 生成采样率8000Hz、时长2秒、频率200Hz与510Hz的双正弦，固定随机种子0；用 scipy.signal.periodogram 计算功率谱并找出最高的两个峰；用 matplotlib 保存频谱图到 ${outputDir}/spectrum.png；保存 ${outputDir}/result.json，字段必须为 python_executable（sys.executable）、python_prefix（sys.prefix）、sample_rate_hz、sample_count、peak_frequencies_hz（两个峰频率数组）、versions（numpy/scipy/matplotlib版本）。必须实际调用工具执行，不能只描述方案，不安装依赖，不访问网络，不调用子智能体。最后只报告结果文件路径、解释器路径和两个峰频率。`
    : args.join(' ')
  const harness = createProjectHarness()
  const close = () => { harness.close().catch(() => {}) }
  process.once('SIGINT', close)
  process.once('SIGTERM', close)
  try {
    const result = await runHarnessTask(harness, prompt, { ...(smoke ? { timeoutMs: 240000 } : {}), onNotification(notification) {
      const event = notification.params?.event
      if (event?.type === 'tool/call') console.error('[tool] ' + event.data.name)
      if (event?.type === 'tool/result' && event.data?.message?.content?.some((block) => block.type === 'tool-result' && block.isError)) console.error('[tool] execution error')
    } })
    console.log(result.finalResponse)
    if (smoke) {
      const artifactDir = path.join(workspaceRoot, outputDir)
      const report = JSON.parse(fs.readFileSync(path.join(artifactDir, 'result.json'), 'utf8'))
      const peaks = report.peak_frequencies_hz
      if (report.python_executable !== pythonEnvironment().python || report.sample_rate_hz !== 8000 || report.sample_count !== 16000 || !Array.isArray(peaks) || peaks.length !== 2 || ![200, 510].every((expected) => peaks.some((actual) => typeof actual === 'number' && Math.abs(actual - expected) <= 0.5))) {
        throw new Error('执行产物未通过解释器/峰值校验：' + JSON.stringify(report))
      }
      const png = fs.readFileSync(path.join(artifactDir, 'spectrum.png'))
      if (!png.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) throw new Error('频谱图不是有效 PNG 文件')
      fs.writeFileSync(path.join(artifactDir, 'events.json'), JSON.stringify(result.events, null, 2) + '\n')
      console.log('Harness → sandbox → project .venv → numerical output: verified')
    }
  } finally {
    process.removeListener('SIGINT', close)
    process.removeListener('SIGTERM', close)
    await harness.close()
  }
} else {
  console.log('用法：./harness.sh --skills | --check | --smoke | "任务指令"\n启动任务时自动准备项目 .venv 与 Skill 依赖；主动重检：./setup-python.sh')
}
