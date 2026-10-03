import { createServer } from 'node:http'
import { timingSafeEqual } from 'node:crypto'
import { setTimeout as delay } from 'node:timers/promises'
import z from '@deepseek-ai/schemastery'

export const name = 'ocean-harness-control'
export const inject = ['agents', 'jobs']
export const Config = z.object({ timeoutMs: z.number().step(1).min(1).max(60000).default(30000) })

export class ControlError extends Error {
  constructor(statusCode, code, message) {
    super(message)
    this.statusCode = statusCode
    this.code = code
  }
}

export function environmentConfig(env = process.env, options = {}) {
  const port = Number(env.HARNESS_CONTROL_PORT)
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) throw new Error('HARNESS_CONTROL_PORT must be an integer between 1 and 65535')
  const token = env.HARNESS_CONTROL_TOKEN
  if (typeof token !== 'string' || !token.trim() || /\s/.test(token)) throw new Error('HARNESS_CONTROL_TOKEN must be a non-empty bearer token without whitespace')
  const timeoutMs = options.timeoutMs ?? 30000
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 60000) throw new Error('harness-control timeoutMs must be an integer between 1 and 60000')
  return { port, token, timeoutMs }
}

const live = status => status === 'running' || status === 'stopping'

/** Runtime ownership, rather than durable parentSession lineage, is the fence. */
function extendTree(agents, members) {
  const candidates = agents.list()
  let changed
  do {
    changed = false
    for (const candidate of candidates) {
      if (members.has(candidate)) continue
      if ([...members].some(owner => agents.isOwnedBy(candidate.id, owner))) {
        members.add(candidate)
        changed = true
      }
    }
  } while (changed)
}

function rejectReplacements(agents, members) {
  for (const member of members) {
    const current = agents.get(member.id)
    if (current !== undefined && current !== member) throw new ControlError(409, 'session_replaced', 'A requested live session was replaced during cancellation')
  }
}

async function beforeDeadline(promise, deadline, shutdown) {
  let timer
  let fail
  const boundary = new Promise((_resolve, reject) => {
    fail = () => reject(new ControlError(503, 'service_stopping', 'Cancellation bridge is stopping'))
    timer = setTimeout(() => reject(new ControlError(504, 'cancel_timeout', 'Session cancellation did not reach quiescence before the deadline')), Math.max(1, deadline - Date.now()))
    shutdown.addEventListener('abort', fail, { once: true })
    if (shutdown.aborted) fail()
  })
  try { return await Promise.race([promise, boundary]) }
  finally { clearTimeout(timer); shutdown.removeEventListener('abort', fail) }
}

/** Cancel only this live Agent and its actual owned tree; retain all inboxes. */
export async function cancelSessionTree(ctx, target, { timeoutMs, shutdown }) {
  const deadline = Date.now() + timeoutMs
  const members = new Set([target])
  const cancelledAgents = new Set()
  const cancelledJobs = new Set()
  let hadRunningWork = false
  let stablePasses = 0
  while (stablePasses < 2) {
    if (shutdown.aborted) throw new ControlError(503, 'service_stopping', 'Cancellation bridge is stopping')
    if (Date.now() >= deadline) throw new ControlError(504, 'cancel_timeout', 'Session cancellation did not reach quiescence before the deadline')
    const replacement = ctx.agents.get(target.id)
    if (replacement !== undefined && replacement !== target) throw new ControlError(409, 'session_replaced', 'The requested live session was replaced during cancellation')
    extendTree(ctx.agents, members)
    rejectReplacements(ctx.agents, members)
    const previousCount = cancelledAgents.size + cancelledJobs.size
    for (const agent of members) {
      if (cancelledAgents.has(agent)) continue
      hadRunningWork ||= agent.status === 'running'
      // Cancel a known exact object, never a replacement sharing its id.
      agent.cancel({ kind: 'user' }, { keepInbox: true })
      cancelledAgents.add(agent)
    }
    const waits = [...members].map(agent => agent.whenIdle())
    for (const agent of members) {
      for (const job of ctx.jobs.list(agent)) {
        // list() also exposes unowned jobs. They must remain untouched.
        if (job.ownerSession !== agent.id || !live(job.status)) continue
        hadRunningWork = true
        if (!cancelledJobs.has(job.id)) {
          if (job.status === 'running') ctx.jobs.kill(job.id, agent, 'user cancelled session')
          cancelledJobs.add(job.id)
        }
        waits.push(ctx.jobs.wait(job.id, Math.max(1, deadline - Date.now()), agent).then(snapshot => {
          if (live(snapshot.status)) throw new ControlError(504, 'cancel_timeout', 'A session-owned background job is still stopping')
        }))
      }
    }
    await beforeDeadline(Promise.all(waits), deadline, shutdown)
    rejectReplacements(ctx.agents, members)
    const active = [...members].some(agent => agent.status !== 'idle' || ctx.jobs.list(agent).some(job => job.ownerSession === agent.id && live(job.status)))
    stablePasses = !active && previousCount === cancelledAgents.size + cancelledJobs.size ? stablePasses + 1 : 0
    if (stablePasses < 2) await delay(10, undefined, { signal: shutdown }).catch(() => {
      throw new ControlError(503, 'service_stopping', 'Cancellation bridge is stopping')
    })
  }
  return {
    ok: true, status: hadRunningWork ? 'cancelled' : 'idle', sessionId: target.id, agentStatus: 'idle',
    cancelledSessionIds: [...cancelledAgents].map(agent => agent.id), cancelledJobIds: [...cancelledJobs],
  }
}

