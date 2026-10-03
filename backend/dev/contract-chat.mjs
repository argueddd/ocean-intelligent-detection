/** 隔离加载实际 HTTP 适配层：用假 SDK/HTTP server，不启动真实模型或监听端口。 */
import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import { execFile } from 'node:child_process'
import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { Readable } from 'node:stream'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import vm from 'node:vm'

function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

async function adapter({ start = async () => {}, run = async () => ({ events: [], finalResponse: 'ok' }), filesystem = fs,
  env = {}, analyze = async () => '', health = async () => ({ ok: true }), cancel = async ({ sessionId }) => ({ status: 'cancelled', sessionId }) } = {}) {
  let route
  const calls = { legacyOptions: [], projectOptions: [], patches: [], images: [], proxies: [], cancels: [], closes: 0 }
  const session = (id) => ({ id, run: (...args) => run(id, ...args) })
  class Harness {
    constructor(options) { calls.legacyOptions.push(options) }
    start = start
    session = session
    async close() { calls.closes++ }
  }
  const context = vm.createContext({
    Buffer, URL, AbortController, crypto: crypto.webcrypto, console: { log() {} },
    process: { env, loadEnvFile() {}, on() {} },
    fs: filesystem, path, execFile, promisify, fileURLToPath,
    http: { ...http, createServer(handler) { route = handler; return { listen() {}, close() {} } },
      request(options, config, responseCallback) {
        const callback = typeof config === 'function' ? config : responseCallback
        const isCancel = options instanceof URL && options.pathname === '/cancel'
        if (!isCancel) calls.proxies.push(options)
        const request = new EventEmitter()
        request.write = () => {}
        request.end = (body) => queueMicrotask(async () => {
          let result
          if (isCancel) {
            const data = JSON.parse(String(body))
            calls.cancels.push(data)
            try { result = await cancel(data) } catch (error) { request.emit('error', error); return }
          } else result = { proxied: true, pending: [] }
          const upstream = new EventEmitter()
          upstream.statusCode = 200
          upstream.headers = { 'content-type': 'application/json' }
          callback(upstream)
          upstream.emit('data', Buffer.from(JSON.stringify(result)))
          upstream.emit('end')
        })
        return request
      } },
    DeepSeekHarness: Harness,
    createProjectHarness(options) { calls.projectOptions.push(options); return { start, session, close: async () => { calls.closes++ } } },
    prepareHarnessHome(...args) { calls.patches.push(args); return '' }, integrationHealth: health,
    async analyzeImageAttachments(...args) { calls.images.push(args); return analyze(...args) },
  })
  const url = new URL('../index.js', import.meta.url)
  // 只替换依赖入口，HTTP 路由和锁逻辑均执行源文件；无需 SDK 安装或实验性 VM 模块。
  const source = fs.readFileSync(url, 'utf8').replace(/^import .*$/gm, '').replaceAll('import.meta.url', JSON.stringify(url.href))
  new vm.Script(source, { filename: fileURLToPath(url) }).runInContext(context)
  const request = (method, url, body) => {
      const req = Readable.from(body === undefined ? [] : [Buffer.from(JSON.stringify(body))])
      req.method = method
      req.url = url
      const response = new EventEmitter()
      Object.assign(response, {
        headersSent: false, writableEnded: false, chunks: [],
        writeHead(status) { this.status = status; this.headersSent = true },
        write(chunk) { this.chunks.push(chunk); return true },
        end(chunk) { if (chunk) this.chunks.push(chunk); this.writableEnded = true },
        text() { return this.chunks.join('') },
        events() {
          return this.text().split('\n\n').filter(Boolean).map((block) => {
            const [event, data] = block.split('\n')
            return { event: event.slice(7), data: JSON.parse(data.slice(6)) }
          })
        },
      })
      return { response, completion: route(req, response) }
  }
  return {
    calls, request,
    post(sessionId, attachments, requestId) { return request('POST', '/api/chat/stream', { sessionId, message: '分析数据', attachments, requestId }) },
  }
}

const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF9sAAAAASUVORK5CYII='

