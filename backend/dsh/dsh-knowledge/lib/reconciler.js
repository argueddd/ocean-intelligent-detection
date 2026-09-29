/**
 * dsh-knowledge v2 · 收敛器 —— 让引擎持续逼近注册表意图。
 *
 * 职责（对应 v2 重构核心反转）：
 *  1. 启动全量对账：引擎有/注册表无 → 收养（adopt）；
 *     注册表 active/processing 但引擎无且无进行中意图 → 标 missing（进入待办）；
 *     注册表 retired 但引擎仍在 → 补删意图（对账补删，低优先级）。
 *  2. 周期核验：收敛度报告（引擎≡注册表），分歧进 lastReport 供仪表盘。
 *  3. 与意图账本联动：有进行中意图的文档跳过对账（避免误判）。
 *
 * 引擎列表分页扫描：page_size=100，无上限页数限制（对账要见全集）。
 */

export function createReconciler({ engine, registry, intents, logger = () => {}, scanIntervalMs = 10 * 60 * 1000, pageSize = 100 }) {
  let timer = null
  let lastReport = null

  async function scanAllEngineDocs() {
    const docs = []
    let page = 1
    let total = null
    for (;;) {
      const lr = await engine.listDocuments({ page, page_size: pageSize })
      const batch = (lr && lr.documents) || []
      docs.push(...batch)
      total = lr && lr.pagination ? lr.pagination.total_count : docs.length
      if (docs.length >= total || batch.length === 0) break
      page++
      if (page > 200) break // 防御上限：200 页 × pageSize
    }
    return { docs, total }
  }

  /** 进行中意图覆盖的 docId/replacesDocId 集合（对账豁免）。 */
  function coveredByIntents() {
    const set = new Set()
    for (const i of intents.list()) {
      if (i.status === 'verified' || i.status === 'failed' || i.status === 'stuck') continue
      if (i.params && i.params.docId) set.add(i.params.docId)
      if (i.params && i.params.replacesDocId) set.add(i.params.replacesDocId)
      if (i.docId) set.add(i.docId)
      if (i.newDocId) set.add(i.newDocId)
    }
    return set
  }

  /** 全量对账（启动与手动触发）。返回报告。 */
  async function reconcile({ reason = 'startup' } = {}) {
    const { docs, total } = await scanAllEngineDocs()
    const engineIds = new Set(docs.map((d) => d.id))
    const covered = coveredByIntents()
    const report = {
      ts: new Date().toISOString(), reason,
      engineDocs: total, adopted: 0, missingMarked: 0, deleteQueued: 0, divergences: [],
    }
    // 1. 引擎有 → 注册表无：收养（进行中意图覆盖的文档等意图自己落档，不收养）
    const adoptable = []
    for (const d of docs) {
      if (registry.getDoc(d.id)) continue
      if (covered.has(d.id)) continue
      adoptable.push({ id: d.id, file_path: d.file_path, status: d.status })
    }
    if (adoptable.length) report.adopted = registry.adoptDocs(adoptable, 'reconciler:' + reason)
    // 2. 注册表 vs 引擎
    for (const doc of registry.listDocs({})) {
      if (covered.has(doc.doc_id)) continue
      if (doc.status === 'retired' || doc.status === 'outdated') {
        if (engineIds.has(doc.doc_id)) {
          intents.submitReconcileDelete({ docId: doc.doc_id, source: doc.source, reason: '对账：注册表已退役但引擎仍在' })
          report.deleteQueued++
          report.divergences.push({ docId: doc.doc_id, kind: 'retired-in-engine' })
        }
        continue
      }
      if (!engineIds.has(doc.doc_id)) {
        registry.touchStatus(doc.doc_id, 'missing', '对账发现引擎中不存在')
        report.missingMarked++
        report.divergences.push({ docId: doc.doc_id, kind: 'missing-in-engine' })
      }
    }
    lastReport = report
    logger('reconcile(' + reason + '): engine=' + total + ' adopted=' + report.adopted + ' missing=' + report.missingMarked + ' deleteQueued=' + report.deleteQueued)
    return report
  }

  return {
    reconcile,
    start(onReport) {
      if (timer) return
      const run = () => reconcile({ reason: 'periodic' }).then((r) => { if (onReport) onReport(r) }).catch((e) => logger('reconcile error: ' + (e && e.message)))
      timer = setInterval(run, scanIntervalMs)
      if (typeof timer.unref === 'function') timer.unref()
    },
    stop() { if (timer) { clearInterval(timer); timer = null } },
    lastReport: () => lastReport,
  }
}
