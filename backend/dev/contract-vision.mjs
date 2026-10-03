/** Real SDK filesystem/attachment admission and isolated mock visual responses. */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import sharp from 'sharp'
import { Context, Service } from '@deepseek-ai/cordis'
import { LocalFileSystem } from '@deepseek-ai/dsh-fs-local'
import { LocalAttachmentStore } from '@deepseek-ai/dsh-attachment-local'
import { SystemPrompt } from '@deepseek-ai/dsh-system-prompt'
import { ToolRuntime, validateJsonSchemaValue } from '@deepseek-ai/dsh-tools'
import { apply, inject } from '../dsh/harness-vision/lib/index.js'

class MockVisualModel extends Service {
  constructor(ctx) {
    super(ctx, 'llm')
    this.requests = []
    this.resolutions = []
    this.inputModalities = ['text', 'image']
    this.chunks = [
      { type: 'text-delta', index: 0, text: '横轴频率；' },
      { type: 'text-delta', index: 0, text: '128 Hz 附近可见峰值。' },
      { type: 'usage', usage: { inputTokens: 72, outputTokens: 18, totalTokens: 90 } },
      { type: 'finish', reason: { kind: 'stop' } },
    ]
  }
  async resolveModelInfo(provider, model, signal) {
    signal?.throwIfAborted()
    this.resolutions.push({ provider, model })
    return { provider, model, inputModalities: this.inputModalities }
  }
  stream(request) {
    this.requests.push(request)
    if (this.handler) return this.handler(request)
    const chunks = this.chunks
    return (async function* () {
      for (const chunk of chunks) {
        request.signal?.throwIfAborted()
        yield chunk
      }
    })()
  }
}

async function fixture(t, config = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'ocean-vision-contract-'))
  t.after(() => fs.rm(root, { recursive: true, force: true }))
  const ctx = new Context()
  new SystemPrompt(ctx, {})
  new ToolRuntime(ctx)
  const filesystem = new LocalFileSystem(ctx, { cwd: root, diffBasisMaxBytes: 10 * 1024 * 1024 })
  const attachments = new LocalAttachmentStore(ctx, { dshHome: path.join(root, 'harness-home') })
  const llm = new MockVisualModel(ctx)
  apply(ctx, config)
  const tool = ctx.tools.get('vision_inspect')
  const signal = new AbortController()
  const execution = { signal: signal.signal, agent: { session: { header: { cwd: root }, id: 'fixture-session' }, options: { provider: 'primary-text-only', model: 'main-text-model' } } }
  const image = await sharp({ create: { width: 8, height: 4, channels: 3, background: '#ffffff' } }).png().toBuffer()
  const png = path.join(root, '频谱 chart.png')
  await fs.writeFile(png, image)
  return { root, ctx, filesystem, attachments, llm, tool, signal, execution, image, png,
    run: (args = {}) => tool.execute({ file_path: png, question: '核对坐标轴和可见峰。', ...args }, execution) }
}

test('valid image is admitted by real SDK and only attributed text reaches the main model', async t => {
  const f = await fixture(t)
  const result = await f.run({ file_path: path.basename(f.png) })
  assert.equal(result.status, 'completed')
  assert.equal(result.provider, 'aliyun-vision')
  assert.equal(result.model, 'qwen3.8-omni-flash')
  assert.equal(result.source_path, f.png)
  assert.equal(result.source_bytes, f.image.length)
  assert.equal(result.source_sha256, createHash('sha256').update(f.image).digest('hex'))
  assert.deepEqual(result.usage, { inputTokens: 72, outputTokens: 18, totalTokens: 90 })
  assert.equal(result.attachment_width, 8)
  assert.equal(result.attachment_height, 4)
  assert.equal(result.answer, '横轴频率；128 Hz 附近可见峰值。')
  const request = f.llm.requests[0]
  assert.equal(request.provider, 'aliyun-vision')
  assert.equal(request.model, 'qwen3.8-omni-flash')
  assert.equal(request.sessionId, 'fixture-session')
  assert.ok(request.signal.aborted, 'the nested model signal is closed after success')
  assert.equal(f.signal.signal.aborted, false, 'closing the nested call must not abort its parent')
  assert.deepEqual(request.messages[0].content.map(block => block.type), ['text', 'image'])
  const stored = await f.attachments.readImage(request.messages[0].content[1].attachment)
  assert.ok(stored.data.byteLength > 0)
  const rendered = f.tool.output.render({}, result)
  assert.equal(rendered.length, 1)
  assert.equal(rendered[0].type, 'text')
  assert.deepEqual(JSON.parse(rendered[0].text), result)
  assert.equal(validateJsonSchemaValue(f.tool.output.schema, result).length, 0)
  assert.deepEqual(inject, ['tools', 'fs', 'attachments', 'llm'])
})