test('same session is reserved during asynchronous Harness startup', { timeout: 2000 }, async () => {
  const entered = deferred(), ready = deferred()
  let calls = 0
  const app = await adapter({
    start: async () => { entered.resolve(); await ready.promise },
    run: async () => { calls++; return { events: [], finalResponse: 'ok' } },
  })
  const first = app.post('same')
  try {
    await entered.promise
    const duplicate = app.post('same')
    await duplicate.completion
    assert.equal(duplicate.response.status, 409)
  } finally { ready.resolve(); await first.completion }
  assert.equal(calls, 1)
  assert.equal(first.response.status, 200)
  assert.equal(first.response.events().at(-1).event, 'done')
  const next = app.post('same')
  await next.completion
  assert.equal(next.response.status, 200, 'lock must release after success')
  assert.equal(calls, 2)
})

test('startup, attachment and run failures all release the session lock', { timeout: 2000 }, async () => {
  let starts = 0, calls = 0
  const app = await adapter({
    start: async () => { if (++starts === 1) throw new Error('startup failed') },
    run: async () => {
      if (++calls === 1) throw new Error('run failed')
      return { events: [], finalResponse: 'ok' }
    },
    filesystem: { ...fs, mkdirSync() { throw new Error('spool unavailable') } },
  })
  const attachment = app.post('same', [{ name: 'data.bin', data: 'AA==' }])
  await attachment.completion
  assert.equal(attachment.response.status, 502)
  assert.match(attachment.response.text(), /spool unavailable/)
  const startup = app.post('same')
  await startup.completion
  assert.equal(startup.response.events().at(-1).event, 'error')
  assert.match(startup.response.text(), /startup failed/)
  const failedRun = app.post('same')
  await failedRun.completion
  assert.equal(failedRun.response.events().at(-1).event, 'error')
  assert.match(failedRun.response.text(), /run failed/)
  const success = app.post('same')
  await success.completion
  assert.equal(success.response.events().at(-1).event, 'done')
  assert.equal(starts, 2, 'failed startup must be retried')
})

test('migration locks both old and new ids; stale ids resolve to the new session', { timeout: 2000 }, async () => {
  const entered = deferred(), ready = deferred()
  const app = await adapter({ run: async (id) => {
    if (id === 'old') throw new Error('session already exists')
    entered.resolve(id)
    await ready.promise
    return { events: [], finalResponse: 'ok' }
  } })
  const first = app.post('old')
  let migratedId
  try {
    migratedId = await entered.promise
    for (const id of ['old', migratedId]) {
      const duplicate = app.post(id)
      await duplicate.completion
      assert.equal(duplicate.response.status, 409)
    }
  } finally { ready.resolve(); await first.completion }
  const renamed = first.response.events().find((e) => e.event === 'renamed')
  assert.equal(renamed.data.to, migratedId)
  const next = app.post('old')
  await next.completion
  assert.equal(next.response.status, 200)
  assert.equal(next.response.events().find((e) => e.event === 'start').data.sessionId, migratedId)
  assert.equal(next.response.events().at(-1).data.sessionId, migratedId)
})

test('client disconnect keeps the lock until backend execution finishes', { timeout: 2000 }, async () => {
  const entered = deferred(), ready = deferred()
  const app = await adapter({ run: async () => {
    entered.resolve()
    await ready.promise
    return { events: [], finalResponse: 'ok' }
  } })
  const first = app.post('same')
  try {
    await entered.promise
    first.response.emit('close')
    const duplicate = app.post('same')
    await duplicate.completion
    assert.equal(duplicate.response.status, 409)
  } finally { ready.resolve(); await first.completion }
  assert.ok(!first.response.events().some((e) => e.event === 'done'), 'must not write after close')
  const next = app.post('same')
  await next.completion
  assert.equal(next.response.events().at(-1).event, 'done')
})

function notify(options, id, type, data = {}) {
  options.onNotification({ method: 'session.event', params: { sessionId: id, event: { type, data } } })
}

