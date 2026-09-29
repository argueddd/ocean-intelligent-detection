/**
 * dsh-lightrag → dsh-knowledge · HTTP helpers for webServer routes.
 * Plain Node ESM, zero dependencies.
 */

export function readBody(req, maxBytes = 100 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0
    const chunks = []
    req.on('data', (chunk) => {
      size += chunk.length
      if (size > maxBytes) {
        const err = new Error('body too large (max ' + maxBytes + ' bytes)')
        err.status = 413
        reject(err)
        try { req.destroy() } catch (e) {}
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => resolve(Buffer.concat(chunks)))
    req.on('error', reject)
  })
}

export async function readJsonBody(req, maxBytes) {
  const buf = await readBody(req, maxBytes)
  try {
    return JSON.parse(buf.toString('utf8') || '{}')
  } catch (e) {
    return {}
  }
}

export function json(res, code, obj) {
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-cache',
  })
  res.end(JSON.stringify(obj))
}

export function queryParams(req) {
  const out = {}
  const url = new URL(req.url || '/', 'http://x')
  for (const [k, v] of url.searchParams.entries()) out[k] = v
  return out
}

export function err(res, e, code) {
  const status = (e && e.status) || code || 500
  json(res, status, { ok: false, error: String(e && e.message ? e.message : e) })
}