test('filesystem denial is propagated and never bypassed with host IO', async t => {
  const f = await fixture(t)
  let reads = 0
  f.filesystem.readBytes = async () => { reads++; throw Object.assign(new Error('filesystem policy denied'), { code: 'FS_ACCESS_DENIED' }) }
  await assert.rejects(f.run(), { code: 'FS_ACCESS_DENIED' })
  assert.equal(reads, 1)
  assert.equal(f.llm.requests.length, 0)
})

test('credential filenames and unsupported extensions are refused before reading any bytes', async t => {
  const f = await fixture(t)
  let reads = 0
  f.filesystem.readBytes = async () => { reads++; throw new Error('must not read') }
  for (const file_path of [path.join(f.root, '.env'), path.join(f.root, '.env.local'), path.join(f.root, 'input.svg')]) {
    await assert.rejects(f.run({ file_path }), { code: 'VISION_UNSUPPORTED_IMAGE' })
  }
  assert.equal(reads, 0)
  assert.equal(f.llm.resolutions.length, 0)
})

test('byte budget, missing files and directories fail before attachment or model dispatch', async t => {
  const f = await fixture(t, { maxImageBytes: 8 })
  await assert.rejects(f.run(), { code: 'VISION_IMAGE_TOO_LARGE' })
  await assert.rejects(f.run({ file_path: path.join(f.root, 'missing.png') }), { code: 'VISION_FILE_NOT_FOUND' })
  const directory = path.join(f.root, 'directory.png')
  await fs.mkdir(directory)
  await assert.rejects(f.run({ file_path: directory }), { code: 'VISION_NOT_REGULAR_FILE' })
  assert.equal(f.llm.requests.length, 0)
})

test('extension-less images work but mismatched and corrupt rasters never reach the visual model', async t => {
  const f = await fixture(t)
  const extensionless = path.join(f.root, 'attachment-object')
  await fs.writeFile(extensionless, f.image)
  assert.equal((await f.run({ file_path: extensionless })).status, 'completed')
  const mismatch = path.join(f.root, 'wrong.jpg')
  await fs.writeFile(mismatch, f.image)
  await assert.rejects(f.run({ file_path: mismatch }), { code: 'VISION_IMAGE_TYPE_MISMATCH' })
  const corrupt = path.join(f.root, 'corrupt.png')
  await fs.writeFile(corrupt, f.image.subarray(0, 16))
  await assert.rejects(f.run({ file_path: corrupt }), /IMAGE|image|decode|Invalid|corrupt/i)
  assert.equal(f.llm.requests.length, 1)
})

test('image capability is checked on the independent route regardless of the main text model', async t => {
  const f = await fixture(t, { model: 'configured-vision-model' })
  const result = await f.run()
  assert.equal(result.model, 'configured-vision-model')
  assert.equal(f.llm.requests[0].model, 'configured-vision-model')
  f.llm.inputModalities = ['text']
  await assert.rejects(f.run(), { code: 'VISION_ROUTE_NOT_CAPABLE' })
  assert.equal(f.llm.requests.length, 1)
})

