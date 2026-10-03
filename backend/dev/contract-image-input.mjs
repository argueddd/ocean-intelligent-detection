/** Real HTTP tests for upload → VLM observations, without credentials or paid model calls. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import sharp from 'sharp'
import { analyzeImageAttachments } from '../integrations.js'

async function fixture(t, respond) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'ocean-image-input-'))
  const keys = ['VLM_API_KEY', 'VLM_BASE_URL', 'VLM_MODEL', 'VLM_REASONING_EFFORT', 'VLM_MAX_IMAGE_BYTES']
  const original = Object.fromEntries(keys.map(key => [key, process.env[key]]))
  const calls = []
  const server = http.createServer(async (req, res) => {
    const chunks = []
    for await (const chunk of req) chunks.push(chunk)
    const call = { body: JSON.parse(Buffer.concat(chunks).toString()), req, res }
    calls.push(call)
    if (respond) return respond(call)
    res.setHeader('content-type', 'application/json')
    res.end(JSON.stringify({ choices: [{ message: { content: '可见峰值位于 128 Hz 附近。' }, finish_reason: 'stop' }] }))
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  Object.assign(process.env, { VLM_API_KEY: 'fixture-key', VLM_BASE_URL: `http://127.0.0.1:${server.address().port}/v1`, VLM_MODEL: 'qwen3.8-omni-flash', VLM_REASONING_EFFORT: 'none', VLM_MAX_IMAGE_BYTES: '5242880' })
  t.after(async () => {
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
    for (const [key, value] of Object.entries(original)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
    await fs.rm(root, { recursive: true, force: true })
  })
  const bytes = await sharp({ create: { width: 16, height: 8, channels: 3, background: '#fff' } }).png().toBuffer()
  const image = path.join(root, '频谱.png')
  await fs.writeFile(image, bytes)
  return { root, calls, bytes, image }
}

test('the VLM receives actual image pixels and the original text question together', async t => {
  const f = await fixture(t)
  const question = '只解释横轴，不要分析其他部分。'
  const result = await analyzeImageAttachments([f.image], question)
  assert.equal(f.calls.length, 1)
  const { body, req } = f.calls[0]
  assert.equal(req.url, '/v1/chat/completions')
  assert.equal(body.model, 'qwen3.8-omni-flash')
  assert.equal(body.reasoning_effort, 'none')
  const content = body.messages[0].content
  assert.ok(content[0].text.includes(question))
  assert.equal(content.find(block => block.type === 'image_url').image_url.url, 'data:image/png;base64,' + f.bytes.toString('base64'))
  assert.match(result, /128 Hz/)
  assert.match(result, /识别误差/)
  assert.match(result, /不重复调用视觉工具/)
})

test('ordinary file attachments do not trigger a visual request', async t => {
  const f = await fixture(t)
  delete process.env.VLM_API_KEY
  const result = await analyzeImageAttachments([path.join(f.root, 'samples.csv')], '体检数据')
  assert.equal(result, '')
  assert.equal(f.calls.length, 0)
})

test('corrupt rasters and extension/content mismatches fail before model dispatch', async t => {
  const f = await fixture(t)
  const bad = path.join(f.root, '坏图.png')
  const mismatch = path.join(f.root, '伪jpeg.jpg')
  await fs.writeFile(bad, f.bytes.subarray(0, 32))
  await fs.writeFile(mismatch, f.bytes)
  await assert.rejects(analyzeImageAttachments([bad], '识图'), /无法解码/)
  await assert.rejects(analyzeImageAttachments([mismatch], '识图'), /格式不一致/)
  assert.equal(f.calls.length, 0)
})

test('image byte budgets are enforced before model dispatch', async t => {
  const f = await fixture(t)
  process.env.VLM_MAX_IMAGE_BYTES = '32'
  await assert.rejects(analyzeImageAttachments([f.image], '识图'), /输入限制/)
  assert.equal(f.calls.length, 0)
})

test('JPEG, WebP and GIF are decoded and sent using their actual MIME types', async t => {
  const f = await fixture(t)
  for (const [extension, type] of [['jpeg', 'image/jpeg'], ['webp', 'image/webp'], ['gif', 'image/gif']]) {
    const file = path.join(f.root, 'fixture.' + extension)
    await fs.writeFile(file, await sharp(f.bytes).toFormat(extension).toBuffer())
    await analyzeImageAttachments([file], '识图')
    assert.ok(f.calls.at(-1).body.messages[0].content.find(block => block.type === 'image_url').image_url.url.startsWith('data:' + type + ';base64,'))
  }
})

test('stopping during visual HTTP analysis aborts the actual upstream request', async t => {
  let observed, closed
  const started = new Promise(resolve => { observed = resolve })
  const disconnected = new Promise(resolve => { closed = resolve })
  const f = await fixture(t, ({ res }) => { res.on('close', closed); observed() })
  const controller = new AbortController()
  const pending = analyzeImageAttachments([f.image], '识图', { signal: controller.signal })
  await started
  controller.abort(new DOMException('用户停止', 'AbortError'))
  await assert.rejects(pending, { name: 'AbortError' })
  await Promise.race([disconnected, new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error('upstream socket not closed')), 3000); timer.unref() })])
  assert.equal(f.calls.length, 1)
})

test('an already cancelled request never reads or sends images', async t => {
  const f = await fixture(t)
  const controller = new AbortController()
  controller.abort(new DOMException('用户停止', 'AbortError'))
  await assert.rejects(analyzeImageAttachments([f.image], '识图', { signal: controller.signal }), { name: 'AbortError' })
  assert.equal(f.calls.length, 0)
})

test('truncated observations are marked partial rather than claimed complete', async t => {
  const f = await fixture(t, ({ res }) => res.end(JSON.stringify({ choices: [{ message: { content: '可见横轴。' }, finish_reason: 'length' }] })))
  assert.match(await analyzeImageAttachments([f.image], '识图'), /被截断/)
})

test('empty, blocked and HTTP error responses never become successful observations', async t => {
  let mode = 'empty'
  const f = await fixture(t, ({ res }) => {
    if (mode === 'http') { res.statusCode = 503; return res.end(JSON.stringify({ error: { message: 'fixture unavailable' } })) }
    res.end(JSON.stringify({ choices: [{ message: { content: mode === 'empty' ? '' : '部分内容' }, finish_reason: 'content_filter' }] }))
  })
  await assert.rejects(analyzeImageAttachments([f.image], '识图'), /未返回/)
  mode = 'blocked'
  await assert.rejects(analyzeImageAttachments([f.image], '识图'), /未正常完成/)
  mode = 'http'
  await assert.rejects(analyzeImageAttachments([f.image], '识图'), /HTTP 503/)
})
