/** Read-only, bounded presentation of generated workspace artifacts. */
import fs from 'node:fs/promises'
import { constants } from 'node:fs'
import path from 'node:path'
import { pipeline } from 'node:stream/promises'

const ROOTS = new Set(['.run', 'tasks', 'output'])
const MAX_DIRECTORY_ENTRIES = 300
const TEXT_PREVIEW_BYTES = 2 * 1024 * 1024
const FORMATS = {
  '.md': ['text/markdown; charset=utf-8', 'markdown'],
  '.markdown': ['text/markdown; charset=utf-8', 'markdown'],
  '.txt': ['text/plain; charset=utf-8', 'text'],
  '.csv': ['text/csv; charset=utf-8', 'text'],
  '.tsv': ['text/tab-separated-values; charset=utf-8', 'text'],
  '.json': ['application/json; charset=utf-8', 'text'],
  '.png': ['image/png', 'image'], '.jpg': ['image/jpeg', 'image'],
  '.jpeg': ['image/jpeg', 'image'], '.webp': ['image/webp', 'image'],
  '.gif': ['image/gif', 'image'], '.pdf': ['application/pdf', 'pdf'],
  '.npz': ['application/octet-stream', 'download'],
  '.npy': ['application/octet-stream', 'download'],
  '.html': ['application/octet-stream', 'download'],
  '.htm': ['application/octet-stream', 'download'],
}
const PRIVATE_NAMES = /^(?:credentials?|secrets?|tokens?|id_rsa|id_ed25519)(?:\.|$)/i
const PRIVATE_DIRECTORIES = new Set(['backend', 'node_modules', '__pycache__'])

function fail(status, message) { throw Object.assign(new Error(message), { status }) }

function validateRelative(relative) {
  const pieces = relative.split('/')
  if (!ROOTS.has(pieces[0])) fail(403, '仅可读取工作区内 .run、tasks、output 中的产物')
  if (pieces.some((piece, index) => index > 0 && (piece.startsWith('.') || PRIVATE_NAMES.test(piece)
    || PRIVATE_DIRECTORIES.has(piece)))) fail(403, '该路径不属于可展示的产物')
}

/** Both lexical and resolved paths must remain inside an allowed generated root. */
async function resolveArtifact(workspaceRoot, requested) {
  if (!requested || requested.length > 4096 || /[\\\x00-\x1f\x7f]/.test(requested)) fail(400, 'path 必须是有效的工作区产物路径')
  if (requested.split('/').some((part) => part === '..' || part === '.')) fail(400, '路径不能包含遍历片段')
  const workspace = path.resolve(workspaceRoot)
  const trimmed = requested.replace(/\/+$/, '')
  const relative = path.isAbsolute(trimmed) ? path.relative(workspace, trimmed).split(path.sep).join('/') : trimmed
  validateRelative(relative)
  const candidate = path.resolve(workspace, relative)
  const realWorkspace = await fs.realpath(workspace)
  const realPath = await fs.realpath(candidate)
  const realRelative = path.relative(realWorkspace, realPath).split(path.sep).join('/')
  validateRelative(realRelative)
  const stat = await fs.stat(realPath)
  if (!stat.isFile() && !stat.isDirectory()) fail(403, '仅支持普通产物文件和目录')
  if (stat.isFile() && stat.nlink > 1) fail(403, '不展示具有额外硬链接的文件')
  if (stat.isFile() && !FORMATS[path.extname(realPath).toLowerCase()]) fail(403, '该文件格式不支持展示或下载')
  return { relative, realPath, realWorkspace, stat }
}

function metadata(artifact) {
  const { relative, realPath, stat } = artifact
  const base = { kind: stat.isDirectory() ? 'directory' : 'file', path: relative,
    name: path.posix.basename(relative), modifiedAt: stat.mtime.toISOString() }
  if (stat.isDirectory()) return base
  const [mimeType, kind] = FORMATS[path.extname(realPath).toLowerCase()]
  const preview = ['markdown', 'text'].includes(kind) && stat.size > TEXT_PREVIEW_BYTES ? 'download' : kind
  const fileUrl = '/api/artifacts/file?' + new URLSearchParams({ path: relative })
  return { ...base, sizeBytes: stat.size, mimeType, preview, fileUrl, downloadUrl: fileUrl + '&download=1' }
}