for (const profile of ['harness', 'rag-kb']) {
  test(`${profile} stop cancels the owned activity, waits for idle and permits a same-session followup`, { timeout: 2000 }, async () => {
    const entered = deferred(), stopping = deferred(), idle = deferred()
    let current, runs = 0
    const app = await adapter({ env: { DSH_PROFILE: profile }, run: async (id, _prompt, options) => {
      if (id !== 'same' || ++runs > 1) return { events: [], finalResponse: 'followup' }
      return await new Promise((resolve) => {
        current = { id, options, resolve }
        notify(options, id, 'step/start')
        entered.resolve()
      })
    }, cancel: async ({ sessionId }) => {
      assert.equal(sessionId, 'same')
      notify(current.options, sessionId, 'turn/end', { reason: { kind: 'aborted', reason: { kind: 'user' } } })
      stopping.resolve()
      await idle.promise
      current.resolve({ events: [], finalResponse: '' }) // Models SDK receipt of session.status=idle.
      return { status: 'cancelled', sessionId }
    } })
    const first = app.post('same', undefined, 'round-1')
    await entered.promise
    const cancel = app.request('POST', '/api/chat/cancel', { requestId: 'round-1', sessionId: 'same' })
    await stopping.promise
    assert.equal(cancel.response.writableEnded, false, 'an aborted turn does not yet prove the process stopped')
    const busy = app.post('same', undefined, 'round-2')
    await busy.completion
    assert.equal(busy.response.status, 409)
    const other = app.post('other', undefined, 'parallel')
    await other.completion
    assert.equal(other.response.events().at(-1).event, 'done')
    idle.resolve()
    await Promise.all([cancel.completion, first.completion])
    assert.equal(cancel.response.status, 200)
    assert.equal(JSON.parse(cancel.response.text()).cancelled, true)
    assert.equal(first.response.events().at(-1).event, 'cancelled')
    assert.ok(!first.response.events().some((event) => ['error', 'renamed'].includes(event.event)))
    const next = app.post('same', undefined, 'round-3')
    await next.completion
    assert.equal(next.response.events().at(-1).data.sessionId, 'same')
    assert.equal(next.response.events().at(-1).event, 'done')
    assert.equal(app.calls.closes, 0)
    assert.equal(app.calls.cancels.length, 1)
    const options = profile === 'harness' ? app.calls.projectOptions : app.calls.legacyOptions
    assert.equal(options.length, 1, 'cancellation must retain the live runtime and original session')
  })
}

test('disconnect forwards cancellation instead of leaving a hidden model activity running', { timeout: 2000 }, async () => {
  const entered = deferred()
  let current, runs = 0
  const app = await adapter({ env: { DSH_PROFILE: 'harness' }, run: async (id, _prompt, options) => {
    if (++runs > 1) return { events: [], finalResponse: 'same session' }
    return await new Promise((resolve) => { current = { options, resolve }; notify(options, id, 'step/start'); entered.resolve() })
  }, cancel: async ({ sessionId }) => {
    notify(current.options, sessionId, 'turn/end', { reason: { kind: 'aborted', reason: { kind: 'user' } } })
    current.resolve({ events: [], finalResponse: '' })
    return { status: 'cancelled', sessionId }
  } })
  const first = app.post('same', undefined, 'disconnect-1')
  await entered.promise
  const count = first.response.events().length
  first.response.emit('close')
  await first.completion
  assert.equal(app.calls.cancels.length, 1)
  assert.equal(first.response.events().length, count, 'do not write stale output after disconnect')
  const next = app.post('same', undefined, 'disconnect-2')
  await next.completion
  assert.equal(next.response.events().at(-1).event, 'done')
})

test('an early stop prevents an unregistered first request from starting the SDK', async () => {
  let runs = 0
  const app = await adapter({ env: { DSH_PROFILE: 'harness' }, run: async () => { runs++; return { events: [], finalResponse: 'ok' } } })
  const stop = app.request('POST', '/api/chat/cancel', { requestId: 'early-first' })
  await stop.completion
  const id = JSON.parse(stop.response.text()).sessionId
  const first = app.post(undefined, undefined, 'early-first')
  await first.completion
  assert.equal(first.response.events().at(-1).event, 'cancelled')
  assert.equal(first.response.events().at(-1).data.sessionId, id)
  assert.equal(app.calls.projectOptions.length, 0)
  assert.equal(runs, 0)
  const next = app.post(id, undefined, 'early-followup')
  await next.completion
  assert.equal(next.response.events().at(-1).data.sessionId, id)
  assert.equal(runs, 1)
})