function json(res, status, value) {
  if (res.destroyed || res.writableEnded) return
  const body = JSON.stringify(value)
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'content-length': Buffer.byteLength(body), 'cache-control': 'no-store' })
  res.end(body)
}

async function bodyOf(req) {
  const chunks = []
  let size = 0
  for await (const chunk of req) {
    size += chunk.length
    if (size > 16384) throw new ControlError(413, 'invalid_request', 'Request body is too large')
    chunks.push(chunk)
  }
  let body
  try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')) }
  catch { throw new ControlError(400, 'invalid_request', 'Request body must be valid JSON') }
  if (!body || Array.isArray(body) || typeof body !== 'object' || Object.keys(body).some(key => key !== 'sessionId') || typeof body.sessionId !== 'string' || !body.sessionId.trim() || body.sessionId.length > 512) {
    throw new ControlError(400, 'invalid_request', 'Request must contain only a non-empty sessionId string')
  }
  return body
}

/** Start a private loopback listener. The token is never returned or logged. */
export async function startControlServer(ctx, config) {
  const expected = Buffer.from(`Bearer ${config.token}`)
  const shutdown = new AbortController()
  const pending = new Map()
  const server = createServer(async (req, res) => {
    try {
      const supplied = Buffer.from(typeof req.headers.authorization === 'string' ? req.headers.authorization : '')
      if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) throw new ControlError(401, 'unauthorized', 'A valid cancellation bridge bearer token is required')
      if (req.url !== '/cancel') throw new ControlError(404, 'not_found', 'Cancellation route not found')
      if (req.method !== 'POST') throw new ControlError(405, 'method_not_allowed', 'Cancellation requires POST')
      if (!/^application\/json(?:\s*;|$)/i.test(req.headers['content-type'] || '')) throw new ControlError(415, 'invalid_request', 'Content-Type must be application/json')
      const { sessionId } = await bodyOf(req)
      const target = ctx.agents.get(sessionId)
      if (!target) throw new ControlError(404, 'session_not_found', 'The requested session is not attached')
      let operation = pending.get(target)
      if (!operation) {
        operation = cancelSessionTree(ctx, target, { timeoutMs: config.timeoutMs, shutdown: shutdown.signal }).finally(() => pending.delete(target))
        pending.set(target, operation)
      }
      json(res, 200, await operation)
    } catch (error) {
      const known = error instanceof ControlError
      json(res, known ? error.statusCode : 500, { ok: false, status: known ? error.code : 'cancel_failed', error: known ? error.message : 'Session cancellation failed to reach quiescence' })
    }
  })
  server.requestTimeout = 5000
  server.headersTimeout = 5000
  server.keepAliveTimeout = 1000
  let closed
  const close = () => closed ??= (async () => {
    shutdown.abort()
    server.closeAllConnections()
    await new Promise((resolve, reject) => server.close(error => error && error.code !== 'ERR_SERVER_NOT_RUNNING' ? reject(error) : resolve()))
  })()
  // Register teardown before listen, including startup failures.
  ctx.effect(() => close, 'harness-control.listener()')
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(config.port, '127.0.0.1', () => { server.removeListener('error', reject); resolve() })
  })
  return { server, close }
}

export async function apply(ctx, options = {}) {
  await startControlServer(ctx, environmentConfig(process.env, options))
}
