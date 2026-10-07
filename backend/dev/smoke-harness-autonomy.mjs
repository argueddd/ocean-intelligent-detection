/** Real-model regression for autonomous defaults and consolidated blocking questions. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { backendDir, workspaceRoot, pythonEnvironment, createProjectHarness } from '../harness/runtime.mjs'
import { runHarnessTask } from '../harness/task.mjs'

process.loadEnvFile(path.join(backendDir, '.env'))
assert.ok(process.env.LLM_API_KEY, '真实模型测试需要 LLM_API_KEY')

const root = path.join(workspaceRoot, '.run', 'harness-autonomy', randomUUID())
const fixtureDir = path.join(root, 'fixtures')
fs.mkdirSync(fixtureDir, { recursive: true })
const wav = path.join(fixtureDir, 'unambiguous.wav')
const { python, env } = pythonEnvironment()
execFileSync(python, ['-B', '-c', String.raw`
from pathlib import Path
import sys, wave
import numpy as np
root=Path(sys.argv[1]); fs=8000; n=fs; t=np.arange(n)/fs
x=np.column_stack((0.3*np.sin(2*np.pi*440*t), 0.2*np.sin(2*np.pi*660*t)))
pcm=np.clip(x*32767,-32768,32767).astype('<i2')
with wave.open(str(root/'unambiguous.wav'),'wb') as f:
    f.setnchannels(2); f.setsampwidth(2); f.setframerate(fs); f.writeframes(pcm.tobytes())
`, fixtureDir], { cwd: workspaceRoot, env, timeout: 30000 })

const argsOf = event => typeof event.data?.arguments === 'string'
  ? JSON.parse(event.data.arguments) : event.data?.arguments || {}
const skillLoaded = (events, name) => events.some(event =>
  event.type === 'tool/call' && event.data?.name === 'skill'
  && JSON.stringify(event.data.arguments).includes(name))
  || events.some(event => event.type === 'user/message'
    && event.data?.source?.kind === 'skill-invocation' && event.data.source.name === name)
const chineseOpening = text => /^[#\s>*-]*[\p{Script=Han}]/u.test(text)

const summary = { status: 'running', scenarios: [] }
const save = () => fs.writeFileSync(path.join(root, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
save()

const scenarios = [
  {
    name: 'unambiguous-inspection-runs-without-parameter-questions',
    prompt: `体检 ${wav}，直接给我结果。`,
    check(result) {
      assert.ok(skillLoaded(result.events, 'underwater-data-inspection'), '未加载数据体检 Skill')
      assert.ok(result.events.some(event => event.type === 'tool/call' && event.data?.name === 'bash'), '没有实际执行体检')
      assert.ok(!result.finalResponse.includes('需要你确认'), '完整 WAV 仍向用户索要非关键确认')
      assert.match(result.finalResponse, /8000\s*Hz/i, '没有使用 WAV 文件头采样率')
      assert.ok(chineseOpening(result.finalResponse), '最终回答没有从中文开始')
      return { askedForConfirmation: false }
    },
  },
  {
    name: 'physical-blockers-are-asked-once',
    prompt: '我要对一个 shape=[8000,2] 的二维 NPY 做 MVDR，并保留用于后续线谱分析的波束。现在已知没有采样率、阵列身份/几何和方向坐标说明；请先做参数规划，不读取文件、不执行计算。能自主决定的设置直接决定，只把真正阻断的物理事实一次问完。',
    check(result) {
      assert.ok(skillLoaded(result.events, 'underwater-beamforming'), '未加载波束形成 Skill')
      const headings = result.finalResponse.match(/需要你确认/g) || []
      assert.equal(headings.length, 1, '阻断项没有统一放进一个确认清单')
      assert.match(result.finalResponse, /采样率/, '合并清单没有采样率阻断项')
      assert.match(result.finalResponse, /几何|阵元坐标|阵元间距/, '合并清单没有阵列几何阻断项')
      assert.match(result.finalResponse, /按推荐执行/, '没有提供一次接受推荐的回复方式')
      assert.ok(chineseOpening(result.finalResponse), '最终回答没有从中文开始')
      assert.ok(!/两(?:个|阵元|通道).*MVDR[\s\S]{0,80}(?:不成立|无法执行|无实际.*增益)/.test(result.finalResponse),
        '仅凭两通道就武断否定 MVDR')
      const questions = result.finalResponse.match(/^\s*\d+[.)、]\s+/gm) || []
      assert.ok(questions.length <= 3, `仍拆出了过多确认项：${questions.length}`)
      assert.ok(!/请.*(?:接受|确认).*1500\s*m\/s/i.test(result.finalResponse), '仍要求用户批准名义声速基线')
      assert.ok(!/\]\([^)]*(?:plan|notes)[^)]*\.md[^)]*\)/i.test(result.finalResponse), '纯规划任务额外创建了计划文件')
      const commands = result.events.filter(event => event.type === 'tool/call' && event.data?.name === 'bash')
        .map(event => argsOf(event).command || '')
      assert.ok(!commands.some(command => /underwater-beamforming\/scripts\/execute\.py\s+run/.test(command)),
        '物理事实缺失时仍执行了 MVDR')
      return { consolidatedQuestionCount: headings.length, numericalBeamformingStarted: false }
    },
  },
]

let harness
try {
  for (const scenario of scenarios) {
    const dir = path.join(root, scenario.name)
    fs.mkdirSync(dir)
    harness = createProjectHarness({ home: path.join(dir, 'runtime') })
    const started = Date.now()
    const record = { name: scenario.name, status: 'running' }
    summary.scenarios.push(record)
    save()
    let result
    try {
      result = await runHarnessTask(harness, scenario.prompt, { timeoutMs: 180000 })
      fs.writeFileSync(path.join(dir, 'response.md'), result.finalResponse + '\n')
      fs.writeFileSync(path.join(dir, 'events.json'), JSON.stringify(result.events, null, 2) + '\n')
      Object.assign(record, { status: 'passed', elapsedMs: Date.now() - started, ...scenario.check(result) })
    } catch (error) {
      Object.assign(record, { status: 'failed', elapsedMs: Date.now() - started, error: error.message })
    } finally {
      await harness.close()
      harness = null
      save()
    }
  }
  summary.status = summary.scenarios.every(item => item.status === 'passed') ? 'passed' : 'failed'
  save()
  console.log(`Harness autonomy smoke ${summary.status}: ${root}`)
  if (summary.status !== 'passed') process.exitCode = 1
} finally {
  if (harness) await harness.close()
}