test('late old stop and mismatched session cannot cancel a newer request', { timeout: 2000 }, async () => {
  const entered = deferred()
  let current, runs = 0
  const app = await adapter({ env: { DSH_PROFILE: 'harness' }, run: async (id, _prompt, options) => {
    if (++runs === 1) return { events: [], finalResponse: 'old finished' }
    return await new Promise((resolve) => { current = { resolve }; notify(options, id, 'step/start'); entered.resolve() })
  }, cancel: async ({ sessionId }) => { current.resolve({ events: [], finalResponse: '' }); return { status: 'cancelled', sessionId } } })
  const old = app.post('same', undefined, 'old-request')
  await old.completion
  const currentRun = app.post('same', undefined, 'new-request')
  await entered.promise
  for (const body of [{ requestId: 'old-request', sessionId: 'same' }, { requestId: 'new-request', sessionId: 'different' }]) {
    const stop = app.request('POST', '/api/chat/cancel', body)
    await stop.completion
  }
  assert.equal(app.calls.cancels.length, 0)
  assert.equal(currentRun.response.writableEnded, false)
  const stop = app.request('POST', '/api/chat/cancel', { requestId: 'new-request', sessionId: 'same' })
  await Promise.all([stop.completion, currentRun.completion])
  assert.equal(app.calls.cancels.length, 1)
})

test('cancel waits past enqueue receipt until the current prompt is actually claimed', { timeout: 2000 }, async () => {
  const enqueued = deferred()
  let current
  const app = await adapter({ env: { DSH_PROFILE: 'harness' }, run: async (id, _prompt, options) => await new Promise((resolve) => {
    current = { id, options, resolve }
    notify(options, id, 'agent/inbox/spliced', { inserted: [{ id: 'queued' }], removedCount: 0 })
    enqueued.resolve()
  }), cancel: async ({ sessionId }) => { current.resolve({ events: [], finalResponse: '' }); return { status: 'cancelled', sessionId } } })
  const first = app.post('same', undefined, 'queued-request')
  await enqueued.promise
  const stop = app.request('POST', '/api/chat/cancel', { requestId: 'queued-request' })
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(app.calls.cancels.length, 0, 'idle Agent acknowledgement before queued input executes would be a false stop')
  notify(current.options, current.id, 'agent/inbox/spliced', { inserted: [], removedCount: 1 })
  await Promise.all([stop.completion, first.completion])
  assert.equal(app.calls.cancels.length, 1)
})

test('failed cancellation retains the lock even after model idle until owned jobs can be stopped on retry', { timeout: 2000 }, async () => {
  const entered = deferred()
  let current, attempts = 0, runs = 0
  const app = await adapter({ env: { DSH_PROFILE: 'harness' }, run: async (id, _prompt, options) => {
    if (++runs > 1) return { events: [], finalResponse: 'recovered' }
    return await new Promise((resolve) => { current = { resolve }; notify(options, id, 'step/start'); entered.resolve() })
  }, cancel: async ({ sessionId }) => {
    current.resolve({ events: [], finalResponse: '' })
    if (++attempts === 1) throw new Error('owned background job still running')
    return { status: 'cancelled', sessionId }
  } })
  const first = app.post('same', undefined, 'retry-stop')
  await entered.promise
  const stop = app.request('POST', '/api/chat/cancel', { requestId: 'retry-stop' })
  await stop.completion
  await first.completion
  assert.equal(stop.response.status, 502)
  assert.match(stop.response.text(), /background job still running/)
  assert.equal(first.response.events().at(-1).event, 'error')
  assert.ok(!first.response.events().some((event) => event.event === 'cancelled'), 'model idle alone must not claim all owned jobs stopped')
  const blocked = app.post('same', undefined, 'too-early')
  await blocked.completion
  assert.equal(blocked.response.status, 409)
  const retry = app.request('POST', '/api/chat/cancel', { requestId: 'retry-stop' })
  await retry.completion
  assert.equal(retry.response.status, 200)
  const followup = app.post('same', undefined, 'after-stop')
  await followup.completion
  assert.equal(followup.response.events().at(-1).event, 'done')
})

test('a failed turn with no idle remains cancellable, and cancellation recovers its original session', { timeout: 2000 }, async () => {
  let current, runs = 0
  const app = await adapter({ env: { DSH_PROFILE: 'harness' }, run: async (id, _prompt, options) => {
    if (++runs > 1) return { events: [], finalResponse: 'recovered' }
    return await new Promise((resolve) => { current = { resolve }; notify(options, id, 'turn/end', { reason: { kind: 'error', error: { message: 'provider failure' } } }) })
  }, cancel: async ({ sessionId }) => { current.resolve({ events: [], finalResponse: '' }); return { status: 'cancelled', sessionId } } })
  const first = app.post('same', undefined, 'failed-request')
  await first.completion
  assert.equal(first.response.events().at(-1).event, 'error')
  const stop = app.request('POST', '/api/chat/cancel', { requestId: 'failed-request' })
  await stop.completion
  assert.equal(stop.response.status, 200)
  const next = app.post('same', undefined, 'recover-request')
  await next.completion
  assert.equal(next.response.events().at(-1).data.sessionId, 'same')
  assert.equal(next.response.events().at(-1).event, 'done')
  assert.ok(!next.response.events().some((event) => event.event === 'renamed'))
})

