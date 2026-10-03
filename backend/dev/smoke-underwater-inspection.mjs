/** 真实模型调用正式水声体检 Skill；核验脚本产物、来源及执行轨迹。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { randomUUID, createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { backendDir, workspaceRoot, pythonEnvironment, createProjectHarness } from '../harness/runtime.mjs'
import { listProjectSkills } from '../harness/skills.mjs'
import { runHarnessTask } from '../harness/task.mjs'

process.loadEnvFile(path.join(backendDir, '.env'))
assert.ok(process.env.LLM_API_KEY, '真实模型测试需要 LLM_API_KEY')
const args = process.argv.slice(2)
const only = args.includes('--only') ? args[args.indexOf('--only') + 1] : null
const resume = args.includes('--resume')
const id = resume ? args[args.indexOf('--resume') + 1] : randomUUID()
assert.match(id || '', /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/)
const dir = path.join(workspaceRoot, '.run', 'underwater-inspection-smoke', id)
const inputs = path.join(dir, '中文 原始数据')
fs.mkdirSync(inputs, { recursive: true })
const skillDir = path.join(workspaceRoot, 'skills/underwater-data-inspection')
const script = path.join(skillDir, 'scripts/inspect_data.py')
const sha = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const filesUnder = folder => fs.readdirSync(folder, { withFileTypes: true }).flatMap(entry => {
  const file = path.join(folder, entry.name)
  return entry.isDirectory() ? (entry.name === '__pycache__' ? [] : filesUnder(file)) : [file]
})
const hashes = Object.fromEntries(filesUnder(skillDir).map(file => [file, sha(file)]))
const summary = { id, status: 'running', scenarios: [] }
const save = () => fs.writeFileSync(path.join(dir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
const checks = report => Object.fromEntries(report.checks.map(check => [check.id, check]))
save()
let harness
const cancel = () => { harness?.close().catch(() => {}) }
process.once('SIGINT', cancel)
process.once('SIGTERM', cancel)
try {
  execFileSync(path.join(workspaceRoot, 'setup-python.sh'), ['--ensure'], { cwd: workspaceRoot, stdio: 'inherit' })
  const { python, env } = pythonEnvironment()
  if (!resume) execFileSync(python, ['-c', `import numpy as np, h5py
from scipy.io import wavfile
from pathlib import Path
import sys
p=Path(sys.argv[1])
t=np.arange(8195)/1024
x=np.column_stack([np.sin(2*np.pi*80*t), 0.8*np.sin(2*np.pi*96*t), np.cos(2*np.pi*64*t), np.zeros(t.size), np.sin(2*np.pi*32*t)])
x[20:23,2]=np.nan
x[5000:5020,4]=0
with h5py.File(p/'阵列 数据.h5','w') as f:
    f['recordings']=x
    f['fs_hz']=1024.0
np.save(p/'未知采样率.npy',np.arange(4500,dtype=np.int16).reshape(3,1500))
np.savez(p/'歧义.npz',sound=np.ones((2,128)), candidate=np.zeros((128,2)))
wavfile.write(p/'冲突.wav',2048,(12000*np.sin(2*np.pi*256*np.arange(4096)/2048)).astype(np.int16))
`, inputs], { cwd: workspaceRoot, env })
  const catalog = await listProjectSkills(workspaceRoot)
  assert.ok(catalog.some(item => item.name === 'underwater-data-inspection'))
  fs.writeFileSync(path.join(dir, 'catalog.json'), JSON.stringify(catalog, null, 2) + '\n')
  const cases = [
    {
      name: 'implicit-hdf5-health-and-spectrum', source: path.join(inputs, '阵列 数据.h5'),
      task: `请读取并体检这个水声文件，做基础PSD及时频分析。已确认波形字段是 /recordings，轴0是时间样本，采样率取已确认以Hz存储的 /fs_hz 字段，原始数值单位为ADC counts。检查全部样本和全部通道；为控制基础分析开销，只分析起点后的4099个样本、原始通道0、1、2。频率网格希望2Hz，选择并记录合适窗长和50%重叠。报告异常区间、恒值通道、实际覆盖以及后续用于检测的限制。`,
      check(report, out) {
        assert.equal(report.status, 'partial')
        assert.deepEqual(report.dataset.view_shape, [8195, 5])
        assert.equal(report.dataset.sample_rate_hz.value, 1024)
        assert.equal(report.quality.channels.length, 5)
        const rows = report.quality.channels
        assert.equal(rows[2].nan_count, 3)
        assert.deepEqual(rows[2].nonfinite_ranges, [[20, 23]])
        assert.equal(rows[3].std_population, 0)
        assert.equal(rows[3].longest_zero_run.length, 8195)
        assert.equal(report.analysis.settings.nperseg, 512)
        assert.equal(report.analysis.settings.noverlap, 256)
        assert.equal(report.analysis.settings.full_segments, 15)
        assert.equal(report.analysis.settings.frequency_grid_spacing_hz, 2)
        assert.deepEqual(report.analysis.coverage.sample_range, [0, 4099])
        assert.equal(report.analysis.coverage.unused_tail_samples, 3)
        assert.equal(report.analysis.channels[2].status, 'skipped')
        assert.equal(report.analysis.channels[0].strongest_bin_hz, 80)
        assert.equal(report.analysis.channels[1].strongest_bin_hz, 96)
        assert.equal(checks(report)['analysis.psd'].coverage.complete_source_range, false)
        assert.equal(report.coverage_summary.all_listed_checks_complete, false)
        for (const file of ['report.md', 'channel_quality.csv', 'feature_status.csv', 'analysis_products.npz', 'psd.png', 'spectrogram_ch0.png']) assert.ok(fs.existsSync(path.join(out, file)), file)
        const png = fs.readFileSync(path.join(out, 'psd.png'))
        assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10])
      },
    },
    {
      name: 'explicit-missing-sample-rate', source: path.join(inputs, '未知采样率.npy'),
      task: `$underwater-data-inspection 已确认这个NPY的轴1是样本，轴0是原始通道。希望体检并分析，但采样率没有记录，不要猜。当前不追问，先保存能完成的检查和不能完成的步骤，说明下一步所需最小信息。`,
      check(report, out) {
        assert.equal(report.status, 'partial')
        assert.deepEqual(report.dataset.view_shape, [1500, 3])
        assert.equal(report.dataset.sample_rate_hz.value, null)
        assert.equal(report.dataset.sample_rate_hz.state, 'missing')
        assert.equal(report.dataset.duration_s, null)
        assert.equal(report.quality.channels.length, 3)
        assert.equal(report.stages.analysis.status, 'blocked')
        assert.ok(report.issues.some(item => item.code === 'sample_rate_missing'))
        assert.ok(!fs.existsSync(path.join(out, 'analysis_products.npz')))
      },
    },
    {
      name: 'ambiguous-fields-and-axes', source: path.join(inputs, '歧义.npz'), probeOnly: true,
      task: `这个NPZ没有字段、轴和采样率说明。先探查文件，列出真实候选和阻断条件，不按数组大小或名称猜波形字段与轴。本次只交付探查证据，不执行需要这些事实的检查或频谱。`,
      check(report, out) {
        assert.equal(report.status, 'completed')
        assert.equal(report.request.operation, 'probe')
        assert.equal(report.probe.fields.length, 2)
        assert.ok(!report.dataset)
        assert.ok(!report.quality)
        assert.ok(!report.analysis)
        assert.ok(!fs.existsSync(path.join(out, 'analysis_products.npz')))
        assert.equal(checks(report)['reading.selection'].status, 'not_run')
      },
    },
    {
      name: 'wav-sample-rate-conflict', source: path.join(inputs, '冲突.wav'),
      task: `请体检并尝试基础分析这个WAV。我的记录写采样率4096Hz，但可能与文件头冲突。如果冲突，请保留双方证据，不替我选择，不编造解决理由。当前不追问，先保存不依赖冲突参数的检查，暂停Hz/秒相关分析。`,
      check(report, out) {
        assert.equal(report.status, 'partial')
        assert.equal(report.dataset.sample_rate_hz.state, 'conflict')
        assert.equal(report.dataset.sample_rate_hz.value, null)
        assert.deepEqual(report.dataset.sample_rate_hz.sources.map(item => item.value), [2048, 4096])
        assert.equal(report.quality.channels[0].sample_count, 4096)
        assert.equal(report.stages.analysis.status, 'blocked')
        assert.ok(!report.config.values.sample_rate_resolution)
        assert.ok(!fs.existsSync(path.join(out, 'analysis_products.npz')))
      },
    },
  ]
  if (only) assert.ok(cases.some(item => item.name === only), '未知场景：' + only)
  harness = createProjectHarness({ home: path.join(dir, 'runtime') })
  for (const scenario of cases) {
    if (only && scenario.name !== only) continue
    console.log('[scenario] ' + scenario.name)
    const sourceHash = sha(scenario.source)
    const out = path.join(dir, scenario.name, 'result')
    const probeOut = path.join(dir, scenario.name, 'probe')
    fs.mkdirSync(path.dirname(out), { recursive: true })
    const streamed = []
    const task = `${scenario.task}\n输入：${scenario.source}\n${scenario.probeOnly ? `探查产物目录必须为 ${out}。` : `先探查后配置；探查目录 ${probeOut}，run的原始产物目录必须为 ${out}。完整分析请求使用mode=analyze，即使缺条件也保留partial诊断。`}使用匹配的现有Skill及其资源脚本，使用项目Python。不要改Skill、源文件或脚本原始JSON，不安装依赖、不访问外部服务、不创建子智能体。输出新目录，核对原始报告和适用的数值产品后，在500字以内解释观察、分析设置依据、已完成步骤与受阻条件；不得宣布目标检测成功或工程验收通过。`
    const eventFile = path.join(dir, scenario.name + '.events.json')
    const liveEventFile = path.join(dir, scenario.name + '.events.jsonl')
    const responseFile = path.join(dir, scenario.name + '.response.txt')
    const reuse = resume && fs.existsSync(path.join(out, 'result.json')) && fs.existsSync(eventFile) && fs.existsSync(responseFile)
    let result
    try {
      result = reuse ? { events: JSON.parse(fs.readFileSync(eventFile, 'utf8')), finalResponse: fs.readFileSync(responseFile, 'utf8'), sessionId: null } : await runHarnessTask(harness, task, { timeoutMs: 450000, onNotification(notification) {
        const event = notification.params?.event
        if (event) { streamed.push(event); fs.appendFileSync(liveEventFile, JSON.stringify(event) + '\n') }
        if (event?.type === 'tool/call') console.log('[tool] ' + event.data.name)
      } })
    } finally { fs.writeFileSync(eventFile, JSON.stringify(result?.events || streamed, null, 2) + '\n') }
    fs.writeFileSync(responseFile, result.finalResponse + '\n')
    const report = JSON.parse(fs.readFileSync(path.join(out, 'result.json'), 'utf8'))
    assert.equal(report.source.path, scenario.source)
    assert.notEqual(report.results_valid, false)
    assert.equal(report.source_consistency, 'unchanged_size_and_mtime')
    assert.ok(result.events.some(event => {
      if (event.type !== 'tool/call' || event.data.name !== 'bash') return false
      const args = typeof event.data.arguments === 'string' ? JSON.parse(event.data.arguments) : event.data.arguments
      const command = args.command || ''
      const hasResourceBase = [skillDir, path.relative(workspaceRoot, skillDir)].some(value => command.includes(value))
      return hasResourceBase && /inspect_data\.py["']?\s+(probe|run)\b/.test(command)
    }), '未实际执行Skill入口')
    assert.ok(result.events.some(event => event.type === 'tool/call' && event.data.name === 'skill' && JSON.stringify(event.data.arguments).includes('underwater-data-inspection')) || result.events.some(event => event.type === 'user/message' && event.data?.source?.kind === 'skill-invocation' && event.data.source.name === 'underwater-data-inspection'), '未由SDK加载Skill')
    scenario.check(report, out)
    assert.equal(sha(scenario.source), sourceHash, '源数据被修改')
    for (const [file, hash] of Object.entries(hashes)) assert.equal(sha(file), hash, 'Skill资源被修改：' + file)
    summary.scenarios.push({ name: scenario.name, passed: true, reusedRecordedRun: reuse, sessionId: result.sessionId, output: out, sourceSha256: sourceHash })
    save()
  }
  summary.status = 'passed'
  console.log(`All ${summary.scenarios.length} real-model underwater inspection scenarios passed: ` + path.join(dir, 'summary.json'))
} catch (error) {
  summary.status = 'failed'; summary.error = error.message
  throw error
} finally {
  try { if (harness) await harness.close() }
  finally { process.removeListener('SIGINT', cancel); process.removeListener('SIGTERM', cancel); save() }
}
