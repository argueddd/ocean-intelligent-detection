/** Opt-in real browser-adapter/model checks. Uses fresh sessions and generated fixtures only. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { setTimeout as delay } from 'node:timers/promises'
import sharp from 'sharp'

const root = path.resolve(import.meta.dirname, '../..')
const base = process.env.HARNESS_TEST_API || 'http://127.0.0.1:3089'
const directory = path.join(root, '.run/harness-input-cancel', randomUUID())
fs.mkdirSync(directory, { recursive: true })
const results = []
const streams = new Set()
const id = prefix => prefix + randomUUID().replaceAll('-', '')
const picture = await sharp(Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="560"><rect width="1000" height="560" fill="white"/><g font-family="Arial" fill="black"><text x="100" y="70" font-size="40">Spectrum: two labelled peaks</text><path d="M100 440H930 M100 120V440" stroke="black" stroke-width="3"/><path d="M100 420L270 420L315 180L360 420L630 420L680 250L730 420L930 420" fill="none" stroke="blue" stroke-width="4"/><text x="235" y="150" font-size="52">128 Hz</text><text x="605" y="220" font-size="52">256 Hz</text><text x="390" y="510" font-size="32">Frequency (Hz)</text></g></svg>`)).png().toBuffer()
fs.writeFileSync(path.join(directory, 'input.png'), picture)
const attachment = { name: 'spectrum.png', kind: 'image', mimeType: 'image/png', data: picture.toString('base64') }

async function until(check, message, timeout = 20000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) { if (check()) return; await delay(40) }
  throw new Error(message)
}
async function stream(name, message, { sessionId = id('session-input-'), attachments } = {}) {
  const requestId = id('request-')
  const controller = new AbortController()
  const frames = []
  const response = await fetch(base + '/api/chat/stream', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ requestId, sessionId, message, attachments }), signal: controller.signal })
  assert.equal(response.status, 200, await (response.ok ? Promise.resolve('') : response.text()))
  const state = { name, sessionId, requestId, controller, frames }
  streams.add(state)
  state.finished = (async () => {
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let pending = '', raw = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const text = decoder.decode(value, { stream: true })
        pending += text; raw += text
        let end
        while ((end = pending.indexOf('\n\n')) >= 0) {
          const block = pending.slice(0, end); pending = pending.slice(end + 2)
          const kind = /^event:\s*(.+)$/m.exec(block)?.[1]
          const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
          if (kind && data) {
            const frame = { kind, data: JSON.parse(data) }; frames.push(frame)
            if (kind === 'start') state.sessionId = frame.data.sessionId
            if (kind === 'renamed') state.sessionId = frame.data.to
          }
        }
      }
    } finally {
      reader.releaseLock()
      fs.writeFileSync(path.join(directory, name + '.sse'), raw)
      streams.delete(state)
    }
    return frames
  })()
  state.finished.catch(() => {})
  return state
}
async function cancel(state) {
  const began = Date.now()
  const response = await fetch(base + '/api/chat/cancel', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ requestId: state.requestId, sessionId: state.sessionId }), signal: AbortSignal.timeout(45000) })
  const body = await response.json()
  assert.equal(response.status, 200, JSON.stringify(body))
  assert.equal(body.cancelled, true)
  assert.equal(body.sessionId, state.sessionId)
  await state.finished
  assert.ok(state.frames.some(frame => frame.kind === 'cancelled'), 'missing cancellation acknowledgement in SSE')
  assert.ok(!state.frames.some(frame => frame.kind === 'done'), 'cancelled task was reported as completed')
  return Date.now() - began
}
async function answer(name, message, opts) {
  const state = await stream(name, message, opts)
  let timer
  try { await Promise.race([state.finished, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('answer timed out')), 120000) })]) }
  finally { clearTimeout(timer) }
  const done = state.frames.find(frame => frame.kind === 'done')
  assert.ok(done, JSON.stringify(state.frames.find(frame => frame.kind === 'error')?.data || state.frames.at(-1)))
  return { state, text: done.data.finalResponse }
}
async function scenario(name, run) {
  const began = Date.now()
  try { results.push({ name, status: 'passed', ...(await run()), elapsedMs: Date.now() - began }) }
  catch (error) { results.push({ name, status: 'failed', error: error.message, elapsedMs: Date.now() - began }); throw error }
  finally { fs.writeFileSync(path.join(directory, 'summary.json'), JSON.stringify({ directory, results }, null, 2) + '\n'); console.log(JSON.stringify(results.at(-1))) }
}

try {
  await scenario('image-and-text', async () => {
    const { state, text } = await answer('image-and-text', '读出图片中标注的两个峰频率，并计算它们的频率差。只用一句中文回答，末尾加“图片联合测试完成”。', { attachments: [attachment] })
    assert.match(text, /128/); assert.match(text, /256/); assert.match(text, /图片联合测试完成/)
    assert.ok(state.frames.some(frame => frame.kind === 'phase' && /解读上传图片/.test(frame.data.message)))
    const calls = state.frames.filter(frame => frame.data.params?.event?.type === 'tool/call')
    assert.equal(calls.length, 0, 'automatic image interpretation should not need repeated tool calls')
    fs.writeFileSync(path.join(directory, 'image-answer.md'), text + '\n')
    return { sessionId: state.sessionId, toolCount: calls.length, answer: text }
  })
  await scenario('cancel-image-preparation', async () => {
    const state = await stream('cancel-image-preparation', '解读图片中的坐标轴和峰值，给详细说明。', { attachments: [attachment] })
    await until(() => state.frames.some(frame => frame.kind === 'phase'), 'no visual phase')
    const cancelMs = await cancel(state)
    const followup = await answer('after-image-cancel', '请只回答：可以继续。', { sessionId: state.sessionId })
    assert.equal(followup.state.sessionId, state.sessionId)
    assert.match(followup.text, /可以继续/)
    return { sessionId: state.sessionId, cancelMs, followup: followup.text }
  })
  await scenario('cancel-model-generation', async () => {
    const state = await stream('cancel-model-generation', '详细比较常规波束形成和MVDR：说明两种方法的数学基础、参数选择与适用条件，写1500字。')
    await until(() => state.frames.some(frame => frame.data.params?.event?.type === 'step/start'), 'model did not start')
    const cancelMs = await cancel(state)
    const followup = await answer('after-model-cancel', '上一轮我请你比较哪两种方法？只用名称回答。', { sessionId: state.sessionId })
    assert.equal(followup.state.sessionId, state.sessionId)
    assert.match(followup.text, /MVDR/i)
    assert.match(followup.text, /常规|传统/)
    return { sessionId: state.sessionId, cancelMs, followup: followup.text }
  })
  await scenario('cancel-python-and-preserve-other-session', async () => {
    const script = path.join(directory, 'hold-for-cancel.py')
    const heartbeat = path.join(directory, 'heartbeat.txt')
    const completed = path.join(directory, 'completed.txt')
    fs.writeFileSync(script, `import time,pathlib,os\np=pathlib.Path(${JSON.stringify(heartbeat)})\np.with_suffix('.pid').write_text(str(os.getpid()))\nfor i in range(450):\n    with p.open('a') as f: f.write(str(i)+'\\n')\n    time.sleep(0.1)\npathlib.Path(${JSON.stringify(completed)}).write_text('completed')\n`)
    const state = await stream('cancel-python', `请用 bash 前台执行项目 Python 脚本 ${script}，timeoutMs 120000。只调用一次 bash，不转为后台，不读其他文件，等待执行结束再回复。description 写“运行取消测试脚本”。`)
    await until(() => fs.existsSync(heartbeat) && fs.statSync(heartbeat).size > 0, 'real Python script did not start', 45000)
    const unrelated = answer('unrelated-session', '请只输出：独立会话正常。')
    unrelated.catch(() => {})
    const cancelMs = await cancel(state)
    const stoppedSize = fs.statSync(heartbeat).size
    await delay(400)
    assert.equal(fs.statSync(heartbeat).size, stoppedSize, 'Python kept writing after cancellation')
    assert.equal(fs.existsSync(completed), false)
    const pid = Number(fs.readFileSync(path.join(directory, 'heartbeat.pid'), 'utf8'))
    let alive = true
    try { process.kill(pid, 0) } catch (error) { if (error.code === 'ESRCH') alive = false; else throw error }
    assert.equal(alive, false, 'Python process still alive after cancellation acknowledgement')
    const independent = await unrelated
    assert.match(independent.text, /独立会话正常/)
    const followup = await answer('after-python-cancel', '上一轮我请求执行的 Python 脚本文件名是什么？只回答文件名。', { sessionId: state.sessionId })
    assert.equal(followup.state.sessionId, state.sessionId)
    assert.match(followup.text, /hold-for-cancel\.py/)
    return { sessionId: state.sessionId, cancelMs, pidExited: true, heartbeatStopped: true, otherSessionAnswer: independent.text, followup: followup.text }
  })
  await scenario('cancel-before-start', async () => {
    const requestId = id('request-early-'), sessionId = id('session-early-')
    const response = await fetch(base + '/api/chat/cancel', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ requestId, sessionId }) })
    assert.equal(response.status, 200)
    const late = await fetch(base + '/api/chat/stream', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ requestId, sessionId, message: '这轮已取消，不应执行。' }) })
    const raw = await late.text()
    assert.match(raw, /event: cancelled/)
    assert.doesNotMatch(raw, /event: (?:notification|done)/)
    fs.writeFileSync(path.join(directory, 'early-stop.sse'), raw)
    const followup = await answer('after-early-stop', '请只回答：同一会话继续。', { sessionId })
    assert.equal(followup.state.sessionId, sessionId)
    assert.match(followup.text, /同一会话继续/)
    return { sessionId, followup: followup.text }
  })
} catch (error) { process.exitCode = 1; console.error(error.message) }
finally {
  for (const state of streams) { try { await cancel(state) } catch { state.controller.abort() } }
  console.log('Evidence: ' + directory)
}