function json(req, res, status, value) {
  const text = JSON.stringify(value)
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(text), 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' })
  res.end(req.method === 'HEAD' ? undefined : text)
}

function disposition(name, download) {
  const fallback = name.replace(/[^\x20-\x7e]|["\\]/g, '_')
  const encoded = encodeURIComponent(name).replace(/[!'()*]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase())
  return `${download ? 'attachment' : 'inline'}; filename="${fallback}"; filename*=UTF-8''${encoded}`
}

/** Used by the real HTTP adapter and contract tests; never starts a Harness. */
export async function handleArtifactRequest(req, res, { workspaceRoot }) {
  const url = new URL(req.url || '/', 'http://localhost')
  if (!['/api/artifacts', '/api/artifacts/file'].includes(url.pathname)) return false
  if (!['GET', 'HEAD'].includes(req.method)) {
    res.setHeader('allow', 'GET, HEAD')
    json(req, res, 405, { ok: false, error: '产物接口仅支持读取' })
    return true
  }
  let handle
  try {
    if (url.searchParams.getAll('path').length !== 1) fail(400, '请提供唯一的 path 参数')
    const artifact = await resolveArtifact(workspaceRoot, url.searchParams.get('path'))
    const info = metadata(artifact)
    if (url.pathname === '/api/artifacts') {
      if (info.kind === 'directory') {
        const children = await fs.readdir(artifact.realPath, { withFileTypes: true })
        children.sort((a, b) => Number(b.isDirectory()) - Number(a.isDirectory()) || a.name.localeCompare(b.name, 'zh-CN'))
        const entries = []
        let truncated = false
        for (const child of children) {
          try {
            const resolved = await resolveArtifact(workspaceRoot, path.posix.join(artifact.relative, child.name))
            if (entries.length === MAX_DIRECTORY_ENTRIES) { truncated = true; break }
            entries.push(metadata(resolved))
          } catch (error) {
            if (![400, 403, 404].includes(error.status) && !['ENOENT', 'ENOTDIR', 'ELOOP', 'EACCES'].includes(error.code)) throw error
          }
        }
        const parent = path.posix.dirname(info.path)
        json(req, res, 200, { ok: true, ...info, parentPath: ROOTS.has(info.path) ? null : parent,
          entries, truncated, maxEntries: MAX_DIRECTORY_ENTRIES })
        return true
      }
      json(req, res, 200, { ok: true, ...info })
      return true
    }
    if (info.kind !== 'file') fail(400, '请先打开目录并选择一个文件')
    // Use the resolved filename and refuse a replaced final symlink or FIFO.
    handle = await fs.open(artifact.realPath, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK)
    const opened = await handle.stat()
    const current = await resolveArtifact(workspaceRoot, artifact.relative)
    if (!opened.isFile() || opened.dev !== artifact.stat.dev || opened.ino !== artifact.stat.ino
      || current.realPath !== artifact.realPath || current.stat.dev !== opened.dev || current.stat.ino !== opened.ino
      || opened.nlink > 1) fail(409, '产物在读取前发生变化，请重新打开')
    const download = url.searchParams.get('download') === '1' || info.preview === 'download'
    res.writeHead(200, { 'content-type': info.mimeType, 'content-length': opened.size,
      'content-disposition': disposition(info.name, download), 'cache-control': 'no-store',
      'x-content-type-options': 'nosniff', 'content-security-policy': "default-src 'none'; sandbox" })
    if (req.method === 'HEAD' || opened.size === 0) res.end()
    else await pipeline(handle.createReadStream({ autoClose: false, start: 0, end: opened.size - 1 }), res)
  } catch (error) {
    if (!res.headersSent) {
      const status = error.status || ({ ENOENT: 404, ENOTDIR: 404, ELOOP: 403, EACCES: 403 }[error.code]) || 500
      const message = error.status ? error.message : status === 404 ? '产物不存在' : status === 403 ? '无法访问该产物' : '读取产物失败'
      json(req, res, status, { ok: false, error: message })
    } else if (!res.writableEnded) res.destroy()
  } finally { await handle?.close().catch(() => {}) }
  return true
}
