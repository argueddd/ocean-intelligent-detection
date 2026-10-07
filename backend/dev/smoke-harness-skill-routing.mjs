/** Real-model routing matrix for the installed underwater Skills. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { backendDir, workspaceRoot, createProjectHarness } from '../harness/runtime.mjs'
import { runHarnessTask } from '../harness/task.mjs'

process.loadEnvFile(path.join(backendDir, '.env'))
assert.ok(process.env.LLM_API_KEY, '真实模型测试需要 LLM_API_KEY')

const skillNames = [
  'underwater-data-inspection',
  'underwater-beamforming',
  'underwater-beamforming-evaluation',
  'underwater-line-spectrum-detection',
  'underwater-line-spectrum-evaluation',
  'underwater-line-spectrum-tracking',
  'underwater-line-spectrum-tracking-evaluation',
]
const root = path.join(workspaceRoot, '.run', 'harness-skill-routing', randomUUID())
fs.mkdirSync(root, { recursive: true })
const summary = { status: 'running', scenarios: [] }
const save = () => fs.writeFileSync(path.join(root, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
const skillCalls = events => {
  const selected = new Set()
  for (const event of events) {
    if (event.type !== 'tool/call' || event.data?.name !== 'skill') continue
    let args = event.data.arguments || {}
    if (typeof args === 'string') {
      try { args = JSON.parse(args) } catch { continue }
    }
    if (skillNames.includes(args.name)) selected.add(args.name)
  }
  return [...selected].sort()
}

const scenarios = [
  {
    name: 'raw-waveform-inspection', expected: ['underwater-data-inspection'],
    prompt: '我有一份原始 WAV，想检查字段与轴、NaN、恒值段、通道质量和基础 PSD。请判断并加载适用的现有 Skill，然后只说明选择结果，不读取文件、不执行。',
  },
  {
    name: 'create-beams', expected: ['underwater-beamforming'],
    prompt: '我要从原始阵元时域数据形成 CBF 和 MVDR 波束并保存所选波束。请判断并加载适用的现有 Skill，然后只说明选择结果，不读取文件、不执行。',
  },
  {
    name: 'supplement-beam-products', expected: ['underwater-beamforming'],
    prompt: '已有本项目生成的波束结果，缺少 PSD 和 BTR，我要补生成这些产物，不做质量评分。请判断并加载适用的现有 Skill，然后只说明选择结果，不读取文件、不执行。',
  },
  {
    name: 'evaluate-existing-beams', expected: ['underwater-beamforming-evaluation'],
    prompt: '已有完整 CBF/MVDR 波束结果，我要评价空间谱主瓣旁瓣、BTR 稳定性并比较算法表现，不重新形成波束。请判断并加载适用的现有 Skill，然后只说明选择结果，不读取文件、不执行。',
  },
  {
    name: 'evaluate-detection-package', expected: ['underwater-line-spectrum-evaluation'],
    prompt: '已有完整 DetectionResult、candidates 和包含零候选帧的 ledger，我要评价候选统计和真值覆盖内的频率误差，不重新检测。请判断并加载适用的现有 Skill，然后只说明选择结果，不读取文件、不执行。',
  },
  {
    name: 'create-tracks', expected: ['underwater-line-spectrum-tracking'],
    prompt: '已有完整 DetectionTrackingHandoff，我要把逐窗候选跨时间关联成新的频率轨迹。请判断并加载适用的现有 Skill，然后只说明选择结果，不读取文件、不执行。',
  },
  {
    name: 'evaluate-tracks', expected: ['underwater-line-spectrum-tracking-evaluation'],
    prompt: '已有完整 TrackingResultPackage，我要评价轨迹连续性、短轨比例、频率误差和碎片化，不重新关联候选。请判断并加载适用的现有 Skill，然后只说明选择结果，不读取文件、不执行。',
  },
  {
    name: 'create-line-detections', expected: ['underwater-line-spectrum-detection'],
    prompt: '我有一份完整的波束时域交接包，要执行 CA/OS-CFAR 线谱检测并生成候选、门限和逐帧 ledger，不做效果评价或跨窗跟踪。请判断并加载适用的现有 Skill，然后只说明选择结果，不读取文件、不执行。',
  },
  {
    name: 'term-explanation-needs-no-skill', expected: [],
    prompt: 'dtype 是什么意思？只解释这个术语。',
  },
]
const scenarioFilter = process.argv[2]
const selectedScenarios = scenarioFilter
  ? scenarios.filter(scenario => scenario.name === scenarioFilter)
  : scenarios
assert.ok(selectedScenarios.length, `未知路由场景：${scenarioFilter}`)

save()
let harness
try {
  for (const scenario of selectedScenarios) {
    const dir = path.join(root, scenario.name)
    fs.mkdirSync(dir)
    harness = createProjectHarness({ home: path.join(dir, 'runtime') })
    const record = { name: scenario.name, expected: scenario.expected, status: 'running' }
    summary.scenarios.push(record)
    save()
    const started = Date.now()
    let result
    try {
      result = await runHarnessTask(harness, scenario.prompt, { timeoutMs: 90000 })
      const selected = skillCalls(result.events)
      fs.writeFileSync(path.join(dir, 'response.md'), result.finalResponse + '\n')
      fs.writeFileSync(path.join(dir, 'events.json'), JSON.stringify(result.events, null, 2) + '\n')
      assert.deepEqual(selected, [...scenario.expected].sort(), `路由不符：${selected.join(', ') || 'none'}`)
      scenario.check?.(result.finalResponse)
      Object.assign(record, { status: 'passed', selected, elapsedMs: Date.now() - started })
      console.log(`[passed] ${scenario.name}: ${selected.join(', ') || 'none'}`)
    } catch (error) {
      Object.assign(record, { status: 'failed', elapsedMs: Date.now() - started, error: error.message,
        selected: result ? skillCalls(result.events) : [] })
      console.error(`[failed] ${scenario.name}: ${error.message}`)
    } finally {
      await harness.close()
      harness = null
      save()
    }
  }
  summary.status = summary.scenarios.every(item => item.status === 'passed') ? 'passed' : 'failed'
  save()
  console.log(`Harness skill routing smoke ${summary.status}: ${root}`)
  if (summary.status !== 'passed') process.exitCode = 1
} finally {
  if (harness) await harness.close()
}