test('stopping image pre-read aborts it before SDK start and leaves the same session usable', { timeout: 2000 }, async () => {
  const entered = deferred()
  const app = await adapter({ env: { DSH_PROFILE: 'harness' }, filesystem: { ...fs, mkdirSync() {}, writeFileSync() {} }, analyze: async (_files, _question, { signal }) => await new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), { once: true })
    entered.resolve()
  }) })
  const first = app.post('same', [{ name: '图.png', data: png, mimeType: 'image/png' }], 'image-request')
  await entered.promise
  const stop = app.request('POST', '/api/chat/cancel', { requestId: 'image-request' })
  await Promise.all([stop.completion, first.completion])
  assert.equal(first.response.events().at(-1).event, 'cancelled')
  assert.equal(app.calls.projectOptions.length, 0, 'cancelled VLM work must not be followed by a model prompt')
  assert.equal(app.calls.cancels.length, 0, 'no Agent exists during image pre-read')
  const next = app.post('same', undefined, 'after-image-stop')
  await next.completion
  assert.equal(next.response.events().at(-1).event, 'done')
})

test('invalid or oversized images are rejected before spool writes or model calls', async () => {
  let writes = 0
  const app = await adapter({ env: { DSH_PROFILE: 'harness' }, filesystem: { ...fs, mkdirSync() {}, writeFileSync() { writes++ } } })
  for (const [attachment, status] of [
    [{ name: 'bad.png', data: Buffer.from('not image bytes').toString('base64'), mimeType: 'image/png' }, 415],
    [{ name: 'wrong.png', data: png, mimeType: 'image/jpeg' }, 415],
    [{ name: 'huge.png', data: Buffer.alloc(5 * 1024 * 1024 + 1).toString('base64'), mimeType: 'image/png' }, 413],
  ]) {
    const request = app.post('same', [attachment])
    await request.completion
    assert.equal(request.response.status, status)
  }
  assert.equal(writes, 0)
  assert.equal(app.calls.images.length, 0)
  assert.equal(app.calls.projectOptions.length, 0)
})

test('native Harness uses project runtime and isolated home; image facts accompany the same user prompt', async () => {
  let receivedPrompt
  const writes = []
  const app = await adapter({
    env: { DSH_PROFILE: 'harness', DSH_HOME_DIR: '.runtime/dsh-home' },
    filesystem: { ...fs, mkdirSync() {}, writeFileSync(file, content) { writes.push({ file, content }) } },
    analyze: async () => '\n上传图片观察：PSD 存在可见峰值。',
    run: async (_id, prompt) => { receivedPrompt = prompt; return { events: [], finalResponse: 'ready' } },
  })
  const chat = app.post('inspection', [{ name: 'sample.png', data: png, mimeType: 'image/png' }])
  await chat.completion
  assert.equal(chat.response.events().at(-1).event, 'done')
  assert.equal(app.calls.legacyOptions.length, 0)
  assert.equal(app.calls.projectOptions.length, 1)
  assert.equal(app.calls.projectOptions[0].home, path.resolve(fileURLToPath(new URL('..', import.meta.url)), '.runtime/web-harness-home'))
  assert.equal(app.calls.patches.length, 0, 'project runtime prepares the Harness profile itself')
  assert.equal(app.calls.images.length, 1)
  assert.equal(app.calls.images[0][1], '分析数据')
  assert.equal(app.calls.images[0][2].signal.aborted, false)
  assert.ok(chat.response.events().some((event) => event.event === 'phase' && event.data.message === '正在解读上传图片'))
  assert.equal(writes.length, 1)
  assert.equal(writes[0].content.toString('base64'), png)
  assert.ok(receivedPrompt.includes(writes[0].file))
  assert.match(receivedPrompt, /vision_inspect/)
  assert.match(receivedPrompt, /上传图片观察：PSD 存在可见峰值/)
  assert.doesNotMatch(receivedPrompt, /kb_ingest/)
  const health = app.request('GET', '/api/health')
  await health.completion
  assert.equal(JSON.parse(health.response.text()).profile, 'harness')
})

