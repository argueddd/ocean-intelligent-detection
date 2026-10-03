/** 在正式 Skill 的已有分析产物上验证模型读图与数值交叉核对。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { randomUUID, createHash } from 'node:crypto'
import { backendDir, workspaceRoot, createProjectHarness } from '../harness/runtime.mjs'
import { runHarnessTask } from '../harness/task.mjs'

process.loadEnvFile(path.join(backendDir, '.env'))
const sourceDir = path.resolve(process.argv[2] || '')
assert.ok(process.argv[2] && fs.existsSync(path.join(sourceDir, 'result.json')), '参数须为正式 Skill 的已有 analyze 产物目录')
const source = JSON.parse(fs.readFileSync(path.join(sourceDir, 'result.json'), 'utf8'))
assert.ok(source.analysis && fs.existsSync(path.join(sourceDir, 'psd.png')))
const dir = path.join(workspaceRoot, '.run', 'inspection-vision-review', randomUUID())
fs.mkdirSync(dir, { recursive: true })
const output = path.join(dir, 'review.json')
const hashes = Object.fromEntries(fs.readdirSync(sourceDir).filter(file => fs.statSync(path.join(sourceDir, file)).isFile()).map(file => [file, createHash('sha256').update(fs.readFileSync(path.join(sourceDir, file))).digest('hex')]))
const harness = createProjectHarness({ home: path.join(dir, 'runtime') })
const events = []
const summary = { status: 'running', sourceDir, output }
try {
  const result = await runHarnessTask(harness, `$underwater-data-inspection 对已有水声体检产物 ${sourceDir} 做交付复核。这次只读已有result.json、必要的feature_status.csv以及psd.png、spectrogram_ch0.png，不读取原始波形、不重跑probe/run、不改既有产物、不创建子智能体。用已配置的独立视觉工具真实核对这两张图，问题保持简短：坐标/曲线、主要峰或音轨近似位置、是否标定；再与JSON的精确数值和实际覆盖交叉核对。把JSON保存到 ${output}，字段为 numeric_peaks_hz（按成功通道顺序）、frequency_grid_spacing_hz、spectrum_sample_range、visual_results（全部视觉工具原始JSON的列表，逐字段保留，不合并或改写）。依据实际完成度解释，不把图像估计冒充精确数值，不把partial当验收通过。最终回复300字以内。`, {
    timeoutMs: 300000,
    onNotification(notification) {
      const event = notification.params?.event
      if (event) { events.push(event); fs.appendFileSync(path.join(dir, 'events.jsonl'), JSON.stringify(event) + '\n') }
      if (event?.type === 'tool/call') console.log('[tool] ' + event.data.name)
    },
  })
  fs.writeFileSync(path.join(dir, 'events.json'), JSON.stringify(result.events, null, 2) + '\n')
  fs.writeFileSync(path.join(dir, 'response.txt'), result.finalResponse + '\n')
  const review = JSON.parse(fs.readFileSync(output, 'utf8'))
  assert.deepEqual(review.numeric_peaks_hz, source.analysis.channels.filter(row => row.status === 'completed').map(row => row.strongest_bin_hz))
  assert.equal(review.frequency_grid_spacing_hz, source.analysis.settings.frequency_grid_spacing_hz)
  assert.deepEqual(review.spectrum_sample_range, source.analysis.coverage.spectrum_sample_range)
  const originals = result.events.filter(event => event.type === 'tool/result').flatMap(event => event.data.message.content).filter(block => block.type === 'tool-result' && !block.isError).flatMap(block => block.content).filter(block => block.type === 'text').map(block => { try { return JSON.parse(block.text) } catch { return null } }).filter(value => value?.provider === 'aliyun-vision')
  assert.deepEqual(review.visual_results, originals)
  for (const file of ['psd.png', 'spectrogram_ch0.png']) {
    const visual = originals.find(value => value.source_path === path.join(sourceDir, file))
    assert.ok(visual, '未实际视觉核对：' + file)
    assert.equal(visual.model, process.env.VLM_MODEL)
    assert.equal(visual.source_sha256, hashes[file])
    assert.ok(visual.answer.trim())
  }
  assert.ok(result.events.some(event => event.type === 'user/message' && event.data?.source?.kind === 'skill-invocation' && event.data.source.name === 'underwater-data-inspection') || result.events.some(event => event.type === 'tool/call' && event.data.name === 'skill' && event.data.arguments.includes('underwater-data-inspection')), '没有通过SDK加载正式Skill')
  for (const [file, hash] of Object.entries(hashes)) assert.equal(createHash('sha256').update(fs.readFileSync(path.join(sourceDir, file))).digest('hex'), hash, '修改了既有产物')
  Object.assign(summary, { status: 'passed', model: process.env.VLM_MODEL, sessionId: result.sessionId, visualCalls: originals.length })
  console.log('Skill numerical + real visual review passed: ' + path.join(dir, 'summary.json'))
} catch (error) {
  summary.status = 'failed'; summary.error = error.message
  throw error
} finally {
  try { await harness.close() }
  finally {
    fs.writeFileSync(path.join(dir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
    if (!fs.existsSync(path.join(dir, 'events.json'))) fs.writeFileSync(path.join(dir, 'events.json'), JSON.stringify(events, null, 2) + '\n')
  }
}
