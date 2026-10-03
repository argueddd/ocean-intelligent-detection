/** Real SSE checks for task scope and fewer model/tool round trips. Never reuse a user's session. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { performance } from 'node:perf_hooks'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const base = process.env.HARNESS_TEST_API || 'http://127.0.0.1:3089'
const source = process.env.HARNESS_SIO_TEST_FILE || '/Volumes/T7 Shield/SWellEx_96/Data/J1341145.vla.21els.sio'
const sourceBefore = fs.statSync(source)
const output = path.join(root, '.run/harness-efficiency', randomUUID())
fs.mkdirSync(output, { recursive: true })
const only = process.argv[2]
const summary = { status: 'running', source, output, scenarios: [] }
const save = () => fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
const cases = [
  { name: 'full-file-check', maxTools: 3, mode: 'check', samples: 5850000, channels: Array.from({ length: 21 }, (_, i) => i),
    prompt: `请用已有 Skill 检查 ${source}。对完整文件、全部21路做数值体检，采样率已确认1500 Hz，原始单位未知。这轮只做数据检查，简要给出结果。` },
  { name: 'bounded-analysis', maxTools: 3, mode: 'analyze', samples: 90000, channels: [0, 10, 20],
    prompt: `请用已有 Skill 分析 ${source}。采样率已确认1500 Hz，原始单位未知。此次范围为前60秒、通道0/10/20，频率网格0.5 Hz、50%重叠。给简要结果。` },
  { name: 'directory-discovery', maxTools: 4,
    prompt: '我的数据在/t7-shield/SWellEx_96 里 你看下，然后给我做个数据检查。目录内有多份记录，先确认候选与结构，在我指定记录之前不要默选某份做数值体检。' },
]
if (only) assert.ok(only === 'numeric' || cases.some(item => item.name === only), 'unknown scenario')

function argsOf(event) {
  try { return JSON.parse(event.data.arguments || '{}') } catch { return {} }
}
function textOfResult(event) {
  return (event.data?.message?.content || []).filter(block => block.type === 'tool-result')
    .flatMap(block => block.content || []).filter(block => block.type === 'text').map(block => block.text).join('\n')
}
async function run(scenario) {
  const directory = path.join(output, scenario.name)
  const resultDirectory = path.join(directory, 'result')
  fs.mkdirSync(directory)
  const prompt = scenario.mode ? scenario.prompt + `\n新结果保存到：${resultDirectory}` : scenario.prompt
  fs.writeFileSync(path.join(directory, 'prompt.txt'), prompt + '\n')
  const started = performance.now()
  const record = { name: scenario.name, status: 'running' }
  const events = []
  let responseText = ''
  try {
    console.log('Starting ' + scenario.name)
    const response = await fetch(base + '/api/chat/stream', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ sessionId: 'session-efficiency-' + randomUUID().replaceAll('-', ''), message: prompt }),
      signal: AbortSignal.timeout(180000),
    })
    assert.equal(response.status, 200)
    const sse = await response.text()
    fs.writeFileSync(path.join(directory, 'raw.sse'), sse)
    const frames = sse.split(/\r?\n\r?\n/).flatMap(frame => {
      const kind = /^event:\s*(.+)$/m.exec(frame)?.[1]
      const raw = frame.split(/\r?\n/).filter(line => line.startsWith('data: ')).map(line => line.slice(6)).join('\n')
      return kind && raw ? [{ kind, data: JSON.parse(raw) }] : []
    })
    events.push(...frames.filter(frame => frame.kind === 'notification').map(frame => frame.data.params?.event).filter(Boolean))
    const done = frames.find(frame => frame.kind === 'done')
    assert.ok(done, frames.find(frame => frame.kind === 'error')?.data?.message || 'missing done event')
    responseText = done.data.finalResponse || ''
    assert.ok(responseText.trim())
    const calls = events.filter(event => event.type === 'tool/call')
    const bash = calls.filter(event => event.data.name === 'bash')
    const modelSteps = events.filter(event => event.type === 'step/start').length
    Object.assign(record, { elapsedMs: Math.round(performance.now() - started), toolCount: calls.length, modelSteps,
      descriptions: bash.map(event => argsOf(event).description) })
    assert.ok(calls.length <= scenario.maxTools, 'too many tool round trips: ' + calls.length)
    assert.ok(!calls.some(event => event.data.name === 'vision_inspect'), 'unrequested visual review')
    assert.ok(!events.filter(event => event.type === 'assistant/message').flatMap(event => event.data.message.content || []).some(block => block.type === 'reasoning'), 'unexpected reasoning blocks')
    for (const event of bash) {
      const args = argsOf(event)
      assert.match(args.description || '', /[\u4e00-\u9fff]{2}/, 'step purpose is not in Chinese')
      assert.ok(!/^\s*cd\s/.test(args.command || ''), 'redundant cwd setup in command')
      assert.ok(!/inspect_data\.py["']?\s+probe\b/.test(args.command || ''), 'separate probe before integrated execution')
    }
    if (scenario.mode) {
      assert.ok(bash.some(event => /inspect_data\.py["']?\s+execute\b/.test(argsOf(event).command || '')), 'did not use the integrated Skill entry')
      const result = JSON.parse(fs.readFileSync(path.join(resultDirectory, 'result.json'), 'utf8'))
      assert.equal(result.source.path, source)
      assert.equal(result.config.values.mode, scenario.mode)
      assert.deepEqual(result.quality.coverage.sample_range, [0, scenario.samples])
      assert.deepEqual(result.quality.coverage.channel_indices, scenario.channels)
      assert.equal(result.quality.coverage.complete_requested_range, true)
      assert.equal(result.quality.channels.length, scenario.channels.length)
      if (scenario.mode === 'check') {
        assert.ok(!result.analysis, 'unrequested spectral analysis')
      } else {
        assert.equal(result.analysis.settings.nperseg, 3000)
        assert.equal(result.analysis.settings.noverlap, 1500)
        assert.deepEqual(result.analysis.coverage.sample_range, [0, 90000])
        const peaks = result.analysis.channels.map(channel => channel.strongest_bin_hz)
        assert.deepEqual(peaks, [49, 112, 163.5])
        for (const peak of peaks) assert.ok(responseText.includes(String(peak)), 'missing useful computed result')
      }
      record.result = path.join(resultDirectory, 'result.json')
    } else {
      const results = events.filter(event => event.type === 'tool/result').map(textOfResult)
      assert.ok(results.some(text => text.includes('needs_input') && text.includes('candidates')), 'did not return explicit directory candidates')
      assert.ok(!/已(?:完成|通过).{0,12}(?:全部|全量|数值)体检/.test(responseText), 'claimed unperformed full-directory numeric checks')
    }
    const after = fs.statSync(source)
    for (const key of ['size', 'mtimeMs', 'ctimeMs']) assert.equal(after[key], sourceBefore[key], 'source changed: ' + key)
    record.status = 'passed'
  } catch (error) {
    record.status = 'failed'
    record.error = error.message
    record.elapsedMs ??= Math.round(performance.now() - started)
  } finally {
    fs.writeFileSync(path.join(directory, 'events.json'), JSON.stringify(events, null, 2) + '\n')
    fs.writeFileSync(path.join(directory, 'response.md'), responseText + '\n')
    fs.writeFileSync(path.join(directory, 'summary.json'), JSON.stringify(record, null, 2) + '\n')
  }
  console.log(JSON.stringify(record))
  return record
}

try {
  const health = await fetch(base + '/api/health').then(response => response.json())
  assert.equal(health.profile, 'harness')
  for (const scenario of cases) {
    if (only === 'numeric' ? !scenario.mode : only && scenario.name !== only) continue
    summary.scenarios.push(await run(scenario))
    save()
  }
  summary.status = summary.scenarios.every(item => item.status === 'passed') ? 'passed' : 'failed'
} finally { save(); console.log('Evidence: ' + path.join(output, 'summary.json')) }
if (summary.status !== 'passed') process.exitCode = 1