test('Harness never proxies knowledge-base or approval interfaces to the old child', async () => {
  const app = await adapter({ env: { DSH_PROFILE: 'harness' }, health: async () => { throw new Error('legacy integration must not run') } })
  const pending = app.request('GET', '/api/approvals/pending')
  await pending.completion
  assert.equal(pending.response.status, 200)
  assert.deepEqual(JSON.parse(pending.response.text()).pending, [])
  for (const [method, route, body] of [
    ['GET', '/api/kb/health'],
    ['POST', '/api/kb/feedback', { rating: 1 }],
    ['POST', '/api/approvals/a/decision', { decision: 'allowed-once' }],
    ['GET', '/api/integrations/health'],
  ]) {
    const result = app.request(method, route, body)
    await result.completion
    assert.equal(result.response.status, 404)
    assert.equal(JSON.parse(result.response.text()).profile, 'harness')
    assert.match(JSON.parse(result.response.text()).error, /未启用/)
  }
  assert.equal(app.calls.proxies.length, 0)
  assert.equal(app.calls.projectOptions.length, 0, 'non-chat routes do not spawn an unrelated runtime')
})

test('rag-kb retains its SDK, attachment preprocessing and child proxy behavior', async () => {
  let receivedPrompt
  const app = await adapter({
    filesystem: { ...fs, mkdirSync() {}, writeFileSync() {} },
    analyze: async () => '\nlegacy visual observation',
    run: async (_id, prompt) => { receivedPrompt = prompt; return { events: [], finalResponse: 'ok' } },
  })
  const chat = app.post('knowledge', [{ name: 'file.png', data: png }])
  await chat.completion
  assert.equal(app.calls.legacyOptions[0].profile, 'rag-kb')
  assert.equal(app.calls.projectOptions.length, 0)
  assert.equal(app.calls.patches.length, 1)
  assert.equal(app.calls.images.length, 1)
  assert.match(receivedPrompt, /kb_ingest/)
  assert.match(receivedPrompt, /legacy visual observation/)
  const pending = app.request('GET', '/api/approvals/pending')
  await pending.completion
  assert.equal(JSON.parse(pending.response.text()).proxied, true)
  const feedback = app.request('POST', '/api/kb/feedback', { rating: 1 })
  await feedback.completion
  assert.equal(JSON.parse(feedback.response.text()).proxied, true)
  assert.deepEqual(app.calls.proxies.map((request) => request.path), ['/approvals/pending', '/kb/feedback'])
})

for (const kind of ['error', 'aborted', 'max-tokens']) {
  test(`Harness root ${kind} ends SSE even when SDK does not emit idle`, { timeout: 2000 }, async () => {
    const app = await adapter({ env: { DSH_PROFILE: 'harness' }, run: async (id, _prompt, options) => {
      options.onNotification({ method: 'session.event', params: { sessionId: id, event: { type: 'turn/end', data: { reason: { kind } } } } })
      return new Promise(() => {})
    } })
    const chat = app.post('failed')
    await chat.completion
    assert.equal(chat.response.writableEnded, true)
    assert.equal(chat.response.events().at(-1).event, 'error')
    assert.ok(!chat.response.events().some((event) => event.event === 'done'))
    assert.match(chat.response.events().at(-1).data.message, new RegExp(kind))
    assert.equal(app.calls.closes, 0, 'must not kill unrelated sessions in the shared runtime')
    const retry = app.post('failed')
    await retry.completion
    assert.equal(retry.response.status, 409)
    assert.match(retry.response.text(), /上一条消息/, 'unfinished SDK activity retains its lock and cancellation handle')
  })
}

