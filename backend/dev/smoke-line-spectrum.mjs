/** 真实 SDK 的评价集成测试；使用现有合成检测包夹具，不实现或重跑检测器。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createHash, randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { backendDir, workspaceRoot, pythonEnvironment, createProjectHarness } from '../harness/runtime.mjs'
import { listProjectSkills } from '../harness/skills.mjs'
import { runHarnessTask } from '../harness/task.mjs'

process.loadEnvFile(path.join(backendDir, '.env'))
assert.ok(process.env.LLM_API_KEY, '真实模型测试需要 LLM_API_KEY')
process.env.PYTHONDONTWRITEBYTECODE = '1'
const args = process.argv.slice(2)
const only = args.includes('--only') ? args[args.indexOf('--only') + 1] : null
const id = randomUUID()
const dir = path.join(workspaceRoot, '.run', 'line-spectrum-integration', 'model-' + id)
const cache = path.join(dir, 'cache')
const temp = path.join(dir, 'tmp')
fs.mkdirSync(cache, { recursive: true })
fs.mkdirSync(temp)
const skillDir = path.join(workspaceRoot, 'skills', 'underwater-line-spectrum-evaluation')
const script = path.join(skillDir, 'scripts', 'evaluation_runtime.py')
const sha = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const filesUnder = folder => fs.readdirSync(folder, { withFileTypes: true }).flatMap(entry => {
  const file = path.join(folder, entry.name)
  return entry.isDirectory() ? (entry.name === '__pycache__' ? [] : filesUnder(file)) : [file]
})
const hashesUnder = folder => Object.fromEntries(filesUnder(folder).map(file => [file, sha(file)]))
const sourceHashes = { [fileURLToPath(import.meta.url)]: sha(fileURLToPath(import.meta.url)), ...hashesUnder(skillDir) }
const assertUnchanged = (hashes, reason) => {
  for (const [file, hash] of Object.entries(hashes)) assert.equal(sha(file), hash, reason + ': ' + file)
}
const { python, env: baseEnv } = pythonEnvironment()
const env = { ...baseEnv, MPLBACKEND: 'Agg', MPLCONFIGDIR: cache, XDG_CACHE_HOME: cache,
  TMPDIR: temp, PYTHONDONTWRITEBYTECODE: '1' }
const runPython = (code, extra = []) => execFileSync(python, ['-B', '-W', 'error::RuntimeWarning', '-c', code, ...extra], {
  cwd: workspaceRoot, env, encoding: 'utf8', timeout: 30000, maxBuffer: 4 * 1024 * 1024,
})
const argsOf = event => typeof event.data?.arguments === 'string' ? JSON.parse(event.data.arguments) : event.data?.arguments || {}
const loadedSkill = events => events.some(event => event.type === 'tool/call' && event.data?.name === 'skill'
  && JSON.stringify(event.data.arguments).includes('underwater-line-spectrum-evaluation'))
  || events.some(event => event.type === 'user/message' && event.data?.source?.kind === 'skill-invocation'
    && event.data.source.name === 'underwater-line-spectrum-evaluation')
const evaluationCalls = events => events.filter(event => event.type === 'tool/call' && event.data?.name === 'bash'
  && [script, path.relative(workspaceRoot, script)].some(value => (argsOf(event).command || '').includes(value)))
const summary = { id, scope: 'Existing RuntimeFixture synthetic persisted candidates only; no detector or real-data authorization',
  status: 'running', sourceHashes, scenarios: [] }
const save = () => fs.writeFileSync(path.join(dir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
let harness
const cancel = () => { harness?.close().catch(() => {}) }
process.once('SIGINT', cancel)
process.once('SIGTERM', cancel)
save()

try {
  const catalog = await listProjectSkills(workspaceRoot)
  assert.ok(catalog.some(item => item.name === 'underwater-line-spectrum-evaluation'))
  fs.writeFileSync(path.join(dir, 'catalog.json'), JSON.stringify(catalog, null, 2) + '\n')
  const completeDir = path.join(dir, 'no-truth-descriptive-evaluation')
  const blockedDir = path.join(dir, 'tampered-result-reference')
  fs.mkdirSync(completeDir)
  fs.mkdirSync(blockedDir)
  runPython(`import sys
from pathlib import Path
skill, complete, blocked = map(Path, sys.argv[1:])
sys.path.insert(0, str(skill / 'tests'))
from test_runtime import RuntimeFixture, metric, write_json
for directory, invalid in ((complete, False), (blocked, True)):
    fixture=RuntimeFixture(directory)
    kinds=['candidate_count','mean_candidates_per_frame','candidate_frame_fraction','mean_threshold_margin_db','false_count']
    request=fixture.request(directory/'evaluation', [metric('m'+str(i),kind) for i,kind in enumerate(kinds)])
    request['payload']['question']='Synthetic SDK evaluation smoke; use saved JSON candidates only; no raw waveform or detection algorithm.'
    request['payload']['confirmation']['statement']='MOCK SYNTHETIC TEST ONLY: evaluate the explicitly selected existing fixture package; does not authorize real data.'
    request['payload']['accepted_limitations']=['Synthetic RuntimeFixture only; no truth/background; not real-data performance or engineering acceptance.']
    if invalid:
        request['payload']['targets'][0]['result_ref']['sha256']='0'*64
    write_json(directory/'confirmed-evaluation-request.json',request)
`, [skillDir, completeDir, blockedDir])
  const scenarios = [
    {
      name: 'no-truth-descriptive-evaluation', directory: completeDir,
      prompt: `这是合成夹具集成测试，只评价已经持久保存的规范JSON检测包，不执行任何检测算法。使用 ${path.join(completeDir, 'confirmed-evaluation-request.json')}，其中对象、范围、所选指标、保存目录与MOCK确认都已明确，仅适用于本次合成夹具。真值none且没有可信背景，请按现有匹配Skill的必读文档和已有请求实际调用 evaluation_runtime.py --preflight-only，把原始预检JSON写到 ${path.join(completeDir, 'preflight.json')}；通过后再以 --output-dir ${path.join(completeDir, 'evaluation')} 运行评价。计算候选总数、帧均候选数、有候选帧占比、平均门限余量，并对false_count记录真实证据不足状态与null，不能填0。不得改已确认请求/输入摘要、补候选/真值、修改阈值、重新检测、FFT或读取任何原始录音。不请求报告，不生成report.md或额外产物。完成后直接在对话中用小表和200字左右说明实际数值、分母与误报不可算的原因，不用结果目录或文件链接替代内容。`,
      check(result, calls) {
        assert.ok(calls.some(event => (argsOf(event).command || '').includes('--preflight-only')), '没有实际执行只读预检')
        assert.ok(calls.some(event => (argsOf(event).command || '').includes('--output-dir')), '没有实际运行评价入口')
        const preflight = JSON.parse(fs.readFileSync(path.join(completeDir, 'preflight.json'), 'utf8'))
        assert.equal(preflight.can_execute, true)
        const output = path.join(completeDir, 'evaluation')
        const evaluated = JSON.parse(fs.readFileSync(path.join(output, 'evaluation-result.json'), 'utf8'))
        assert.equal(evaluated.record_type, 'EvaluationResult')
        assert.equal(evaluated.payload.execution_status, 'completed')
        const metrics = Object.fromEntries(evaluated.payload.metrics.map(metric => [metric.metric_kind, metric]))
        assert.equal(metrics.candidate_count.value, 3)
        assert.equal(metrics.mean_candidates_per_frame.value, 1.5)
        assert.equal(metrics.candidate_frame_fraction.value, 1)
        assert.ok(Math.abs(metrics.mean_threshold_margin_db.value - 10 * Math.log10(2)) < 1e-12)
        for (const kind of ['candidate_count', 'mean_candidates_per_frame', 'candidate_frame_fraction', 'mean_threshold_margin_db']) {
          assert.equal(metrics[kind].status, 'computed')
        }
        assert.equal(metrics.false_count.value, null)
        assert.equal(metrics.false_count.status, 'insufficient_evidence')
        assert.ok(metrics.false_count.reason)
        assert.equal(evaluated.payload.acceptance.status, 'not_requested')
        assert.ok(!fs.existsSync(path.join(output, 'report.md')), '未请求却生成报告')
        assert.deepEqual(fs.readdirSync(output).sort(), ['evaluation-result.json', 'package-manifest.json', 'resolved-evaluation-config.json'])
        const manifest = JSON.parse(fs.readFileSync(path.join(output, 'package-manifest.json'), 'utf8'))
        for (const artifact of manifest.files) {
          const file = path.resolve(output, artifact.path)
          assert.ok(file.startsWith(output + path.sep))
          assert.equal(fs.statSync(file).size, artifact.size_bytes)
          assert.equal(sha(file), artifact.sha256)
        }
        assert.match(result.finalResponse, /\b3\b/, '对话未呈现候选总数')
        assert.match(result.finalResponse, /1\.5/, '对话未呈现帧均值')
        assert.match(result.finalResponse, /3\.01/, '对话未呈现门限余量')
        assert.match(result.finalResponse, /证据不足|真值|可信背景/, '对话未解释误报证据边界')
        runPython(`import sys
from pathlib import Path
skill,result=map(Path,sys.argv[1:]); sys.path.insert(0,str(skill/'scripts'))
from validate_contract import read_json,validate_document
assert validate_document(read_json(result),'EvaluationResult')['valid']
`, [skillDir, path.join(output, 'evaluation-result.json')])
        return { output, candidateCount: 3, meanCandidatesPerFrame: 1.5,
          meanThresholdMarginDb: metrics.mean_threshold_margin_db.value, falseCount: null,
          falseCountStatus: 'insufficient_evidence', coreArtifactHashesVerified: manifest.files.length, reportGenerated: false }
      },
    },
    {
      name: 'tampered-result-reference', directory: blockedDir,
      prompt: `这是合成夹具的坏摘要阻断测试，只使用 ${path.join(blockedDir, 'confirmed-evaluation-request.json')} 做已有线谱检测结果评价的只读跨文档预检。请求刻意将result_ref.sha256声明为全0，这不是实际包摘要，不得修复请求或输入、不寻找别的结果、不补造检测器/候选/真值。使用匹配的现有Skill，实际调用 evaluation_runtime.py --preflight-only，把原始预检JSON写到 ${path.join(blockedDir, 'preflight.json')}，保留工具真实失败状态；预检不通过就停止，不调用 --output-dir，不输出EvaluationResult。不读取原始录音、不重新检测、FFT或调整参数。200字左右直接说明实际阻断原因和缺证据，等待用户给出可信引用，不把缺证据说成零候选或零误报。`,
      check(result, calls) {
        assert.ok(calls.some(event => (argsOf(event).command || '').includes('--preflight-only')), '没有实际执行阻断预检')
        assert.ok(!calls.some(event => (argsOf(event).command || '').includes('--output-dir')), '预检受阻却执行评价')
        const report = JSON.parse(fs.readFileSync(path.join(blockedDir, 'preflight.json'), 'utf8'))
        assert.equal(report.can_execute, false)
        assert.ok(report.issues.some(issue => issue.code === 'target_preflight_failed'))
        assert.match(JSON.stringify(report.issues), /SHA|sha|digest|hash|摘要/i)
        assert.ok(!fs.existsSync(path.join(blockedDir, 'evaluation')), '受阻任务发布了评价包')
        assert.match(result.finalResponse, /摘要|哈希|SHA|sha|hash/)
        return { readOnlyPreflightBlocked: true, evaluationPublished: false, issues: report.issues }
      },
    },
  ]
  if (only) assert.ok(scenarios.some(item => item.name === only), '未知场景：' + only)
  for (const scenario of scenarios) {
    if (only && scenario.name !== only) continue
    console.log('[scenario] ' + scenario.name)
    const packageHashes = hashesUnder(path.join(scenario.directory, 'detection'))
    const request = path.join(scenario.directory, 'confirmed-evaluation-request.json')
    const requestHash = sha(request)
    const prompt = `${scenario.prompt}\n只使用项目Python与当前JSON证据文件，不安装/升级依赖、不访问外部资料、不调用视觉模型、不创建子智能体、不操作服务或真实数据。bash每步description用简短中文说明目的，合并必要核验，避免重复流程。`
    fs.writeFileSync(path.join(scenario.directory, 'prompt.txt'), prompt + '\n')
    fs.writeFileSync(path.join(scenario.directory, 'source-hashes.json'), JSON.stringify({ requestSha256: requestHash, packageHashes }, null, 2) + '\n')
    const record = { name: scenario.name, status: 'running', passed: false, requestSha256: requestHash, packageHashes }
    summary.scenarios.push(record)
    save()
    const streamed = []
    const start = Date.now()
    let result
    harness = createProjectHarness({ home: path.join(scenario.directory, 'runtime') })
    try {
      result = await runHarnessTask(harness, prompt, { timeoutMs: 180000, onNotification(notification) {
        const event = notification.params?.event
        if (event) {
          streamed.push(event)
          fs.appendFileSync(path.join(scenario.directory, 'events.jsonl'), JSON.stringify(event) + '\n')
        }
        if (event?.type === 'tool/call') console.log('[tool] ' + event.data.name)
      } })
      fs.writeFileSync(path.join(scenario.directory, 'response.txt'), result.finalResponse + '\n')
      assert.ok(result.finalResponse.trim())
      assert.ok(loadedSkill(result.events), 'SDK未加载线谱评价Skill')
      const bashCalls = result.events.filter(event => event.type === 'tool/call' && event.data?.name === 'bash')
      for (const event of bashCalls) {
        const toolArgs = argsOf(event)
        assert.match(toolArgs.description || '', /[\u4e00-\u9fff]{2}/, '执行步骤没有中文目的description')
        assert.ok(!/(?:line_spectrum_metrics\.py|np\.fft\.|numpy\.fft\.|scipy\.(?:signal|fft)|cfar_(?:run|detect))/.test(toolArgs.command || ''), '评价任务调用了检测/FFT')
        assert.ok(!/\.(?:sio|wav|npy|npz|hdf5|h5)(?:["'\s]|$)/i.test(toolArgs.command || ''), '评价任务读取了波形文件')
      }
      const evidence = scenario.check(result, evaluationCalls(result.events))
      assert.equal(sha(request), requestHash, '评价请求被改写')
      assertUnchanged(packageHashes, '原检测包被改写')
      assertUnchanged(sourceHashes, '测试/Skill源文件被改写')
      Object.assign(record, { status: 'passed', passed: true, sessionId: result.sessionId,
        elapsedMs: Date.now() - start, toolCalls: result.events.filter(event => event.type === 'tool/call').length,
        bashDescriptions: bashCalls.map(event => argsOf(event).description), ...evidence })
      console.log('[passed] ' + scenario.name)
    } catch (error) {
      Object.assign(record, { status: 'failed', error: error.message, elapsedMs: Date.now() - start })
      console.error('[failed] ' + scenario.name + ': ' + error.message)
    } finally {
      fs.writeFileSync(path.join(scenario.directory, 'events.json'), JSON.stringify(result?.events || streamed, null, 2) + '\n')
      await harness.close()
      harness = null
      save()
    }
  }
  summary.status = summary.scenarios.every(item => item.passed) ? 'passed' : 'failed'
  console.log(`Line-spectrum evaluation smoke ${summary.status}: ${summary.scenarios.filter(item => item.passed).length}/${summary.scenarios.length}: ` + path.join(dir, 'summary.json'))
  if (summary.status !== 'passed') process.exitCode = 1
} catch (error) {
  summary.status = 'failed'
  summary.error = error.message
  throw error
} finally {
  try { if (harness) await harness.close() }
  finally { process.removeListener('SIGINT', cancel); process.removeListener('SIGTERM', cancel); save() }
}
