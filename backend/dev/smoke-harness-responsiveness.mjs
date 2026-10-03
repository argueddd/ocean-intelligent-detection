/** Real front-end HTTP/SSE smoke: retain evidence; never reuse a user's session or rewrite existing results. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createHash, randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { performance } from 'node:perf_hooks'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const base = process.env.HARNESS_TEST_BASE_URL || 'http://127.0.0.1:3089'
assert.ok(process.env.HARNESS_REFERENCE_DIR, 'Set HARNESS_REFERENCE_DIR to existing inspection and analysis results')
assert.ok(process.env.HARNESS_SIO_TEST_FILE, 'Set HARNESS_SIO_TEST_FILE to a local SIO recording')
const reference = path.resolve(root, process.env.HARNESS_REFERENCE_DIR)
const source = path.resolve(root, process.env.HARNESS_SIO_TEST_FILE)
const image = path.join(reference, 'results-analyze-first60s/psd.png')
const args = process.argv.slice(2)
const onlyIndex = args.indexOf('--only')
const only = onlyIndex === -1 ? null : args[onlyIndex + 1]
const revalidateIndex = args.indexOf('--revalidate')
const revalidate = revalidateIndex === -1 ? null : args[revalidateIndex + 1]
if (revalidate) assert.match(revalidate, /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/)
const id = revalidate || randomUUID()
const output = path.join(root, '.run/harness-responsiveness', id)
fs.mkdirSync(output, { recursive: true })
const sha = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const filesUnder = directory => fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
  const file = path.join(directory, entry.name)
  return entry.isDirectory() ? filesUnder(file) : entry.isFile() ? [file] : []
})
const protectedFiles = ['results-full-check', 'results-analyze-first60s'].flatMap(folder => filesUnder(path.join(reference, folder)))
const protectedHashes = Object.fromEntries(protectedFiles.map(file => [file, sha(file)]))
const sourceStat = fs.statSync(source)
const sourceMetadata = { size: sourceStat.size, mtimeMs: sourceStat.mtimeMs, ctimeMs: sourceStat.ctimeMs }
const existingReports = new Set(filesUnder(path.join(root, '.run')).filter(file => path.basename(file) === 'result.json'))

const cases = [
  { name: 'greeting', timeoutMs: 120000, maxChars: 120, maxTools: 0,
    prompt: '你好' },
  { name: 'dtype-definition', timeoutMs: 120000, maxChars: 500, maxTools: 0,
    prompt: '报告里 dtype 是 >f4，尾部填充是每通道1136个。这个dtype和尾部填充是啥意思？' },
  { name: 'existing-results-summary', timeoutMs: 120000, maxChars: 1400, maxTools: 8,
    prompt: `请读取现有体检与基础分析报告，简要概括结论和覆盖范围：\n${path.join(reference, 'results-full-check')}\n${path.join(reference, 'results-analyze-first60s')}。` },
  { name: 'explicit-vision', timeoutMs: 120000, maxChars: 700, maxTools: 6,
    prompt: `用独立视觉工具读取现有 ${image}，只说明坐标和可见曲线，不估算精确频点，简短回答。` },
  { name: 'bounded-sio-analysis', timeoutMs: 240000, maxChars: 1400, maxTools: 20,
    prompt: `请用已有 Skill 分析 ${source}。采样率已确认1500Hz，原始单位未知。此次范围为前60秒、通道0/10/20，频率网格0.5Hz、50%重叠。给简要结果并保存新的任务目录。` },
]
if (only) assert.ok(cases.some(scenario => scenario.name === only), 'unknown --only case')
const summary = revalidate ? JSON.parse(fs.readFileSync(path.join(output, 'summary.json'), 'utf8'))
  : { id, status: 'running', base, output, scenarios: [], source: { path: source, ...sourceMetadata }, protectedFiles: protectedFiles.length }
const saveSummary = () => fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
if (!revalidate) saveSummary()

if (!revalidate) {
  const health = await fetch(base + '/api/health', { signal: AbortSignal.timeout(10000) }).then(response => response.json())
  assert.equal(health.ok, true)
  assert.equal(health.profile, 'harness')
}

function toolArguments(event) {
  const raw = event.data.arguments
  try { return typeof raw === 'string' ? JSON.parse(raw) : raw || {} } catch { return {} }
}
function visualResults(events) {
  const results = []
  for (const event of events.filter(event => event.type === 'tool/result')) {
    for (const block of event.data.message.content.filter(block => block.type === 'tool-result' && !block.isError)) {
      for (const text of block.content.filter(block => block.type === 'text')) {
        try { const value = JSON.parse(text.text); if (value?.source_path === image && value?.model) results.push(value) } catch {}
      }
    }
  }
  return results
}
function verifyProtected() {
  for (const [file, hash] of Object.entries(protectedHashes)) assert.equal(sha(file), hash, 'existing result changed: ' + file)
  const current = fs.statSync(source)
  assert.deepEqual({ size: current.size, mtimeMs: current.mtimeMs, ctimeMs: current.ctimeMs }, sourceMetadata, 'source file metadata changed')
}

function analysisArtifacts(calls, caseDir, retained = []) {
  const candidates = new Set(retained)
  for (const event of calls.filter(event => event.data.name === 'bash')) {
    const command = String(toolArguments(event).command || '')
    if (!/inspect_data\.py["']?\s+run\b/.test(command)) continue
    const match = /--out\s+(?:"([^"]+)"|'([^']+)'|([^\s;&|]+))/.exec(command)
    const literal = match && (match[1] || match[2] || match[3])
    if (!literal || /[$`]/.test(literal)) continue
    const directory = path.resolve(root, literal)
    const relative = path.relative(root, directory)
    assert.ok(relative && relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative), 'output must be inside the workspace')
    candidates.add(path.join(directory, 'result.json'))
  }
  for (const file of filesUnder(path.join(root, '.run')).filter(file => path.basename(file) === 'result.json' && !existingReports.has(file))) candidates.add(file)
  const startedAt = fs.statSync(path.join(caseDir, 'prompt.txt')).mtimeMs
  const matching = []
  for (const file of candidates) {
    try {
      const resolved = fs.realpathSync(file)
      const relative = path.relative(root, resolved)
      if (relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) continue
      if (fs.statSync(file).mtimeMs < startedAt - 1000) continue
      const report = JSON.parse(fs.readFileSync(file, 'utf8'))
      if (report.source?.path === source && report.analysis?.settings) matching.push({ file, report })
    } catch {}
  }
  return matching
}

function verifyAnalysisArtifacts(calls, caseDir, retained = []) {
  const failures = []
  if (!calls.some(event => event.data.name === 'bash' && /inspect_data\.py["']?\s+run\b/.test(String(toolArguments(event).command || '')))) failures.push('no actual Skill analysis invocation')
  const matching = analysisArtifacts(calls, caseDir, retained)
  if (!matching.length) failures.push('no new numerical analysis result found in the workspace')
  const valid = matching.find(({ report }) => report.analysis.settings.nperseg === 3000 && report.analysis.settings.noverlap === 1500
    && JSON.stringify(report.dataset.view_shape) === '[90000,3]' && JSON.stringify(report.analysis.coverage.sample_range) === '[0,90000]'
    && JSON.stringify(report.analysis.coverage.channel_indices) === '[0,10,20]')
  if (!valid) failures.push('bounded analysis settings or coverage do not match the request')
  return { failures, paths: matching.map(({ file }) => file), summaryPath: valid && path.join(path.dirname(valid.file), 'summary.md') }
}

async function runScenario(scenario) {
  const caseDir = path.join(output, scenario.name)
  fs.mkdirSync(caseDir)
  fs.writeFileSync(path.join(caseDir, 'prompt.txt'), scenario.prompt + '\n')
  const sessionId = 'session-responsiveness-' + randomUUID().replaceAll('-', '')
  const started = performance.now()
  const events = []
  const notifications = []
  const frames = []
  let finalResponse = ''
  let done = false
  let streamError
  let firstEventMs
  let firstAssistantTextMs
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(new Error('whole-case timeout')), scenario.timeoutMs)
  const record = { name: scenario.name, sessionId, status: 'running', timeoutMs: scenario.timeoutMs }
  try {
    const response = await fetch(base + '/api/chat/stream', { method: 'POST',
      headers: { 'content-type': 'application/json' }, body: JSON.stringify({ message: scenario.prompt, sessionId }), signal: controller.signal })
    assert.equal(response.status, 200)
    assert.ok(response.headers.get('content-type')?.includes('text/event-stream'))
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    const acceptFrame = frame => {
      const lines = frame.split(/\r?\n/)
      const kind = lines.find(line => line.startsWith('event:'))?.slice(6).trim()
      const dataText = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
      if (!kind || !dataText) return
      const data = JSON.parse(dataText)
      const elapsedMs = performance.now() - started
      firstEventMs ??= elapsedMs
      frames.push({ kind, data, elapsedMs })
      if (kind === 'notification') {
        notifications.push(data)
        const event = data.params?.event
        if (event) {
          events.push(event)
          if (event.type === 'assistant/message' && event.data.message.content.some(block => block.type === 'text' && block.text?.trim())) firstAssistantTextMs ??= elapsedMs
        }
      }
      if (kind === 'done') { finalResponse = data.finalResponse || ''; done = true }
      if (kind === 'error') streamError = new Error(String(data.message || 'stream error'))
    }
    while (true) {
      const { value, done: finished } = await reader.read()
      if (finished) break
      const decoded = decoder.decode(value, { stream: true })
      fs.appendFileSync(path.join(caseDir, 'raw.sse'), decoded)
      buffer += decoded
      while (true) {
        const boundary = /\r?\n\r?\n/.exec(buffer)
        if (!boundary) break
        acceptFrame(buffer.slice(0, boundary.index))
        buffer = buffer.slice(boundary.index + boundary[0].length)
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) acceptFrame(buffer)
    if (streamError) throw streamError
    assert.equal(done, true, 'missing done event')
    assert.ok(finalResponse.trim(), 'missing final response')
    const calls = events.filter(event => event.type === 'tool/call')
    const reasoning = events.filter(event => event.type === 'assistant/message').flatMap(event => event.data.message.content).filter(block => block.type === 'reasoning')
    const usage = events.filter(event => event.type === 'assistant/message' && event.data.usage).map(event => event.data.usage)
    Object.assign(record, { elapsedMs: Math.round(performance.now() - started), firstEventMs: Math.round(firstEventMs || 0),
      firstAssistantTextMs: firstAssistantTextMs === undefined ? null : Math.round(firstAssistantTextMs), responseChars: [...finalResponse].length,
      toolCount: calls.length, toolNames: calls.map(event => event.data.name), reasoningBlockCount: reasoning.length,
      usage, visualResults: visualResults(events).map(value => ({ status: value.status, model: value.model, finishReason: value.finish_reason, usage: value.usage })) })
    const failures = []
    const check = (ok, reason) => { if (!ok) failures.push(reason) }
    check(record.responseChars <= scenario.maxChars, `response exceeds ${scenario.maxChars} characters`)
    check(record.toolCount <= scenario.maxTools, `tool count exceeds ${scenario.maxTools}`)
    check(reasoning.length === 0, 'main model returned reasoning blocks')
    if (scenario.name === 'dtype-definition') {
      check(!/^(好的[，,。！!\s]|当然[，,。！!\s]|我来|下面|这是个.{0,8}问题)/.test(finalResponse.trim()), 'unnecessary introductory chatter')
    }
    if (['existing-results-summary', 'explicit-vision', 'bounded-sio-analysis'].includes(scenario.name)) {
      for (const event of calls) {
        const params = toolArguments(event)
        const command = String(params.command || '')
        if (scenario.name === 'existing-results-summary') {
          check(!/inspect_data\.py["']?\s+run\b/.test(command), 'reran inspection while summarizing existing results')
          check(event.data.name !== 'vision_inspect', 'routine vision invocation while summarizing existing results')
          if (event.data.name === 'bash') check(!/(read_bytes|readframes|fromfile|memmap|\.sio(?:["']|\s|$))/.test(command), 'raw-waveform or independent byte read while summarizing existing results')
          check(!['write_file', 'edit_file', 'apply_patch'].includes(event.data.name), 'wrote files while summarizing existing results')
        }
        if (scenario.name === 'bounded-sio-analysis') {
          check(event.data.name !== 'vision_inspect', 'routine vision invocation without explicit request')
          if (event.data.name === 'bash') check(!/(read_bytes|readframes|fromfile|memmap|struct\.unpack|np\.frombuffer)/.test(command), 'independent source decoding or byte cross-check')
        }
      }
    }
    if (scenario.name === 'explicit-vision') {
      const visuals = calls.filter(event => event.data.name === 'vision_inspect')
      const results = visualResults(events)
      check(visuals.length >= 1 && visuals.length <= 2, 'expected one actual visual call, at most one partial-response retry')
      check(results.some(value => value.status === 'completed'), 'no completed visual response')
      if (visuals.length === 2) check(results[0]?.status === 'partial', 'second visual call was not a partial-response retry')
      check(results.every(value => value.source_sha256 === protectedHashes[image]), 'visual source hash mismatch')
    }
    if (scenario.name === 'bounded-sio-analysis') {
      const artifactCheck = verifyAnalysisArtifacts(calls, caseDir)
      failures.push(...artifactCheck.failures)
      record.newAnalysisResults = artifactCheck.paths
      record.analysisSummaryPath = artifactCheck.summaryPath
    }
    verifyProtected()
    record.failures = failures
    record.status = failures.length ? 'failed' : 'passed'
  } catch (error) {
    Object.assign(record, { status: 'failed', elapsedMs: Math.round(performance.now() - started), error: String(error.message) })
  } finally {
    clearTimeout(timer)
    fs.writeFileSync(path.join(caseDir, 'events.json'), JSON.stringify(events, null, 2) + '\n')
    fs.writeFileSync(path.join(caseDir, 'notifications.json'), JSON.stringify(notifications, null, 2) + '\n')
    fs.writeFileSync(path.join(caseDir, 'frames.json'), JSON.stringify(frames, null, 2) + '\n')
    fs.writeFileSync(path.join(caseDir, 'response.txt'), finalResponse + '\n')
    fs.writeFileSync(path.join(caseDir, 'summary.json'), JSON.stringify(record, null, 2) + '\n')
  }
  console.log(JSON.stringify({ case: record.name, status: record.status, elapsedMs: record.elapsedMs, toolCount: record.toolCount,
    reasoningBlocks: record.reasoningBlockCount, responseChars: record.responseChars, failureCount: record.failures?.length || (record.error ? 1 : 0) }))
  return record
}

if (revalidate) {
  const repaired = structuredClone(summary)
  repaired.originalStatus = summary.status
  repaired.validationRepair = 'discover literal --out paths within the workspace, without restricting unspecified output to .run'
  for (const record of repaired.scenarios) {
    if (record.name !== 'bounded-sio-analysis' || (only && record.name !== only)) continue
    const caseDir = path.join(output, record.name)
    const events = JSON.parse(fs.readFileSync(path.join(caseDir, 'events.json'), 'utf8'))
    const calls = events.filter(event => event.type === 'tool/call')
    const check = verifyAnalysisArtifacts(calls, caseDir, record.newAnalysisResults)
    record.failures = (record.failures || []).filter(reason => ![
      'no new numerical analysis result found under .run', 'no new numerical analysis result found in the workspace',
      'bounded analysis settings or coverage do not match the request', 'no actual Skill analysis invocation',
    ].includes(reason))
    record.failures.push(...check.failures)
    record.newAnalysisResults = check.paths
    record.analysisSummaryPath = check.summaryPath
    record.status = record.failures.length || record.error ? 'failed' : 'passed'
    console.log(JSON.stringify({ case: record.name, status: record.status, elapsedMs: record.elapsedMs, toolCount: record.toolCount,
      reasoningBlocks: record.reasoningBlockCount, responseChars: record.responseChars, failureCount: record.failures.length }))
  }
  assert.deepEqual({ size: sourceStat.size, mtimeMs: sourceStat.mtimeMs, ctimeMs: sourceStat.ctimeMs }, {
    size: summary.source.size, mtimeMs: summary.source.mtimeMs, ctimeMs: summary.source.ctimeMs,
  }, 'source changed since the original request')
  repaired.status = repaired.scenarios.every(record => record.status === 'passed') ? 'passed' : 'failed'
  const file = path.join(output, 'validation-repaired.json')
  fs.writeFileSync(file, JSON.stringify(repaired, null, 2) + '\n')
  console.log('Evidence: ' + file)
  if (repaired.status !== 'passed') process.exitCode = 1
} else {
  try {
    for (const scenario of cases) {
      if (only && scenario.name !== only) continue
      summary.scenarios.push(await runScenario(scenario))
      saveSummary()
    }
    verifyProtected()
    summary.status = summary.scenarios.every(scenario => scenario.status === 'passed') ? 'passed' : 'failed'
    summary.protectedResultsUnchanged = true
    summary.sourceMetadataUnchanged = true
  } finally {
    saveSummary()
    console.log('Evidence: ' + path.join(output, 'summary.json'))
  }
  if (summary.status !== 'passed') process.exitCode = 1
}
