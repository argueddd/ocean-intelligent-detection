/** 真实主模型 → SDK视觉工具 → 独立视觉模型；图片来源与纯文本返回均可核验。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { randomUUID, createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { backendDir, workspaceRoot, pythonEnvironment, createProjectHarness } from '../harness/runtime.mjs'
import { runHarnessTask } from '../harness/task.mjs'

process.loadEnvFile(path.join(backendDir, '.env'))
assert.ok(process.env.VLM_API_KEY, '需要配置 VLM_API_KEY')
const args = process.argv.slice(2)
const resume = args.includes('--resume')
const id = resume ? args[args.indexOf('--resume') + 1] : randomUUID()
assert.match(id || '', /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/)
const dir = path.join(workspaceRoot, '.run', 'harness-vision-smoke', id)
fs.mkdirSync(dir, { recursive: true })
const imageFile = path.join(dir, '未标定 频谱.png')
const output = path.join(dir, 'vision-result.json')
const { python, env } = pythonEnvironment()
if (!resume) execFileSync(python, ['-c', `import sys,numpy as np
from scipy import signal
import matplotlib.pyplot as plt
t=np.arange(4096)/1024
fig,ax=plt.subplots(figsize=(10,4))
for channel,(freq,amplitude) in enumerate([(80,1),(96,.8)]):
 f,p=signal.welch(amplitude*np.sin(2*np.pi*freq*t),fs=1024,nperseg=512,noverlap=256)
 ax.plot(f,10*np.log10(np.maximum(p,1e-300)),label=f'ch {channel}')
ax.set(xlabel='Frequency (Hz)',ylabel='PSD (dB re 1 raw-unit²/Hz)',title='Welch PSD | uncalibrated numeric scale')
ax.legend();fig.tight_layout();fig.savefig(sys.argv[1],dpi=140);plt.close(fig)
`, imageFile], { cwd: workspaceRoot, env })
const sourceHash = createHash('sha256').update(fs.readFileSync(imageFile)).digest('hex')
const harness = resume ? null : createProjectHarness({ home: path.join(dir, 'runtime') })
const events = []
const summary = { status: 'running', source: imageFile, sourceSha256: sourceHash }
const cancel = () => { harness?.close().catch(() => {}) }
process.once('SIGINT', cancel); process.once('SIGTERM', cancel)
try {
  const result = resume ? { events: JSON.parse(fs.readFileSync(path.join(dir, 'events.json'), 'utf8')), finalResponse: fs.readFileSync(path.join(dir, 'response.txt'), 'utf8'), sessionId: null } : await runHarnessTask(harness, `请用当前配置的独立视觉模型实际读取 ${imageFile}，核对曲线数量、横纵轴、主要峰的大约频率、图上是否已标定物理声压；图像估计无需假装精确到频点。请把视觉工具的完整原始JSON结果保存到 ${output}，保留来源、实际模型和回答。不要写代码替代读图、不读其他数值文件、不安装依赖、不创建子智能体。最后简洁说明视觉观察与不能仅凭图像断言的事。`, {
    timeoutMs: 240000,
    onNotification(notification) {
      const event = notification.params?.event
      if (event) { events.push(event); fs.appendFileSync(path.join(dir, 'events.jsonl'), JSON.stringify(event) + '\n') }
      if (event?.type === 'tool/call') console.log('[tool] ' + event.data.name)
    },
  })
  fs.writeFileSync(path.join(dir, 'events.json'), JSON.stringify(result.events, null, 2) + '\n')
  fs.writeFileSync(path.join(dir, 'response.txt'), result.finalResponse + '\n')
  const report = JSON.parse(fs.readFileSync(output, 'utf8'))
  const reports = Array.isArray(report.results) ? report.results : [report]
  assert.ok(reports.length && reports.some(value => value.status === 'completed'), '没有完整视觉响应')
  const calls = result.events.filter(event => event.type === 'tool/call' && event.data.name === 'vision_inspect')
  assert.ok(calls.length, '主模型没有真实调用视觉工具')
  const originals = []
  for (const event of result.events.filter(event => event.type === 'tool/result')) {
    for (const block of event.data.message.content.filter(block => block.type === 'tool-result' && !block.isError)) {
      for (const text of block.content.filter(value => value.type === 'text')) {
        let value
        try { value = JSON.parse(text.text) } catch { continue }
        if (value?.source_sha256 !== sourceHash) continue
        assert.ok(block.content.every(value => value.type === 'text'), '主文本模型收到图片块')
        originals.push(value)
      }
    }
  }
  assert.equal(reports.length, originals.length, '未保存全部原始视觉响应')
  for (const visual of reports) {
    assert.ok(['completed', 'partial'].includes(visual.status))
    assert.equal(visual.status, visual.finish_reason === 'stop' ? 'completed' : 'partial')
    assert.equal(visual.provider, 'aliyun-vision')
    assert.equal(visual.model, process.env.VLM_MODEL)
    assert.equal(visual.source_path, imageFile)
    assert.equal(visual.source_sha256, sourceHash)
    assert.ok(['image/png', 'image/webp'].includes(visual.attachment_media_type), 'SDK附件应保留有效图像类型，允许其默认WebP优化')
    assert.ok(visual.attachment_width > 500 && visual.attachment_height > 200)
    assert.ok(visual.answer.trim().length > 30)
    assert.ok(originals.some(original => { try { assert.deepEqual(visual, original); return true } catch { return false } }), '原始视觉结果被改写')
  }
  assert.equal(createHash('sha256').update(fs.readFileSync(imageFile)).digest('hex'), sourceHash)
  for (const secret of [process.env.VLM_API_KEY, process.env.LLM_API_KEY].filter(Boolean)) {
    assert.ok(!JSON.stringify(result.events).includes(secret), '事件记录包含凭据')
    assert.ok(!JSON.stringify(report).includes(secret), '视觉报告包含凭据')
  }
  Object.assign(summary, { status: 'passed', model: reports[0].model, output, sessionId: result.sessionId, visualCalls: calls.length, reusedRecordedRun: resume })
  console.log('Real Harness vision delegation passed: ' + path.join(dir, 'summary.json'))
  console.log(reports.map(value => value.answer).join('\n\n'))
} catch (error) {
  Object.assign(summary, { status: 'failed', error: String(error.message) })
  throw error
} finally {
  try { if (harness) await harness.close() }
  finally {
    process.removeListener('SIGINT', cancel); process.removeListener('SIGTERM', cancel)
    fs.writeFileSync(path.join(dir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
    if (!fs.existsSync(path.join(dir, 'events.json'))) fs.writeFileSync(path.join(dir, 'events.json'), JSON.stringify(events, null, 2) + '\n')
  }
}
