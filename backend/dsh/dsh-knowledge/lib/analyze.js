/**
 * dsh-knowledge · analyze（五类健康分析 + 周报）。
 *
 * 在 engine/curator/registry 之上提供运维的"眼睛"：
 *  - source_conflicts：引擎源冲突清单（同 source 多版本并存）
 *  - failed_docs：失败文档与抽取状态
 *  - dup_entities：重复实体候选（活库 GraphML 全量实体名按规范化名称聚类，需 KB_RAG_STORAGE 宿主路径配置）
 *  - gaps：检索缺口三分类（query_log 零命中查询 → 重探 /query/data 分诊）
 *      a-missing       知识不存在 → 知识采购（调研后 text_ingest 验证入库）
 *      b-retrieval-jitter 同参数重试即命中 → 检索波动，观察
 *      b-missing-text  实体在、条文不在 → 描述增强/补条文提案（entity_edit 或 text_ingest）
 *  - report：周报/月报（检索信号 + 健康）
 *
 * 全部只读，不产生知识变更；报告落 reports/analysis-*.md/.json。
 */

import fs from 'node:fs'
import path from 'node:path'
import readline from 'node:readline'
import { dataDir } from './registry.js'

/** 名称规范化：小写、去空白、统一全半角括号/常见标点（重复实体候选聚类用）。 */
export function normalizeName(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/[（]/g, '(')
    .replace(/[）]/g, ')')
    .replace(/[【]/g, '[')
    .replace(/[】]/g, ']')
    .replace(/[《]/g, '<')
    .replace(/[》]/g, '>')
    .replace(/[：:]/g, ':')
    .replace(/[，,]/g, ',')
    .replace(/[。.；;！!？?]/g, '')
    .replace(/["'“”‘’]/g, '')
}

export function createAnalyzer({ engine, curator, registry = null, log = () => {} } = {}) {
  const dir = dataDir()
  const reportsDir = path.join(dir, 'reports')

  // ---------------------------------------------------------------- 源冲突

  async function analyzeSourceConflicts() {
    let conflicts = []
    let error = null
    try {
      const r = await engine.sourceConflicts({ limit: 100 })
      conflicts = (r && Array.isArray(r.conflicts)) ? r.conflicts : []
    } catch (e) {
      error = String(e && e.message ? e.message : e)
    }
    return {
      total: conflicts.length,
      error,
      items: conflicts.slice(0, 30).map((c) => ({
        source: c.canonical_source_key,
        candidates: c.candidate_count ?? null,
        samples: (c.sample_doc_ids || []).slice(0, 3),
      })),
    }
  }

  // ---------------------------------------------------------------- 失败文档

  async function analyzeFailedDocs() {
    let engineCounts = null
    try { engineCounts = await engine.statusCounts() } catch (e) { /* ignore */ }
    const stats = registry ? registry.stats() : { failed: [] }
    return {
      failed: (stats.failed || []).map((d) => ({ id: d.id, title: d.title, reason: d.reason || '' })),
      engine_status_counts: engineCounts && engineCounts.status_counts ? engineCounts.status_counts : null,
      registry_status: stats.by_status || {},
    }
  }

  // ---------------------------------------------------------------- 重复实体候选

  /** 流式提取 GraphML 全部节点名（实体名=节点 id；217MB/10.9 万节点 ~1-2s，不整体载入内存）。 */
  function extractGraphmlNames(storage) {
    const p = path.join(storage, 'graph_chunk_entity_relation.graphml')
    if (!fs.existsSync(p)) return Promise.resolve(null)
    return new Promise((resolve, reject) => {
      const names = []
      const rl = readline.createInterface({ input: fs.createReadStream(p, { encoding: 'utf8' }), crlfDelay: Infinity })
      rl.on('line', (line) => {
        if (line.startsWith('<node ')) {
          const m = /id="([^"]*)"/.exec(line)
          if (m) names.push(m[1])
        }
      })
      rl.on('close', () => resolve(names))
      rl.on('error', reject)
    })
  }

  /**
   * 重复实体候选：全量实体名（GraphML 优先；兜底从 kv_store_full_entities 的 entity_names 并集取——
   * 注意该 KV 是"文档→实体名"删除索引，键是 doc-<hash> 而非实体名）按规范化名称聚类，
   * 找出"同名变体"（全半角括号/空白/大小写差异等）。需 KB_RAG_STORAGE。
   */
  async function analyzeDupEntities({ topN = 50 } = {}) {
    const storage = process.env.KB_RAG_STORAGE
    if (!storage) {
      return { configured: false, note: '未配置 KB_RAG_STORAGE（宿主路径），跳过重复实体扫描', total: 0, items: [] }
    }
    let names = null
    let source = 'graphml'
    try {
      names = await extractGraphmlNames(storage)
    } catch (e) { /* 换 KV 兜底 */ }
    if (names === null || !names.length) {
      const kvPath = path.join(storage, 'kv_store_full_entities.json')
      if (!fs.existsSync(kvPath)) return { configured: true, note: 'GraphML 与 KV 均不可读（' + storage + '）', total: 0, items: [] }
      try {
        const kv = JSON.parse(fs.readFileSync(kvPath, 'utf8'))
        const set = new Set()
        for (const rec of Object.values(kv)) {
          if (rec && Array.isArray(rec.entity_names)) for (const n of rec.entity_names) set.add(n)
        }
        names = [...set]
      } catch (e) { names = [] }
      source = 'kv-entity-names'
    }
    const groups = new Map() // normalized -> [raw names]
    for (const name of names) {
      const norm = normalizeName(name)
      if (!norm) continue
      if (!groups.has(norm)) groups.set(norm, [])
      groups.get(norm).push(name)
    }
    const items = []
    for (const [norm, raws] of groups.entries()) {
      if (raws.length < 2) continue
      items.push({ normalized: norm, count: raws.length, names: raws.slice(0, 5) })
    }
    items.sort((a, b) => b.count - a.count || (a.normalized < b.normalized ? -1 : 1))
    return {
      configured: true,
      note: '',
      source,
      entities_total: names.length,
      candidates: items.length,
      items: items.slice(0, topN),
    }
  }

  // ---------------------------------------------------------------- 检索缺口

  /** 归一化查询文本（去空白/标点，聚类去重用）。 */
  const normQuery = (q) => String(q || '').replace(/[\s，。！？!?,:：；;.]+/g, '')

  /**
   * 缺口三分类：取 query_log 最近零命中查询（去重），重探 /query/data 分诊。
   * maxProbes 限制重探次数（每次 ~2-5s，只读）。
   */
  async function analyzeGaps({ windowHours = 24 * 7, maxProbes = 10 } = {}) {
    const since = new Date(Date.now() - windowHours * 3600 * 1000).toISOString()
    const all = curator.listQueries({ limit: 2000, since })
    const zeroRef = all.filter((q) => !Array.isArray(q.references) || q.references.length === 0)
    // 去重：同一归一化查询只探一次，保留最近时间
    const seen = new Map()
    for (const q of zeroRef) {
      const key = normQuery(q.query)
      if (!key) continue
      if (!seen.has(key)) seen.set(key, q)
    }
    const uniq = [...seen.values()].slice(0, maxProbes)
    const items = []
    for (const q of uniq) {
      let probe = null
      let error = null
      try {
        const r = await engine.queryData({ query: q.query, mode: 'mix' })
        const d = r && r.data ? r.data : {}
        probe = {
          chunks: Array.isArray(d.chunks) ? d.chunks.length : 0,
          entities: Array.isArray(d.entities) ? d.entities.length : 0,
          files: [...new Set((Array.isArray(d.references) ? d.references : []).map((x) => x && x.file_path).filter(Boolean))].slice(0, 5),
        }
      } catch (e) {
        error = String(e && e.message ? e.message : e)
      }
      let klass = 'probe-error'
      let suggested = ''
      if (error) {
        klass = 'probe-error'
        suggested = '重探失败，人工复核'
      } else if (probe.chunks > 0) {
        klass = 'b-retrieval-jitter'
        suggested = '同参数重试即命中（检索波动或知识已后补），观察趋势，无需立即处置'
      } else if (probe.entities > 0) {
        klass = 'b-missing-text'
        suggested = '实体在、条文不在 → 描述增强提案（entity_edit）或补条文（text_ingest）'
      } else {
        klass = 'a-missing'
        suggested = '知识不存在 → 采购清单：联网调研后 text_ingest 验证入库'
      }
      items.push({
        query: q.query,
        ts: q.ts,
        session_id: q.session_id,
        probe,
        class: klass,
        suggested,
      })
    }
    const byClass = {}
    for (const it of items) byClass[it.class] = (byClass[it.class] || 0) + 1
    return {
      window_hours: windowHours,
      zero_ref_total: zeroRef.length,
      probed: items.length,
      by_class: byClass,
      items,
    }
  }

  // ---------------------------------------------------------------- 编排

  /** 五类分析 → 结构化报告。sections 为空=全量。 */
  async function analyze({ sections = null, gapMaxProbes = 10 } = {}) {
    const want = sections && Array.isArray(sections) && sections.length ? new Set(sections) : null
    const report = { generated_at: new Date().toISOString(), sections: {} }
    if (!want || want.has('source_conflicts')) report.sections.source_conflicts = await analyzeSourceConflicts()
    if (!want || want.has('failed_docs')) report.sections.failed_docs = await analyzeFailedDocs()
    if (!want || want.has('dup_entities')) report.sections.dup_entities = await analyzeDupEntities()
    if (!want || want.has('gaps')) report.sections.gaps = await analyzeGaps({ maxProbes: gapMaxProbes })
    report.summary = {
      conflicts: report.sections.source_conflicts ? report.sections.source_conflicts.total : null,
      failed_docs: report.sections.failed_docs ? report.sections.failed_docs.failed.length : null,
      dup_candidates: report.sections.dup_entities ? (report.sections.dup_entities.candidates ?? null) : null,
      gap_items: report.sections.gaps ? report.sections.gaps.zero_ref_total : null,
      gap_classes: report.sections.gaps ? report.sections.gaps.by_class : null,
    }
    return report
  }

  // ---------------------------------------------------------------- 报告落盘

  function renderMarkdown(report) {
    const s = report.sections
    const lines = ['# 知识库健康分析（' + report.generated_at + '）', '']
    if (s.source_conflicts) {
      const c = s.source_conflicts
      lines.push('## 1. 源冲突', '- 数量：' + c.total + (c.error ? '（读取失败：' + c.error + '）' : ''))
      for (const it of c.items) lines.push('- `' + it.source + '`（候选 ' + (it.candidates ?? '≥2') + '，样本 ' + (it.samples || []).join(', ') + '）')
      lines.push('')
    }
    if (s.failed_docs) {
      const f = s.failed_docs
      lines.push('## 2. 失败文档', '- 数量：' + f.failed.length + '｜引擎状态：' + JSON.stringify(f.engine_status_counts || {}))
      for (const d of f.failed) lines.push('- ' + d.title + (d.reason ? '（' + d.reason.slice(0, 80) + '）' : ''))
      lines.push('')
    }
    if (s.dup_entities) {
      const d = s.dup_entities
      lines.push('## 3. 重复实体候选', d.configured
        ? '- 实体总数：' + d.entities_total + '｜候选组：' + d.candidates + (d.note ? '｜' + d.note : '')
        : '- 跳过（' + d.note + '）')
      for (const it of d.items) lines.push('- ' + it.names.join(' ≈ ') + '（' + it.count + ' 个变体）')
      lines.push('')
    }
    if (s.gaps) {
      const g = s.gaps
      lines.push('## 4. 检索缺口（近 ' + Math.round(g.window_hours / 24) + ' 天）')
      lines.push('- 零命中查询：' + g.zero_ref_total + '｜重探：' + g.probed + '｜分类：' + JSON.stringify(g.by_class))
      lines.push('')
      lines.push('| 类别 | 查询 | 建议 |')
      lines.push('|---|---|---|')
      for (const it of g.items) {
        lines.push('| ' + it.class + ' | ' + it.query.replace(/\|/g, '/').slice(0, 60) + ' | ' + it.suggested + ' |')
      }
      lines.push('')
    }
    lines.push('> 分类语义：a-missing=知识不存在（采购）；b-retrieval-jitter=同参重试即命中（波动）；b-missing-text=实体在条文不在（描述增强/补条文）。')
    return lines.join('\n')
  }

  function saveReport(report) {
    fs.mkdirSync(reportsDir, { recursive: true })
    const date = new Date().toISOString().slice(0, 10)
    const p = path.join(reportsDir, 'analysis-' + date + '.md')
    fs.writeFileSync(p, renderMarkdown(report), 'utf8')
    fs.writeFileSync(p.replace(/\.md$/, '.json'), JSON.stringify(report, null, 2), 'utf8')
    return p
  }

  function listReports() {
    if (!fs.existsSync(reportsDir)) return []
    return fs.readdirSync(reportsDir)
      .filter((f) => f.endsWith('.json') && f.startsWith('analysis-'))
      .map((f) => {
        try { return JSON.parse(fs.readFileSync(path.join(reportsDir, f), 'utf8')) } catch (e) { return null }
      })
      .filter(Boolean)
      .sort((a, b) => (a.generated_at < b.generated_at ? 1 : -1))
  }

  // ---------------------------------------------------------------- 周报

  /** 周报/月报：检索信号 + 健康。全部只读。 */
  function buildReport({ days = 7 } = {}) {
    const since = new Date(Date.now() - days * 24 * 3600 * 1000).toISOString()
    const queries = curator.listQueries({ limit: 100000, since })
    const zeroRef = queries.filter((q) => !Array.isArray(q.references) || q.references.length === 0)
    const byQuery = new Map()
    for (const q of queries) {
      const key = normQuery(q.query).slice(0, 60) || '(空)'
      byQuery.set(key, (byQuery.get(key) || 0) + 1)
    }
    const topQueries = [...byQuery.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10)

    const latestAnalysis = listReports()[0] || null

    return {
      generated_at: new Date().toISOString(),
      days,
      queries: {
        total: queries.length,
        zero_ref: zeroRef.length,
        zero_ref_rate: queries.length ? +(zeroRef.length / queries.length).toFixed(4) : null,
        top_queries: topQueries.map(([q, n]) => ({ query: q, count: n })),
      },
      health: {
        failed_docs: registry ? registry.stats().failed.length : null,
        latest_analysis_gaps: latestAnalysis && latestAnalysis.sections && latestAnalysis.sections.gaps ? latestAnalysis.sections.gaps.by_class : null,
      },
    }
  }

  function renderReportMarkdown(report) {
    const lines = ['# 知识库运营周报（' + report.generated_at + '，近 ' + report.days + ' 天）', '']
    const q = report.queries
    lines.push('## 1. 检索信号', '- 查询总量：' + q.total + '｜零命中：' + q.zero_ref + (q.zero_ref_rate !== null ? '（' + (q.zero_ref_rate * 100).toFixed(1) + '%）' : ''))
    if (q.top_queries.length) {
      lines.push('- 高频查询：')
      for (const t of q.top_queries) lines.push('  - ' + t.query + ' × ' + t.count)
    }
    lines.push('')
    lines.push('## 2. 健康', '- 失败文档：' + (report.health.failed_docs ?? '–') + '｜最近分析缺口分类：' + JSON.stringify(report.health.latest_analysis_gaps || {}))
    lines.push('')
    return lines.join('\n')
  }

  function saveWeeklyReport(report) {
    fs.mkdirSync(reportsDir, { recursive: true })
    const date = new Date().toISOString().slice(0, 10)
    const p = path.join(reportsDir, 'weekly-' + date + '.md')
    fs.writeFileSync(p, renderReportMarkdown(report), 'utf8')
    fs.writeFileSync(p.replace(/\.md$/, '.json'), JSON.stringify(report, null, 2), 'utf8')
    return p
  }

  /** 历史周报列表，最新在前。 */
  function listWeeklyReports() {
    if (!fs.existsSync(reportsDir)) return []
    return fs.readdirSync(reportsDir)
      .filter((f) => f.endsWith('.json') && f.startsWith('weekly-'))
      .map((f) => {
        try { return JSON.parse(fs.readFileSync(path.join(reportsDir, f), 'utf8')) } catch (e) { return null }
      })
      .filter(Boolean)
      .sort((a, b) => (a.generated_at < b.generated_at ? 1 : -1))
  }

  return {
    normalizeName,
    analyzeSourceConflicts,
    analyzeFailedDocs,
    analyzeDupEntities,
    analyzeGaps,
    analyze,
    renderMarkdown,
    saveReport,
    listReports,
    buildReport,
    renderReportMarkdown,
    saveWeeklyReport,
    listWeeklyReports,
  }
}