test('a child failure does not terminate the Harness root or another concurrent session', { timeout: 2000 }, async () => {
  const entered = deferred(), ready = deferred()
  const app = await adapter({ env: { DSH_PROFILE: 'harness' }, run: async (id, _prompt, options) => {
    if (id === 'other') { entered.resolve(); await ready.promise }
    options.onNotification({ method: 'session.event', params: { sessionId: id === 'failed' ? id : `${id}-child`,
      event: { type: 'turn/end', data: { reason: { kind: 'error', error: { message: 'child failed' } } } } } })
    if (id === 'failed') return new Promise(() => {})
    return { events: [], finalResponse: 'root still succeeds' }
  } })
  const other = app.post('other')
  try {
    await entered.promise
    const failed = app.post('failed')
    await failed.completion
    assert.equal(failed.response.events().at(-1).event, 'error')
  } finally { ready.resolve(); await other.completion }
  assert.equal(other.response.events().at(-1).event, 'done')
  assert.equal(app.calls.closes, 0)
})

function storedHistoryFilesystem(events, { unreadable = false } = {}) {
  return {
    ...fs,
    readdirSync() { return ['stored-workspace'] },
    statSync() { return { isDirectory: () => true } },
    existsSync(file) { return file.endsWith('/old/session.v3.jsonl') },
    readFileSync() {
      if (unreadable) throw new Error('history unavailable')
      return events.map((event) => JSON.stringify(event)).join('\n')
    },
  }
}

function toolHistoryEvents(cases) {
  return cases.flatMap(({ name = 'bash', command = 'python unrelated.py', text, isError = false }, index) => [
    { type: 'tool/call', seq: index * 2, data: { name, callId: `call-${index}`, arguments: JSON.stringify(name === 'bash' ? { command, description: 'Run inspection' } : { job_id: 'unknown-origin' }) } },
    { type: 'tool/result', seq: index * 2 + 1, data: { message: { content: [{ type: 'tool-result', toolCallId: `call-${index}`, isError, content: [{ type: 'text', text }] }] } } },
  ])
}

test('history preserves terminal failure and known Skill partial status before truncating long output', async () => {
  const cases = [
    { text: 'many output lines\n' + 'x'.repeat(5000) + '\n[exit code: 1]', status: 'error' },
    { command: '"/workspace with spaces/.venv/bin/python" -I "skills/underwater-data-inspection/scripts/inspect_data.py" execute --out .run/check', text: 'bounded results\n[exit code: 2]', status: 'partial' },
    { command: 'python3 skills/underwater-data-inspection/scripts/inspect_data.py probe input', text: 'metadata required\n[exit code: 2]', isError: true, status: 'error' },
    { text: 'slow command\n[timed out after 300000ms]\n[killed by signal: SIGTERM]', status: 'error' },
    { name: 'job_output', text: 'partial producer output\n[status: completed, exit code: 2]', status: 'error' },
    { name: 'job_output', text: 'finished background work\n[status: completed, exit code: 0]', status: 'done' },
  ]
  const app = await adapter({ filesystem: storedHistoryFilesystem(toolHistoryEvents(cases)) })
  const history = app.request('GET', '/api/chat/history?sessionId=old')
  await history.completion
  assert.equal(history.response.status, 200)
  const cards = JSON.parse(history.response.text()).events
  assert.deepEqual(cards.map((card) => card.status), cases.map((entry) => entry.status))
  assert.equal(cards[0].resultText.length, 4000)
  assert.doesNotMatch(cards[0].resultText, /exit code/, 'the status must survive even though its original evidence is beyond the display cap')
  assert.equal(cards[1].callId, 'call-1')
})

test('history does not infer Skill partial success from quoted text, arbitrary scripts or nonterminal body markers', async () => {
  const cases = [
    { command: 'echo "python inspect_data.py run"', text: 'other command failed\n[exit code: 2]', status: 'error' },
    { command: 'python -c "print(\"inspect_data.py probe\")"', text: 'other command failed\n[exit code: 2]', status: 'error' },
    { command: 'python inspect_data.py run input; python unrelated.py', text: 'later command failed\n[exit code: 2]', status: 'error' },
    { command: 'python inspect_data.py run input', text: 'documentation example: [exit code: 2]\nordinary error measurement is zero\nfinished successfully', status: 'done' },
    { name: 'read', text: 'Document ends with an example marker\n[exit code: 2]', status: 'done' },
    { command: 'python inspect_data.py probe input', text: 'missing metadata\n[exit code: 2]', status: 'partial' },
    { command: 'python inspect_data.py run input', text: 'limited analysis\n[exit code: 2]', status: 'partial' },
  ]
  const app = await adapter({ filesystem: storedHistoryFilesystem(toolHistoryEvents(cases)) })
  const history = app.request('GET', '/api/chat/history?sessionId=old')
  await history.completion
  assert.deepEqual(JSON.parse(history.response.text()).events.map((card) => card.status), cases.map((entry) => entry.status))
})

