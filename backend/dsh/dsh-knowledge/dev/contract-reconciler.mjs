/**
 * 契约测试 · 收敛器（启动对账 + 周期核验）。
 *
 * 覆盖：收养引擎孤儿文档、注册表 active 但引擎缺失 → missing、
 * 注册表退役但引擎残留 → 低优先级补删意图、进行中意图豁免对账、分页扫描。
 */
import { makeStack, makeRunner, ok, eq } from './harness.mjs'

const { check, finish } = makeRunner('contract-reconciler')

/** 直接在引擎里造一篇已 processed 的文档（模拟外部入库）。 */
async function seedEngineDoc(engine, source, content) {
  const r = await engine.insertText(content || ('内容:' + source), source)
  engine.advanceTicks()
  return r.documents[0].id
}

await check('收养：引擎有、注册表无 → adopted + 汇总审计', async () => {
  const s = await makeStack()
  const d1 = await seedEngineDoc(s.engine, 'orphan:1.md')
  const d2 = await seedEngineDoc(s.engine, 'orphan:2.md')
  const report = await s.reconciler.reconcile({ reason: 'startup' })
  eq(report.adopted, 2)
  eq(s.registry.getDoc(d1).status, 'active', 'processed engine doc adopts as active')
  eq(s.registry.getDoc(d1).source, 'orphan:1.md')
  const audit = s.registry.listAudit({ action: 'registry_adopted' })
  eq(audit.total, 1, 'adoption must be one summary audit row')
  eq(audit.items[0].detail.count, 2)
  // 幂等：再对账不重复收养
  const again = await s.reconciler.reconcile({ reason: 'periodic' })
  eq(again.adopted, 0)
  eq(again.divergences.length, 0, 'no divergence after adoption')
  eq(s.reconciler.lastReport().reason, 'periodic')
})

await check('缺失：注册表 active、引擎无 → missing + divergence', async () => {
  const s = await makeStack()
  s.registry.ensureDoc({ docId: 'doc-gone', source: 'gone.md', title: 'G' })
  s.registry.touchStatus('doc-gone', 'active')
  const report = await s.reconciler.reconcile({ reason: 'startup' })
  eq(report.missingMarked, 1)
  eq(s.registry.getDoc('doc-gone').status, 'missing')
  ok(report.divergences.some((d) => d.kind === 'missing-in-engine' && d.docId === 'doc-gone'))
})

await check('残留：注册表 retired、引擎仍有 → 对账补删意图（reconcile 优先级）', async () => {
  const s = await makeStack()
  const d1 = await seedEngineDoc(s.engine, 'leftover.md')
  s.registry.ensureDoc({ docId: d1, source: 'leftover.md', title: 'L' })
  s.registry.retireDoc(d1, 'test')
  const report = await s.reconciler.reconcile({ reason: 'startup' })
  eq(report.deleteQueued, 1)
  ok(report.divergences.some((d) => d.kind === 'retired-in-engine'))
  const del = s.intents.list().find((i) => i.kind === 'delete_doc')
  ok(del, 'reconcile must queue a delete intent')
  eq(del.priority, 'reconcile')
  eq(del.params.docId, d1)
  // 同一文档再次对账：进行中意图去重，不重复提交
  const again = await s.reconciler.reconcile({ reason: 'periodic' })
  eq(again.deleteQueued, 0, 'in-flight intent must exempt re-queue')
})

await check('豁免：进行中意图覆盖的文档不参与对账（不误判 missing/不收养）', async () => {
  const s = await makeStack()
  // 摄入意图已发出（docId 已知、尚未落注册表）→ 引擎有此文档
  const it = s.intents.submitText({ text: '正文', source: 'text:cov', title: 'C' })
  await s.intents.tickNow(); await s.intents.tickNow() // issued，docId 已知
  const coveredDocId = s.intents.get(it.id).docId
  ok(s.engine._state.docs.has(coveredDocId), 'engine must have the in-flight doc')
  const report = await s.reconciler.reconcile({ reason: 'startup' })
  eq(report.adopted, 0, 'in-flight doc must not be adopted')
  eq(report.missingMarked, 0)
  // 注册表 active 文档有进行中 replace 意图 → 不标 missing
  s.registry.ensureDoc({ docId: 'doc-old', source: 'old.md', title: 'O' })
  s.registry.touchStatus('doc-old', 'active')
  s.intents.submitText({ text: 'x', source: 'old.md', title: 'O', replacesDocId: 'doc-old' })
  const r2 = await s.reconciler.reconcile({ reason: 'periodic' })
  eq(r2.missingMarked, 0, 'doc covered by in-flight replace must not be marked missing')
})

await check('分页：引擎文档超过一页时全量对账', async () => {
  const s = await makeStack()
  const ids = []
  for (let i = 0; i < 25; i++) ids.push(await seedEngineDoc(s.engine, 'p-' + i + '.md'))
  const report = await s.reconciler.reconcile({ reason: 'startup' })
  eq(report.engineDocs, 25)
  eq(report.adopted, 25)
  for (const id of ids) ok(s.registry.getDoc(id), 'doc ' + id + ' must be adopted')
})

await check('start/stop：周期核验定时回调 onReport', async () => {
  const s = await makeStack()
  await seedEngineDoc(s.engine, 'timer.md')
  const rec = s.lib.reconciler({ engine: s.engine, registry: s.registry, intents: s.intents, logger: () => {}, scanIntervalMs: 150 })
  let fired = 0
  rec.start(() => { fired++ })
  await new Promise((r) => setTimeout(r, 500))
  rec.stop()
  ok(fired >= 2, 'periodic reconcile must fire, got ' + fired)
  // 周期实例已收养 timer.md；停止后再出现的新文档由手动对账收养
  const d2 = await seedEngineDoc(s.engine, 'timer2.md')
  const report = await s.reconciler.reconcile({ reason: 'manual' })
  eq(report.adopted, 1)
  ok(s.registry.getDoc(d2), 'new doc must be adopted by manual reconcile')
})

const failed = finish()
if (process.argv[1] && import.meta.url === (await import('node:url')).pathToFileURL(process.argv[1]).href) process.exit(failed ? 1 : 0)
