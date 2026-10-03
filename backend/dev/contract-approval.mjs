import assert from 'node:assert/strict'
import { getEventListeners } from 'node:events'
import { Readable } from 'node:stream'
import test from 'node:test'
import { apply } from '../dsh/plugin-approval-bridge/lib/index.js'

function bridge(timeoutMs = 1000) {
  const previous = process.env.KB_APPROVAL_TIMEOUT_MS
  process.env.KB_APPROVAL_TIMEOUT_MS = String(timeoutMs)
  let request, route
  const disposers = []
  apply({
    logger: { info() {} },
    on(event, handler) { if (event === 'approval/request') request = handler },
    effect(fn) { disposers.push(fn()) },
    webServer: { register({ handler }) { route = handler; return () => {} } },
  })
  return {
    request,
    async http(method, url, body) {
      const req = Readable.from(body ? [Buffer.from(JSON.stringify(body))] : [])
      req.method = method
      req.url = url
      return new Promise((resolve) => {
        let status
        route(req, {
          writeHead(code) { status = code },
          end(text) { resolve({ status, body: JSON.parse(text) }) },
        })
      })
    },
    dispose() {
      for (const fn of disposers.reverse()) fn?.()
      if (previous === undefined) delete process.env.KB_APPROVAL_TIMEOUT_MS
      else process.env.KB_APPROVAL_TIMEOUT_MS = previous
    },
  }
}

async function bounded(promise) {
  let timer
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('approval did not settle')), 1500) }),
    ])
  } finally { clearTimeout(timer) }
}

test('approval timeout delegates once and removes abort listener', async () => {
  const b = bridge(25)
  const controller = new AbortController()
  let fallback = 0
  try {
    const result = b.request({ toolName: 'kb_ingest', signal: controller.signal }, () => { fallback++; return 'unavailable' })
    assert.equal((await b.http('GET', '/approvals/pending')).body.pending.length, 1)
    assert.equal(await bounded(result), 'unavailable')
    assert.equal(fallback, 1)
    assert.equal(getEventListeners(controller.signal, 'abort').length, 0)
    controller.abort()
    assert.equal((await b.http('GET', '/approvals/pending')).body.pending.length, 0)
  } finally { b.dispose() }
})

test('approval abort settles as cancelled without delegating', async () => {
  const b = bridge()
  const controller = new AbortController()
  try {
    const result = b.request({ toolName: 'kb_update', signal: controller.signal }, () => assert.fail('must not delegate'))
    controller.abort()
    assert.equal(await bounded(result), 'cancelled')
    assert.equal(getEventListeners(controller.signal, 'abort').length, 0)
    assert.equal((await b.http('GET', '/approvals/pending')).body.pending.length, 0)
    assert.equal(await b.request({ signal: controller.signal }, () => assert.fail()), 'cancelled')
  } finally { b.dispose() }
})

test('approval decision settles once; a repeated decision returns 404', async () => {
  const b = bridge()
  const controller = new AbortController()
  try {
    const result = b.request({ toolName: 'kb_delete_doc', signal: controller.signal }, () => assert.fail('must not delegate'))
    const [{ id }] = (await b.http('GET', '/approvals/pending')).body.pending
    assert.equal((await b.http('POST', `/approvals/${id}/decision`, { decision: 'invalid' })).status, 400)
    assert.equal((await b.http('POST', `/approvals/${id}/decision`, { decision: 'allowed-once' })).status, 200)
    assert.equal(await bounded(result), 'allowed-once')
    assert.equal(getEventListeners(controller.signal, 'abort').length, 0)
    controller.abort()
    assert.equal((await b.http('POST', `/approvals/${id}/decision`, { decision: 'rejected' })).status, 404)
  } finally { b.dispose() }
})

test('unloading bridge settles all pending approvals and cleans listeners', async () => {
  const b = bridge()
  const controller = new AbortController()
  let fallback = 0
  const requests = [1, 2].map(() => b.request({ toolName: 'kb_ingest', signal: controller.signal }, () => { fallback++; return 'unavailable' }))
  b.dispose()
  assert.deepEqual(await bounded(Promise.all(requests)), ['unavailable', 'unavailable'])
  assert.equal(fallback, 2)
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0)
})
