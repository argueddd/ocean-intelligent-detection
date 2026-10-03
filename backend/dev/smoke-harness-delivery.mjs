/** Real HTTP conversation: show existing analysis in chat, then prepare an explicitly requested report. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createHash, randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { performance } from 'node:perf_hooks'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const base = process.env.HARNESS_TEST_API || 'http://127.0.0.1:3089'
const reference = path.resolve(process.argv[2] || path.join(root, '.run/swellex96-healthcheck-20261003T114049'))
const checkDir = path.join(reference, 'results-full-check')
const analysisDir = path.join(reference, 'results-analyze-first60s')
const analysis = JSON.parse(fs.readFileSync(path.join(analysisDir, 'result.json'), 'utf8'))
const source = analysis.source.path
const sourceBefore = fs.statSync(source)
const sha = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const protectedFiles = [checkDir, analysisDir].flatMap(dir => fs.readdirSync(dir).map(name => path.join(dir, name)).filter(file => fs.statSync(file).isFile()))
const hashes = Object.fromEntries(protectedFiles.map(file => [file, sha(file)]))
const id = randomUUID()
const output = path.join(root, '.run/harness-delivery', id)
const requestedReport = path.join(output, 'requested-report', 'data-report.md')
fs.mkdirSync(output, { recursive: true })
let sessionId = 'session-delivery-' + id.replaceAll('-', '')
const summary = { status: 'running', sessionId, reference, output, scenarios: [] }
const save = () => fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
save()

function links(text) {
  return [...text.matchAll(/(!?)\[[^\]\n]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+"[^"]*")?\s*\)/g)]
    .map(match => ({ image: match[1] === '!', target: match[2] || match[3] }))
}
function localPath(target, directory = root) {
  if (/^[a-z][a-z\d+.-]*:/i.test(target) || target.startsWith('//') || target.startsWith('#')) return null
  let decoded
  try { decoded = decodeURIComponent(target) } catch { decoded = target }
  return path.isAbsolute(decoded) ? decoded : path.resolve(/^(?:\.\/)?(?:\.run|tasks|output)\//.test(decoded) ? root : directory, decoded)
}
async function readableArtifact(file) {
  const response = await fetch(base + '/api/artifacts/file?path=' + encodeURIComponent(file), { signal: AbortSignal.timeout(10000) })
  assert.equal(response.status, 200, 'artifact cannot be opened: ' + file)
  assert.ok((await response.arrayBuffer()).byteLength > 0, 'empty artifact: ' + file)
}
function verifyProtected() {
  for (const [file, hash] of Object.entries(hashes)) assert.equal(sha(file), hash, 'existing result changed: ' + file)
  const current = fs.statSync(source)
  for (const field of ['size', 'mtimeMs', 'ctimeMs']) assert.equal(current[field], sourceBefore[field], 'source changed: ' + field)
}
async function run(name, prompt) {
  console.log('Starting ' + name)
  const dir = path.join(output, name)
  fs.mkdirSync(dir)
  fs.writeFileSync(path.join(dir, 'prompt.txt'), prompt + '\n')
  const started = performance.now()
  const response = await fetch(base + '/api/chat/stream', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ sessionId, message: prompt }), signal: AbortSignal.timeout(120000),
  })
  assert.equal(response.status, 200)
  const sse = await response.text()
  fs.writeFileSync(path.join(dir, 'raw.sse'), sse)
  const frames = sse.split(/\r?\n\r?\n/).flatMap(frame => {
    const kind = /^event: (.+)$/m.exec(frame)?.[1]
    const data = frame.split(/\r?\n/).filter(line => line.startsWith('data: ')).map(line => line.slice(6)).join('\n')
    return kind && data ? [{ kind, data: JSON.parse(data) }] : []
  })
  const events = frames.filter(frame => frame.kind === 'notification').map(frame => frame.data.params?.event).filter(Boolean)
  fs.writeFileSync(path.join(dir, 'events.json'), JSON.stringify(events, null, 2) + '\n')
  const done = frames.find(frame => frame.kind === 'done')
  const error = frames.find(frame => frame.kind === 'error')
  assert.ok(done, error?.data?.message || 'missing done event')
  sessionId = done.data.sessionId
  const text = done.data.finalResponse
  fs.writeFileSync(path.join(dir, 'response.md'), text + '\n')
  const calls = events.filter(event => event.type === 'tool/call')
  const reasoning = events.filter(event => event.type === 'assistant/message').flatMap(event => event.data.message.content).filter(block => block.type === 'reasoning')
  const record = { name, elapsedMs: Math.round(performance.now() - started), toolCount: calls.length, responseChars: [...text].length, reasoningBlockCount: reasoning.length, response: path.join(dir, 'response.md'), status: 'running' }
  summary.scenarios.push(record)
  save()
  const fail = message => { record.status = 'failed'; record.error = message; save(); throw new Error(message) }
  try {
    assert.equal(reasoning.length, 0)
    assert.ok(calls.length <= 12, 'excessive delivery-only tool calls')
    for (const event of calls) {
      assert.notEqual(event.data.name, 'vision_inspect', 'unrequested visual review')
      assert.ok(!/inspect_data\.py["']?\s+(?:run|probe)\b/.test(event.data.arguments), 'reran data inspection for delivery')
    }
    const peaks = analysis.analysis.channels.filter(row => row.status === 'completed').map(row => row.strongest_bin_hz)
    if (name === 'chat-content') {
      for (const peak of peaks) assert.ok(text.includes(String(peak)), 'missing numerical peak: ' + peak)
      assert.ok(/\|[^\n]+\|/.test(text), 'no useful indicator table')
      assert.ok(!/结果目录[：:]|产物清单|源文件只读|未修改/.test(text), 'backend bookkeeping in the answer')
      assert.ok(!calls.some(event => ['write', 'edit'].includes(event.data.name)), 'created a formal report without request')
      const images = links(text).filter(link => link.image).map(link => localPath(link.target)).filter(Boolean)
      assert.ok(images.length, 'did not show any existing result figure in the conversation')
      for (const image of images) await readableArtifact(image)
      record.images = images
    } else {
      const files = links(text).filter(link => !link.image).map(link => localPath(link.target)).filter(file => file?.endsWith('.md'))
      assert.ok(files.length, 'no clickable report link')
      const file = files.find(file => file === requestedReport && fs.existsSync(file))
      assert.ok(file, 'did not create the requested report in its fresh test directory')
      await readableArtifact(file)
      const report = fs.readFileSync(file, 'utf8')
      for (const peak of peaks) assert.ok(report.includes(String(peak)), 'report missing peak: ' + peak)
      const figures = links(report).filter(link => link.image).map(link => localPath(link.target, path.dirname(file))).filter(Boolean)
      assert.ok(figures.length, 'requested report contains no result figures')
      for (const figure of figures) await readableArtifact(figure)
      record.report = file
      record.reportImages = figures
    }
    verifyProtected()
    record.status = 'passed'
    save()
    console.log(JSON.stringify(record))
    return record
  } catch (error) { fail(error.message) }
}

try {
  const health = await fetch(base + '/api/health').then(response => response.json())
  assert.equal(health.profile, 'harness')
  await run('chat-content', `用已有结果告诉我这份数据有哪些特点，在对话里给我结论、关键数据和主要图：\n${checkDir}\n${analysisDir}`)
  assert.ok(!fs.existsSync(requestedReport), 'report test destination already exists')
  await run('requested-report', `把刚才的分析整理成一份正式报告给我，要包含主要图表，并且能直接点开。保存到：${requestedReport}`)
  summary.status = 'passed'
  summary.protectedResultsUnchanged = true
  summary.sourceMetadataUnchanged = true
} catch (error) {
  summary.status = 'failed'
  summary.error = error.message
  process.exitCode = 1
} finally { summary.sessionId = sessionId; save(); console.log('Evidence: ' + path.join(output, 'summary.json')) }