test('reasoning and returned image blocks are excluded from the plain text tool result', async t => {
  const f = await fixture(t)
  f.llm.chunks = [
    { type: 'reasoning-delta', index: 0, text: 'Private reasoning must not be returned.' },
    { type: 'block-end', index: 1, block: { type: 'image', attachment: { invalid: 'not returned' } } },
    { type: 'block-end', index: 2, block: { type: 'text', text: 'Visible answer only.' } },
    { type: 'finish', reason: { kind: 'stop' } },
  ]
  const result = await f.run()
  assert.equal(result.answer, 'Visible answer only.')
  assert.deepEqual(f.tool.output.render({}, result).map(block => block.type), ['text'])
  assert.ok(!JSON.stringify(result).includes('Private reasoning'))
  assert.ok(!JSON.stringify(result).includes('not returned'))
})

test('terminal failures, missing finish and empty answers are explicit failures; truncated answer is partial', async t => {
  const f = await fixture(t)
  for (const [kind, expected] of [['error', 'VISION_MODEL_ERROR'], ['aborted', 'VISION_ABORTED']]) {
    f.llm.chunks = [{ type: 'finish', reason: { kind, failure: { code: 'RATE_LIMIT', status: 429, message: 'Raw diagnostic is not echoed.' } } }]
    await assert.rejects(f.run(), error => error.code === expected && error.message.includes('RATE_LIMIT') && !error.message.includes('Raw diagnostic'))
  }
  f.llm.chunks = [{ type: 'text-delta', index: 0, text: 'Incomplete transport.' }]
  await assert.rejects(f.run(), { code: 'VISION_INCOMPLETE_STREAM' })
  f.llm.chunks = [{ type: 'finish', reason: { kind: 'stop' } }]
  await assert.rejects(f.run(), { code: 'VISION_EMPTY_RESPONSE' })
  f.llm.chunks = [{ type: 'text-delta', index: 0, text: 'Partial answer.' }, { type: 'finish', reason: { kind: 'max-tokens' } }]
  assert.equal((await f.run()).status, 'partial')
})

test('response character budget is enforced without forwarding oversized content', async t => {
  const f = await fixture(t, { maxResponseChars: 5 })
  await assert.rejects(f.run(), { code: 'VISION_RESPONSE_TOO_LARGE' })
  assert.ok(f.llm.requests[0].signal.aborted)
  assert.equal(f.signal.signal.aborted, false)
})

test('the filesystem byte cap also rejects files when preflight metadata underreports size', async t => {
  const f = await fixture(t, { maxImageBytes: 8 })
  const originalStat = f.filesystem.stat.bind(f.filesystem)
  f.filesystem.stat = async (...args) => ({ ...await originalStat(...args), size: 1 })
  await assert.rejects(f.run(), { code: 'FS_TOO_LARGE' })
  assert.equal(f.llm.requests.length, 0)
})

test('an already cancelled caller performs no filesystem read or model lookup', async t => {
  const f = await fixture(t)
  f.signal.abort(new Error('already cancelled fixture'))
  await assert.rejects(f.run(), /already cancelled fixture/)
  assert.equal(f.llm.resolutions.length, 0)
  assert.equal(f.llm.requests.length, 0)
})

test('caller cancellation aborts the independent stream and returns promptly', async t => {
  const f = await fixture(t)
  let requestSignal
  f.llm.handler = request => {
    requestSignal = request.signal
    queueMicrotask(() => f.signal.abort(new Error('caller cancelled fixture')))
    return { [Symbol.asyncIterator]: () => ({ next: () => new Promise(() => {}), return: () => Promise.resolve({ done: true }) }) }
  }
  await assert.rejects(f.run(), /caller cancelled fixture/)
  assert.ok(requestSignal.aborted)
})

test('timeout bounds even an uncooperative model stream and marks its signal aborted', { timeout: 5000 }, async t => {
  // Allow real SDK file admission/decoding to reach the model even on a busy host.
  // The outer test deadline still catches a broken bound on the never-resolving stream.
  const f = await fixture(t, { timeoutMs: 1000 })
  let requestSignal
  f.llm.handler = request => {
    requestSignal = request.signal
    return { [Symbol.asyncIterator]: () => ({ next: () => new Promise(() => {}), return: () => Promise.resolve({ done: true }) }) }
  }
  await assert.rejects(f.run(), { code: 'VISION_TIMEOUT' })
  assert.ok(requestSignal, 'fixture must reach the independent model before testing its timeout')
  assert.ok(requestSignal.aborted)
})
