import assert from 'node:assert/strict'
import test from 'node:test'
import { streamChat } from '../../frontend/src/lib/api.js'

const encoder = new TextEncoder()
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function receive(fetcher, action) {
  const previous = globalThis.fetch
  globalThis.fetch = fetcher
  const events = []
  let complete, timeout
  const terminal = new Promise((resolve) => { complete = resolve })
  try {
    const abort = streamChat({ sessionId: 's', message: '分析数据' }, {
      onStart: (id) => events.push(['start', id]),
      onNotification: (data) => events.push(['notification', data]),
      onDone: (data) => { events.push(['done', data]); complete() },
      onError: (message) => { events.push(['error', message]); complete() },
    })
    if (action) await action(abort)
    else await Promise.race([
      terminal,
      new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error('stream never settled')), 1000) }),
    ])
    await sleep(5) // 同一块内重复终态或终态之后的 EOF 不应再次回调
    return events
  } finally { clearTimeout(timeout); globalThis.fetch = previous }
}

function response(chunks) {
  return new Response(new ReadableStream({ start(controller) {
    for (const chunk of chunks) controller.enqueue(typeof chunk === 'string' ? encoder.encode(chunk) : chunk)
    controller.close()
  } }))
}

test('EOF without done/error becomes one explicit error', async () => {
  const events = await receive(async () => response(['event: start\ndata: {"sessionId":"s"}\n\n']))
  assert.deepEqual(events.map(([type]) => type), ['start', 'error'])
  assert.match(events.at(-1)[1], /未收到完成状态/)
})

test('split UTF-8, CRLF and final block without blank line parse correctly', async () => {
  const bytes = encoder.encode('event: start\r\ndata: {"sessionId":"s"}\r\n\r\nevent: notification\r\ndata: {"text":"声学数据"}\r\n\r\nevent: done\r\ndata: {"finalResponse":"完成"}')
  const events = await receive(async () => response(Array.from(bytes, (byte) => new Uint8Array([byte]))))
  assert.deepEqual(events.map(([type]) => type), ['start', 'notification', 'done'])
  assert.equal(events[1][1].text, '声学数据')
  assert.equal(events[2][1].finalResponse, '完成')
})

test('only the first terminal event is delivered', async () => {
  const events = await receive(async () => response(['event: error\ndata: {"message":"算法失败"}\n\nevent: done\ndata: {}\n\nevent: error\ndata: {}\n\n']))
  assert.deepEqual(events, [['error', '算法失败']])
})

test('done settles immediately even if the server keeps the stream open', async () => {
  let cancelled = false
  const events = await receive(async () => new Response(new ReadableStream({
    start(controller) { controller.enqueue(encoder.encode('event: done\ndata: {}\n\n')) },
    cancel() { cancelled = true },
  })))
  assert.deepEqual(events, [['done', {}]])
  assert.equal(cancelled, true)
})

test('read failure becomes one explicit stream error', async () => {
  const events = await receive(async () => new Response(new ReadableStream({
    pull(controller) { controller.error(new Error('broken connection')) },
  })))
  assert.equal(events.length, 1)
  assert.match(events[0][1], /流中断.*broken connection/)
})

test('HTTP error detail is preserved', async () => {
  const events = await receive(async () => new Response('{"error":"会话忙"}', { status: 409 }))
  assert.deepEqual(events, [['error', '会话忙']])
})

test('intentional abort before headers does not call a stale UI handler', async () => {
  const events = await receive((_, { signal }) => new Promise((_, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
  }), async (abort) => { abort(); await sleep(5) })
  assert.deepEqual(events, [])
})

test('intentional abort during streaming releases the reader without a stale UI error', async () => {
  let body
  const events = await receive(async (_, { signal }) => {
    body = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('event: start\ndata: {"sessionId":"s"}\n\n'))
        signal.addEventListener('abort', () => controller.error(new DOMException('aborted', 'AbortError')), { once: true })
      },
    })
    return new Response(body)
  }, async (abort) => { await sleep(5); abort() })
  assert.deepEqual(events, [['start', 's']])
  assert.equal(body.locked, false)
})