test('already-existing session migrates bounded text context and keeps the current request last', async () => {
  let migratedPrompt
  const events = []
  for (let i = 0; i < 6; i++) {
    events.push({ type: 'user/message', seq: i * 2, data: { source: { kind: 'user' }, content: [{ type: 'text', text: `past user ${i}` }] } })
    events.push({ type: 'assistant/message', seq: i * 2 + 1, data: { message: { content: [
      { type: 'reasoning', text: 'PRIVATE_REASONING_MARKER' }, { type: 'text', text: `past answer ${i}; results saved under .run/completed-analysis/` },
    ] } } })
  }
  events.push({ type: 'tool/call', seq: 12, data: { name: 'bash', callId: 'c', arguments: 'TOOL_ONLY_MARKER' } })
  events.push({ type: 'tool/result', seq: 13, data: { message: { content: [{ type: 'tool-result', toolCallId: 'c', content: [{ type: 'text', text: 'TOOL_RESULT_MARKER' }] }] } } })
  events.push({ type: 'user/message', seq: 14, data: { source: { kind: 'plugin' }, content: [{ type: 'text', text: 'PLUGIN_ONLY_MARKER' }] } })
  const app = await adapter({ env: { DSH_PROFILE: 'harness' }, filesystem: storedHistoryFilesystem(events), run: async (id, prompt) => {
    if (id === 'old') throw new Error('session already exists')
    migratedPrompt = prompt
    return { events: [], finalResponse: 'context retained' }
  } })
  const chat = app.request('POST', '/api/chat/stream', { sessionId: 'old', message: '只解释 dtype，不重新分析数据' })
  await chat.completion
  assert.equal(chat.response.events().at(-1).event, 'done')
  assert.ok(chat.response.events().some((event) => event.event === 'renamed'))
  assert.match(migratedPrompt, /上下文迁移/)
  assert.match(migratedPrompt, /不要重复历史任务/)
  assert.match(migratedPrompt, /past answer 5/)
  assert.match(migratedPrompt, /\.run\/completed-analysis\//)
  assert.doesNotMatch(migratedPrompt, /past user 0|past answer 0|PRIVATE_REASONING_MARKER|TOOL_ONLY_MARKER|TOOL_RESULT_MARKER|PLUGIN_ONLY_MARKER/)
  assert.ok(migratedPrompt.endsWith('本轮用户请求：\n只解释 dtype，不重新分析数据'))
  const background = JSON.parse(migratedPrompt.split('<conversation_background>\n')[1].split('\n</conversation_background>')[0])
  assert.equal(background.sourceSessionId, 'old')
  assert.equal(background.messages.length, 8)
})

test('migrated conversation text has a 24000-character total cap', async () => {
  let migratedPrompt
  const events = [{ type: 'assistant/message', data: { message: { content: [{ type: 'text', text: 'OLD_PREFIX' + 'x'.repeat(30000) + 'LATEST_CONTEXT' }] } } }]
  const app = await adapter({ filesystem: storedHistoryFilesystem(events), run: async (id, prompt) => {
    if (id === 'old') throw new Error('session already exists')
    migratedPrompt = prompt
    return { events: [], finalResponse: 'ok' }
  } })
  const chat = app.post('old')
  await chat.completion
  const background = JSON.parse(migratedPrompt.split('<conversation_background>\n')[1].split('\n</conversation_background>')[0])
  assert.equal(background.messages.reduce((total, message) => total + message.text.length, 0), 24000)
  assert.match(migratedPrompt, /LATEST_CONTEXT/)
  assert.doesNotMatch(migratedPrompt, /OLD_PREFIX/)
})

test('unreadable stored history does not block session migration or alter the current request', async () => {
  let migratedPrompt
  const app = await adapter({ filesystem: storedHistoryFilesystem([], { unreadable: true }), run: async (id, prompt) => {
    if (id === 'old') throw new Error('session already exists')
    migratedPrompt = prompt
    return { events: [], finalResponse: 'ok' }
  } })
  const chat = app.post('old')
  await chat.completion
  assert.equal(chat.response.events().at(-1).event, 'done')
  assert.equal(migratedPrompt, '分析数据')
})
