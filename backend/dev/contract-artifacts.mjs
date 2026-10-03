/** Real HTTP + filesystem contract; generated fixtures, no model or Harness process. */
import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import test, { before, after } from 'node:test'
import { handleArtifactRequest } from '../artifacts.js'

let workspace, outside, server, base
const reportPath = '.run/海试报告 with space/分析摘要.md'
const markdown = '# 数据分析\n\n已检查 128 个样本。\n\n![频谱](psd.png)\n\n<script>window.forbidden = true</script>\n'
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jvRcAAAAASUVORK5CYII=', 'base64')
const npz = Buffer.from('PK\x03\x04generated-numeric-product\0\x01\xff', 'latin1')
const request = (relative, { raw = false, download = false, method = 'GET' } = {}) => {
  const query = new URLSearchParams({ path: relative })
  if (download) query.set('download', '1')
  return fetch(`${base}/api/artifacts${raw ? '/file' : ''}?${query}`, { method })
}

before(async () => {
  workspace = await fs.mkdtemp(path.join(os.tmpdir(), 'artifact-workspace-'))
  outside = await fs.mkdtemp(path.join(os.tmpdir(), 'artifact-private-'))
  const dir = path.join(workspace, '.run/海试报告 with space')
  await fs.mkdir(dir, { recursive: true })
  await fs.mkdir(path.join(workspace, 'tasks/job-a'), { recursive: true })
  await fs.mkdir(path.join(workspace, 'output'), { recursive: true })
  await fs.mkdir(path.join(workspace, 'backend'), { recursive: true })
  await fs.writeFile(path.join(workspace, reportPath), markdown)
  await fs.writeFile(path.join(dir, 'psd.png'), png)
  await fs.writeFile(path.join(dir, '报告.pdf'), '%PDF-1.4\nfixture\n%%EOF\n')
  await fs.writeFile(path.join(dir, '指标.csv'), 'channel,peak_hz\n0,16\n')
  await fs.writeFile(path.join(dir, 'result.json'), '{"status":"partial","sample_range":[0,128]}\n')
  await fs.writeFile(path.join(dir, 'analysis_products.npz'), npz)
  await fs.writeFile(path.join(dir, '报告.html'), '<script>window.forbidden = true</script>')
  await fs.writeFile(path.join(dir, 'debug.py'), 'raise RuntimeError("not an artifact preview")')
  await fs.writeFile(path.join(dir, '.env'), 'fixture-secret-must-not-be-served')
  await fs.writeFile(path.join(dir, 'credentials.json'), '{"fixture":"not-public"}')
  await fs.writeFile(path.join(workspace, 'backend/.env'), 'backend-fixture-private')
  await fs.writeFile(path.join(outside, 'private.md'), 'outside-fixture-private')
  await fs.symlink(path.join(outside, 'private.md'), path.join(dir, 'outside.md'))
  await fs.symlink(outside, path.join(dir, 'outside-dir'))
  await fs.symlink(path.join(workspace, 'backend/.env'), path.join(dir, 'backend-link.md'))
  await fs.symlink(path.join(workspace, reportPath), path.join(dir, 'internal.md'))
  await fs.link(path.join(outside, 'private.md'), path.join(dir, 'hardlinked.md'))
  server = http.createServer(async (req, res) => {
    if (!(await handleArtifactRequest(req, res, { workspaceRoot: workspace }))) { res.writeHead(404); res.end() }
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  base = `http://127.0.0.1:${server.address().port}`
})

after(async () => {
  if (server) await new Promise((resolve) => server.close(resolve))
  if (workspace) await fs.rm(workspace, { recursive: true, force: true })
  if (outside) await fs.rm(outside, { recursive: true, force: true })
})

test('Chinese and space-containing metadata has canonical relative links and exact bytes', async () => {
  const response = await request(path.join(workspace, reportPath))
  assert.equal(response.status, 200)
  const metadata = await response.json()
  assert.equal(metadata.path, reportPath)
  assert.equal(metadata.preview, 'markdown')
  assert.equal(metadata.sizeBytes, Buffer.byteLength(markdown))
  assert.ok(!JSON.stringify(metadata).includes(workspace), 'must not return host absolute paths')
  const raw = await fetch(base + metadata.fileUrl)
  assert.equal(raw.status, 200)
  assert.equal(await raw.text(), markdown)
  assert.match(raw.headers.get('content-type'), /^text\/markdown/)
  assert.equal(raw.headers.get('x-content-type-options'), 'nosniff')
  assert.match(raw.headers.get('content-security-policy'), /sandbox/)
})

test('directory listing provides navigable safe files while filtering private or escaped entries', async () => {
  const response = await request('.run/海试报告 with space')
  assert.equal(response.status, 200)
  const directory = await response.json()
  assert.equal(directory.kind, 'directory')
  assert.equal(directory.parentPath, '.run')
  const names = directory.entries.map((entry) => entry.name)
  for (const visible of ['分析摘要.md', 'psd.png', 'result.json', 'analysis_products.npz', '报告.html', 'internal.md']) assert.ok(names.includes(visible), visible)
  for (const hidden of ['.env', 'credentials.json', 'debug.py', 'outside.md', 'outside-dir', 'backend-link.md', 'hardlinked.md']) assert.ok(!names.includes(hidden), hidden)
  assert.equal((await (await request('.run')).json()).parentPath, null)
  assert.equal((await request('.run/海试报告 with space', { raw: true })).status, 400)
  assert.equal((await request('tasks/job-a')).status, 200)
  assert.equal((await request('output')).status, 200)
})

test('image and PDF bytes remain inline; CSV and JSON retain their precise content types', async () => {
  const dir = '.run/海试报告 with space/'
  const image = await request(dir + 'psd.png', { raw: true })
  assert.equal(image.headers.get('content-type'), 'image/png')
  assert.match(image.headers.get('content-disposition'), /^inline;/)
  const received = Buffer.from(await image.arrayBuffer())
  assert.equal(crypto.createHash('sha256').update(received).digest('hex'), crypto.createHash('sha256').update(png).digest('hex'))
  const pdf = await request(dir + '报告.pdf', { raw: true })
  assert.equal(pdf.headers.get('content-type'), 'application/pdf')
  assert.match(pdf.headers.get('content-disposition'), /^inline;/)
  assert.ok((await pdf.text()).startsWith('%PDF-'))
  const csv = await request(dir + '指标.csv', { raw: true })
  assert.match(csv.headers.get('content-type'), /^text\/csv/)
  assert.equal(await csv.text(), 'channel,peak_hz\n0,16\n')
  const json = await request(dir + 'result.json', { raw: true })
  assert.match(json.headers.get('content-type'), /^application\/json/)
  assert.deepEqual(await json.json(), { status: 'partial', sample_range: [0, 128] })
})

test('NPZ and HTML are forced downloads and Chinese explicit downloads use RFC5987 filenames', async () => {
  const dir = '.run/海试报告 with space/'
  const archive = await request(dir + 'analysis_products.npz', { raw: true })
  assert.equal(archive.headers.get('content-type'), 'application/octet-stream')
  assert.match(archive.headers.get('content-disposition'), /^attachment;/)
  assert.deepEqual(Buffer.from(await archive.arrayBuffer()), npz)
  const html = await request(dir + '报告.html', { raw: true })
  assert.equal(html.headers.get('content-type'), 'application/octet-stream')
  assert.equal(html.headers.get('x-content-type-options'), 'nosniff')
  assert.match(html.headers.get('content-disposition'), /^attachment;/)
  assert.match(html.headers.get('content-security-policy'), /sandbox/)
  await html.arrayBuffer()
  const md = await request(reportPath, { raw: true, download: true })
  assert.match(md.headers.get('content-disposition'), /^attachment;/)
  assert.ok(md.headers.get('content-disposition').includes("filename*=UTF-8''" + encodeURIComponent('分析摘要.md')))
  assert.equal(await md.text(), markdown)
})

test('traversal, outside absolute paths, private files and escaped symlinks fail closed', async () => {
  for (const value of ['../backend/.env', '.run/../backend/.env', '.run\\report.md', '.run/a\0.txt']) {
    assert.equal((await request(value)).status, 400, value)
  }
  for (const value of ['backend/.env', path.join(outside, 'private.md'), '.run/海试报告 with space/.env',
    '.run/海试报告 with space/credentials.json', '.run/海试报告 with space/outside.md',
    '.run/海试报告 with space/outside-dir', '.run/海试报告 with space/backend-link.md',
    '.run/海试报告 with space/hardlinked.md', '.run/海试报告 with space/debug.py']) {
    for (const raw of [false, true]) {
      const response = await request(value, { raw })
      assert.equal(response.status, 403, value)
      const error = await response.json()
      assert.equal(error.ok, false)
      assert.ok(!JSON.stringify(error).includes('fixture-private'))
      assert.ok(!JSON.stringify(error).includes(workspace))
    }
  }
  const safeLink = await request('.run/海试报告 with space/internal.md', { raw: true })
  assert.equal(safeLink.status, 200)
  assert.equal(await safeLink.text(), markdown)
})

test('missing paths, duplicate parameters, unsupported methods and HEAD have stable HTTP semantics', async () => {
  const missing = await request('.run/does-not-exist.md')
  assert.equal(missing.status, 404)
  assert.deepEqual(await missing.json(), { ok: false, error: '产物不存在' })
  assert.equal((await fetch(base + '/api/artifacts')).status, 400)
  assert.equal((await fetch(base + '/api/artifacts?path=.run&path=tasks')).status, 400)
  const post = await request(reportPath, { method: 'POST' })
  assert.equal(post.status, 405)
  assert.equal(post.headers.get('allow'), 'GET, HEAD')
  const head = await request(reportPath, { raw: true, method: 'HEAD' })
  assert.equal(head.status, 200)
  assert.equal(Number(head.headers.get('content-length')), Buffer.byteLength(markdown))
  assert.equal(await head.text(), '')
})

test('large text becomes a download and directory responses expose their listing limit', async () => {
  const dir = path.join(workspace, 'output/large')
  await fs.mkdir(dir)
  const text = 'x'.repeat(2 * 1024 * 1024 + 1)
  await fs.writeFile(path.join(dir, 'large.txt'), text)
  const metadata = await (await request('output/large/large.txt')).json()
  assert.equal(metadata.preview, 'download')
  const raw = await fetch(base + metadata.fileUrl)
  assert.match(raw.headers.get('content-disposition'), /^attachment;/)
  assert.equal((await raw.text()).length, text.length)
  await Promise.all(Array.from({ length: 301 }, (_, i) => fs.writeFile(path.join(dir, `${i}.txt`), 'fixture')))
  const listing = await (await request('output/large')).json()
  assert.equal(listing.entries.length, 300)
  assert.equal(listing.truncated, true)
  assert.equal(listing.maxEntries, 300)
})
