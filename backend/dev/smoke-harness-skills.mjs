/** 真实模型集成：临时复制标准 Skill 包进项目目录，验证行为与原始产物。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { randomUUID, createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { backendDir, workspaceRoot, pythonEnvironment, createProjectHarness } from '../harness/runtime.mjs'
import { listProjectSkills } from '../harness/skills.mjs'
import { runHarnessTask } from '../harness/task.mjs'

process.loadEnvFile(path.join(backendDir, '.env'))
assert.ok(process.env.LLM_API_KEY, '真实模型验证需要 LLM_API_KEY')
const args = process.argv.slice(2)
const resume = args.includes('--resume')
const id = resume ? args[args.indexOf('--resume') + 1] : randomUUID()
const only = args.includes('--only') ? args[args.indexOf('--only') + 1] : null
assert.match(id || '', /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/, '恢复参数必须是本脚本的运行编号')
const dir = path.join(workspaceRoot, '.run', 'harness-skills-smoke', id)
const inputs = path.join(dir, '中文 数据输入')
fs.mkdirSync(inputs, { recursive: true })
const names = ['harness-probe-data-health', 'harness-probe-spectrum']
const installed = []
let harness
const summary = { id, status: 'running', scenarios: [] }
const sha = (file) => createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const saveSummary = () => fs.writeFileSync(path.join(dir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
saveSummary()
try {
  for (const name of names) {
    const destination = path.join(workspaceRoot, 'skills', name)
    assert.ok(!fs.existsSync(destination), '测试目录已存在，拒绝覆盖：' + destination)
    fs.cpSync(path.join(backendDir, 'dev/fixtures/harness-skills', name), destination, { recursive: true })
    installed.push(destination)
  }
  execFileSync(path.join(workspaceRoot, 'setup-python.sh'), ['--ensure'], { cwd: workspaceRoot, stdio: 'inherit' })
  const { python, env } = pythonEnvironment()
  execFileSync(python, ['-c', `import numpy as np
from pathlib import Path
p = Path(__import__('sys').argv[1])
t = np.arange(256)
health = np.column_stack([np.sin(t), np.zeros(256), np.cos(t)])
health[3,0] = np.nan
health[9,0] = np.inf
np.savetxt(p/'异常 多通道.csv', health, delimiter=',')
t = np.arange(8192)/1024
rng = np.random.default_rng(0)
x = np.sin(2*np.pi*83*t)+0.7*np.sin(2*np.pi*317*t)+rng.normal(0,0.5,t.size)
np.savetxt(p/'真实 波形.csv', x, delimiter=',')
(p/'元数据.yml').write_text('sample_rate_hz: 2048\\n')
`, inputs], { cwd: workspaceRoot, env })
  const catalog = await listProjectSkills(workspaceRoot)
  for (const name of names) assert.ok(catalog.some((skill) => skill.name === name), 'Skill 未自动发现：' + name)
  fs.writeFileSync(path.join(dir, 'catalog.json'), JSON.stringify(catalog, null, 2) + '\n')
  const healthScript = path.join(installed[0], 'scripts/check.py')
  const spectrumScript = path.join(installed[1], 'scripts/analyze.py')
  const scriptHashes = [sha(healthScript), sha(spectrumScript)]
  harness = createProjectHarness({ home: path.join(dir, 'runtime') })
  const healthInput = path.join(inputs, '异常 多通道.csv')
  const waveInput = path.join(inputs, '真实 波形.csv')
  const cases = [
    {
      name: 'implicit-health-yaml-dependency', skill: names[0], script: healthScript, source: healthInput,
      task: `对文件 ${healthInput} 做数据体检。元数据在 ${path.join(inputs, '元数据.yml')}。报告非有限值、恒定通道与采样率。`,
      check(report) { assert.deepEqual(report.shape, [256, 3]); assert.equal(report.non_finite_count, 2); assert.deepEqual(report.constant_channels, [1]); assert.equal(report.sample_rate_hz, 2048) },
    },
    {
      name: 'missing-sample-rate', skill: names[0], script: healthScript, source: healthInput,
      task: `只有 ${healthInput} 这个数据，采样率和元数据未知。先做当前条件允许的数据检查，不猜采样率，不推测谱峰频率。当前不要追问，先落盘已知特征与缺失条件。`,
      check(report) { assert.equal(report.sample_rate_hz, null); assert.deepEqual(report.missing_parameters, ['sample_rate_hz']) },
    },
    {
      name: 'explicit-spectrum-derived-welch', skill: names[1], script: spectrumScript, source: waveInput,
      task: `$${names[1]} 分析 ${waveInput}，采样率1024Hz，噪声背景下需要多段平均，目标分辨率1Hz。选择适合的方法，用真实样本数推导分段参数，给出最高两个谱峰。`,
      check(report) { assert.equal(report.method, 'welch'); assert.equal(report.sample_count, 8192); assert.equal(report.derived_parameters.nperseg, 1024); assert.equal(report.derived_parameters.noverlap, 512); assert.equal(report.derived_parameters.segment_count, 15); assert.equal(report.derived_parameters.frequency_resolution_hz, 1); assert.deepEqual(report.peak_frequencies_hz, [83, 317]) },
    },
    {
      name: 'bad-input-path-recovery', skill: names[1], script: spectrumScript, source: waveInput,
      task: `执行路径恢复测试：先用已有频谱 Skill 的资源脚本尝试输入 ${path.join(inputs, '不存在.csv')}，采样率1024Hz，periodogram。必须先真实尝试这条路径；若文件不存在，查看同目录实际的单通道波形文件，修正路径重试。不要生成替代输入。`,
      check(report, events) {
        assert.equal(report.method, 'periodogram'); assert.deepEqual(report.peak_frequencies_hz, [83, 317])
        const diagnostic = events.filter((event) => event.type === 'tool/result').map((event) => JSON.stringify(event.data)).join('\n')
        assert.ok(/FileNotFoundError|not found|No such file|不存在.*not|could not open/i.test(diagnostic), '没有真实失败诊断，不能证明重试恢复')
      },
    },
  ]
  if (only) assert.ok(cases.some((scenario) => scenario.name === only), '未知场景：' + only)
  for (const scenario of cases) {
    if (only && scenario.name !== only) continue
    console.log('[scenario] ' + scenario.name)
    const output = path.join(dir, scenario.name + '.json')
    const eventFile = path.join(dir, scenario.name + '.events.json')
    const responseFile = path.join(dir, scenario.name + '.response.txt')
    const reuse = resume && fs.existsSync(output) && fs.existsSync(eventFile) && fs.existsSync(responseFile)
    const result = reuse ? { events: JSON.parse(fs.readFileSync(eventFile, 'utf8')), finalResponse: fs.readFileSync(responseFile, 'utf8'), sessionId: null } : await runHarnessTask(harness, `${scenario.task}\n输出 JSON 到 ${output}。优先使用匹配的已存在 Skill 与其资源脚本，保留脚本生成的原始字段；不要改脚本，不安装依赖，不访问外部服务，不创建子智能体。最后简洁说明实际观察、选择依据、推导参数与调整条件。`, { timeoutMs: 180000, onNotification(notification) {
      if (notification.params?.event?.type === 'tool/call') console.log('[tool] ' + notification.params.event.data.name)
    } })
    if (!reuse) {
      fs.writeFileSync(eventFile, JSON.stringify(result.events, null, 2) + '\n')
      fs.writeFileSync(responseFile, result.finalResponse + '\n')
    }
    const report = JSON.parse(fs.readFileSync(output, 'utf8'))
    assert.equal(report.skill, scenario.skill)
    assert.equal(report.python_executable, python)
    assert.equal(report.input_sha256, sha(scenario.source))
    assert.ok(result.events.some((event) => event.type === 'tool/call' && event.data.name === 'bash' && [scenario.script, path.relative(workspaceRoot, scenario.script)].some((script) => event.data.arguments.includes(script))), '未真实调用 Skill 资源脚本')
    const loaded = result.events.some((event) => event.type === 'tool/call' && event.data.name === 'skill' && event.data.arguments.includes(scenario.skill))
      || result.events.some((event) => event.type === 'user/message' && event.data?.source?.kind === 'skill-invocation' && event.data.source.name === scenario.skill)
    assert.ok(loaded, 'Skill 未通过 SDK 加载')
    scenario.check(report, result.events)
    assert.equal(sha(healthScript), scriptHashes[0]); assert.equal(sha(spectrumScript), scriptHashes[1])
    summary.scenarios.push({ name: scenario.name, passed: true, reusedRecordedRun: reuse, sessionId: result.sessionId, output })
    saveSummary()
  }
  summary.status = 'passed'
  console.log(`All ${summary.scenarios.length} real-model Skill scenarios passed: ` + path.join(dir, 'summary.json'))
} catch (error) {
  summary.status = 'failed'; summary.error = error.message
  throw error
} finally {
  try { if (harness) await harness.close() }
  finally { for (const folder of installed) fs.rmSync(folder, { recursive: true, force: true }); saveSummary() }
}
