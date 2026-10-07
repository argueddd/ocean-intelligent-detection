/** 真实模型的波束 Skill 集成测试；所有数据/参数/MOCK 仅适用于隔离合成夹具。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createHash, randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { backendDir, workspaceRoot, pythonEnvironment, createProjectHarness } from '../harness/runtime.mjs'
import { listProjectSkills } from '../harness/skills.mjs'
import { runHarnessTask } from '../harness/task.mjs'

process.loadEnvFile(path.join(backendDir, '.env'))
assert.ok(process.env.LLM_API_KEY, '真实模型测试需要 LLM_API_KEY')
process.env.PYTHONDONTWRITEBYTECODE = '1'
const args = process.argv.slice(2)
const only = args.includes('--only') ? args[args.indexOf('--only') + 1] : null
const id = randomUUID()
const dir = path.join(workspaceRoot, '.run', 'beamforming-integration', 'model-' + id)
const cache = path.join(dir, 'cache')
fs.mkdirSync(cache, { recursive: true })
const skillDir = path.join(workspaceRoot, 'skills', 'underwater-beamforming')
const script = path.join(skillDir, 'scripts', 'execute.py')
const sha = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const filesUnder = folder => fs.readdirSync(folder, { withFileTypes: true }).flatMap(entry => {
  const file = path.join(folder, entry.name)
  return entry.isDirectory() ? (entry.name === '__pycache__' ? [] : filesUnder(file)) : [file]
})
const skillHashes = Object.fromEntries(filesUnder(skillDir).map(file => [file, sha(file)]))
const { python, env: baseEnv } = pythonEnvironment()
const env = { ...baseEnv, MPLBACKEND: 'Agg', MPLCONFIGDIR: cache, XDG_CACHE_HOME: cache, PYTHONDONTWRITEBYTECODE: '1' }
const runPython = (code, extra = []) => execFileSync(python, ['-B', '-W', 'error::RuntimeWarning', '-c', code, ...extra], {
  cwd: workspaceRoot, env, encoding: 'utf8', timeout: 30000, maxBuffer: 4 * 1024 * 1024,
})
const argsOf = event => typeof event.data?.arguments === 'string' ? JSON.parse(event.data.arguments) : event.data?.arguments || {}
const loadedSkill = events => events.some(event => event.type === 'tool/call' && event.data?.name === 'skill'
  && JSON.stringify(event.data.arguments).includes('underwater-beamforming'))
  || events.some(event => event.type === 'user/message' && event.data?.source?.kind === 'skill-invocation'
    && event.data.source.name === 'underwater-beamforming')
const summary = { id, scope: 'synthetic fixtures only; MOCK approvals are not authorization for real data', status: 'running', scenarios: [] }
const save = () => fs.writeFileSync(path.join(dir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
let harness
const cancel = () => { harness?.close().catch(() => {}) }
process.once('SIGINT', cancel)
process.once('SIGTERM', cancel)
save()

try {
  const catalog = await listProjectSkills(workspaceRoot)
  assert.ok(catalog.some(item => item.name === 'underwater-beamforming'))
  assert.ok(catalog.some(item => item.name === 'underwater-data-inspection'))
  fs.writeFileSync(path.join(dir, 'catalog.json'), JSON.stringify(catalog, null, 2) + '\n')
  const blockedDir = path.join(dir, 'missing-array-parameters')
  const completeDir = path.join(dir, 'confirmed-synthetic-cbf-mvdr')
  fs.mkdirSync(blockedDir)
  fs.mkdirSync(completeDir)
  runPython(`import json, sys
from pathlib import Path
import numpy as np
skill, blocked, complete = map(Path, sys.argv[1:])
sys.path.insert(0, str(skill / 'tests'))
from test_numerical import numerical_fixture, mock_confirm
from test_output_products import settings
rng = np.random.default_rng(20431004)
np.save(blocked / 'synthetic-missing-parameters.npy', rng.normal(size=(4096, 3)), allow_pickle=False)
cfg = numerical_fixture(complete)
cfg['plan']['output'].update(directory=str(complete / 'result'), auxiliary_products=['psd'],
                           beam_selection='explicit_indices', time_domain_beam_indices=[1], save_time_domain=True)
cfg['analysis'] = settings(band=cfg['plan']['processing']['band_hz'])
cfg['numerics'].update(max_working_bytes=1000000000, max_artifact_bytes=300000000)
mock_confirm(cfg)
(complete / 'confirmed-synthetic-config.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\\n')
`, [skillDir, blockedDir, completeDir])
  const config = path.join(completeDir, 'confirmed-synthetic-config.json')
  const configHash = sha(config)
  const scenarios = [
    {
      name: 'missing-array-parameters', directory: blockedDir,
      source: path.join(blockedDir, 'synthetic-missing-parameters.npy'),
      prompt: `请对 ${path.join(blockedDir, 'synthetic-missing-parameters.npy')} 做波束合成。这是合成数据：4096×3 float64 NPY，轴0为样本、轴1为三阵元，采样率2000Hz，原始幅值为合成幅值。没有阵列几何、声速、指向和同步/标定说明，也没有确认算法/STFT或输出选择。本轮先用现有匹配的Skill汇总阻断条件，200字左右，等待我补充；不得猜方向、采用测试夹具参数或执行数值计算。`,
      check(result) {
        assert.match(result.finalResponse, /几何|阵元.{0,6}(坐标|位置)/, '没有列出阵列几何阻断')
        assert.match(result.finalResponse, /声速/, '没有列出声速阻断')
        assert.match(result.finalResponse, /方向|指向|角度/, '没有列出方向阻断')
        assert.ok(!result.events.some(event => event.type === 'tool/call' && event.data?.name === 'bash'
          && /(?:execute|inspection_handoff|bypass_handoff|analyze_results)\.py["']?\s+(?:run|prepare)\b/.test(argsOf(event).command || '')), '受阻任务进入了执行入口')
        assert.ok(!filesUnder(blockedDir).some(file => /(?:result\.json|(?:cbf|mvdr)_.*\.npy)$/.test(file)), '受阻任务生成了波束产物')
        return { missingGeometrySoundSpeedDirections: true, numericExecutionCalled: false }
      },
    },
    {
      name: 'confirmed-synthetic-cbf-mvdr', directory: completeDir,
      source: path.join(completeDir, 'synthetic.npy'),
      prompt: `这是合成夹具集成测试，仅处理 ${path.join(completeDir, 'synthetic.npy')}，所有参数与MOCK确认仅用于本次合成验证，不授权任何真实数据。使用现有已经明确确认的配置 ${config}，按匹配Skill必读文档校验后实际调用现有execute.py check和run，计算CBF/MVDR，不更改该配置、源文件或Skill。已确认计算0°、20°两个测试方向，只保留20°（索引1）单束时域；PSD覆盖两个计算方向，analysis来自合成test_output_products.settings且MOCK已重新确认。结果目录必须为 ${path.join(completeDir, 'result')}。所有数值与范围以已有配置为准，不要求另作真实数据授权、不重新生成确认。读取真实完成清单并核对必要产物和范围，然后在200字左右总结实际运行、时域与PSD覆盖及合成验证限制；在对话中展示清单里实际存在的PSD PNG，不用结果目录或图集链接代替内容，不执行下游检测、不调用视觉模型。`,
      check(result) {
        assert.ok(result.events.some(event => event.type === 'tool/call' && event.data?.name === 'bash'
          && [script, path.relative(workspaceRoot, script)].some(value => (argsOf(event).command || '').includes(value))
          && /execute\.py["']?\s+run\b/.test(argsOf(event).command || '')), '没有实际调用Skill数值入口')
        assert.equal(sha(config), configHash, '已确认合成配置被改写')
        const out = path.join(completeDir, 'result')
        const report = JSON.parse(fs.readFileSync(path.join(out, 'result.json'), 'utf8'))
        assert.equal(report.execution_status, 'completed')
        assert.deepEqual(report.algorithms, ['cbf', 'mvdr'])
        assert.deepEqual(report.directions_deg, [[0], [20]])
        assert.deepEqual(report.shape_per_algorithm, [4096, 1])
        assert.deepEqual(report.time_domain_retention.scan_beam_indices, [1])
        assert.deepEqual(report.beams.map(beam => [beam.scan_column, beam.direction_deg]), [[1, [20]]])
        assert.deepEqual(report.spectral_products.requested_products, ['psd'])
        assert.deepEqual(report.spectral_products.delivered_products, ['psd'])
        assert.equal(report.real_data_validation, 'not_performed_by_this_run')
        assert.equal(report.downstream_integration, 'not_integrated')
        for (const artifact of report.artifacts) {
          const file = path.resolve(out, artifact.path)
          assert.ok(file.startsWith(out + path.sep), '产物引用越界')
          assert.equal(fs.statSync(file).size, artifact.size_bytes)
          assert.equal(sha(file), artifact.sha256, '产物摘要不匹配：' + artifact.path)
        }
        assert.ok(fs.existsSync(path.join(out, 'index.html')))
        const numerics = JSON.parse(runPython(`import json, sys
from pathlib import Path
import numpy as np
from scipy.signal import get_window, periodogram
out, cfgpath = map(Path, sys.argv[1:])
cfg=json.loads(cfgpath.read_text()); a=cfg['analysis']; fs=cfg['plan']['input']['sample_rate_hz']
assert json.loads((out/'confirmed_config.json').read_text()) == cfg
valid=np.load(out/'valid_sample_mask.npy',allow_pickle=False)
starts=np.load(out/'analysis_frame_start_sample.npy',allow_pickle=False)
freq=np.load(out/'analysis_frequency_hz.npy',allow_pickle=False)
np.testing.assert_array_equal(np.load(out/'directions_deg.npy',allow_pickle=False), [[0],[20]])
window=get_window(a['window'],a['window_samples'],fftbins=a['window_periodic'])
details={}
for algo in ('cbf','mvdr'):
    y=np.load(out/(algo+'_time.npy'),allow_pickle=False)
    psd=np.load(out/(algo+'_psd.npy'),allow_pickle=False)
    assert y.shape==(4096,1) and y.dtype==np.float64 and np.isfinite(y).all()
    assert psd.shape==(len(freq),2) and psd.dtype==np.float64 and np.isfinite(psd).all() and (psd>=0).all()
    frames=np.stack([y[int(s):int(s)+a['window_samples'],0] for s in starts])
    assert all(valid[int(s):int(s)+a['window_samples']].all() for s in starts)
    f,p=periodogram(frames,fs=fs,window=window,nfft=a['nfft'],detrend=False,return_onesided=True,scaling='density',axis=1)
    selected=(f>=a['band_hz'][0])&(f<=a['band_hz'][1])
    np.testing.assert_array_equal(f[selected],freq)
    expected=p[:,selected].mean(axis=0)
    np.testing.assert_allclose(psd[:,1],expected,rtol=3e-13,atol=1e-16)
    assert not (out/(algo+'_time_frequency_psd.npy')).exists()
    details[algo]={'timeShape':list(y.shape),'psdShape':list(psd.shape),'validPsdFrames':len(starts),
                   'selectedBeamPsdMatchesScipyPeriodogram':True}
print(json.dumps(details))
`, [out, config]))
        return { output: out, completed: true, retainedDirectionDeg: 20, spectralDirectionsDeg: [0, 20],
          artifactHashesVerified: report.artifacts.length, numerics }
      },
    },
  ]
  if (only) assert.ok(scenarios.some(item => item.name === only), '未知场景：' + only)
  for (const scenario of scenarios) {
    if (only && scenario.name !== only) continue
    console.log('[scenario] ' + scenario.name)
    const sourceHash = sha(scenario.source)
    const streamed = []
    const start = Date.now()
    const record = { name: scenario.name, status: 'running', passed: false, sourceSha256: sourceHash }
    summary.scenarios.push(record)
    save()
    let result
    harness = createProjectHarness({ home: path.join(scenario.directory, 'runtime') })
    try {
      const prompt = `${scenario.prompt}\n只使用项目Python。禁止安装/升级依赖、访问外部资料、改源Skill、创建子智能体或操作真实数据。bash工具每步description用简短中文说明目的，避免不必要的重复验证。`
      fs.writeFileSync(path.join(scenario.directory, 'prompt.txt'), prompt + '\n')
      result = await runHarnessTask(harness, prompt, {
        timeoutMs: 180000, onNotification(notification) {
          const event = notification.params?.event
          if (event) {
            streamed.push(event)
            fs.appendFileSync(path.join(scenario.directory, 'events.jsonl'), JSON.stringify(event) + '\n')
          }
          if (event?.type === 'tool/call') console.log('[tool] ' + event.data.name)
        },
      })
      fs.writeFileSync(path.join(scenario.directory, 'response.txt'), result.finalResponse + '\n')
      assert.ok(result.finalResponse.trim(), '没有最终回答')
      assert.ok(loadedSkill(result.events), 'SDK未加载underwater-beamforming Skill')
      const bashCalls = result.events.filter(event => event.type === 'tool/call' && event.data?.name === 'bash')
      for (const event of bashCalls) assert.match(argsOf(event).description || '', /[\u4e00-\u9fff]{2}/, '执行步骤没有中文目的description')
      const evidence = scenario.check(result)
      assert.equal(sha(scenario.source), sourceHash, '源合成数据被改写')
      for (const [file, hash] of Object.entries(skillHashes)) assert.equal(sha(file), hash, 'Skill资源被修改：' + file)
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
  console.log(`Beamforming real-model smoke ${summary.status}: ${summary.scenarios.filter(item => item.passed).length}/${summary.scenarios.length}: ` + path.join(dir, 'summary.json'))
  if (summary.status !== 'passed') process.exitCode = 1
} catch (error) {
  summary.status = 'failed'
  summary.error = error.message
  throw error
} finally {
  try { if (harness) await harness.close() }
  finally { process.removeListener('SIGINT', cancel); process.removeListener('SIGTERM', cancel); save() }
}
