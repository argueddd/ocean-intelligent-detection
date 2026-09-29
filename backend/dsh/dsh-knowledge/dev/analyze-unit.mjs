/**
 * dsh-knowledge · analyze 单元测试（假引擎，不触网）。
 * 覆盖：名称规范化聚类、缺口三分类（重探分诊）、周报指标计算。
 * 运行：node dev/analyze-unit.mjs
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createCurator } from '../lib/curator.js'
import { createAnalyzer, normalizeName } from '../lib/analyze.js'

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'kb-analyze-unit-'))
process.env.KB_DATA_DIR = tmp

const results = []
async function check(name, fn) {
  try { await fn(); results.push(['PASS', name]) } catch (e) { results.push(['FAIL', name + ' :: ' + (e && e.message)]) }
}

// 假引擎：按 query 内容返回不同检索结果（模拟三分类场景）
function makeWorld() {
  // 每个 world 独立数据目录，避免跨用例串场
  process.env.KB_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'kb-analyze-world-'))
  const engine = {
    async queryData(payload) {
      const q = String(payload.query || '')
      if (q.includes('波动')) return { status: 'success', data: { chunks: [{ content: 'x', file_path: 'a.docx' }], entities: [], relationships: [], references: [{ file_path: 'a.docx' }] } }
      if (q.includes('实体在')) return { status: 'success', data: { chunks: [], entities: [{ entity_name: 'E1' }], relationships: [], references: [] } }
      if (q.includes('不存在')) return { status: 'success', data: { chunks: [], entities: [], relationships: [], references: [] } }
      return { status: 'success', data: { chunks: [], entities: [], relationships: [], references: [] } }
    },
    async sourceConflicts() { return { conflicts: [{ canonical_source_key: 'x.docx', candidate_count: 2, sample_doc_ids: ['a', 'b'] }], next_cursor: null } },
    async statusCounts() { return { status_counts: { processed: 1800, failed: 3 } } },
  }
  const registry = {
    audit: () => null,
    stats: () => ({ by_status: { active: 10, failed: 1 }, failed: [{ id: 'd1', title: '坏文档', reason: 'parse error' }] }),
  }
  const curator = createCurator({ registry })
  const analyzer = createAnalyzer({ engine, curator, registry })
  return { engine, curator, analyzer }
}

await check('normalizeName：全半角括号/空白/标点统一', () => {
  const a = normalizeName('员工休假管理办法（2025年修订）')
  const b = normalizeName('员工休假管理办法(2025年修订)')
  const c = normalizeName('员工休假管理办法 (2025年修订)！')
  if (a !== b || a !== c) throw new Error(a + ' / ' + b + ' / ' + c)
  if (normalizeName('A.doc') === normalizeName('B.doc')) throw new Error('distinct names merged')
  console.log('  → ' + a)
})

await check('重复实体候选：名称变体聚类（假 KV：文档→实体名索引）', async () => {
  const w = makeWorld()
  const kvDir = path.join(tmp, 'fake-rag-storage')
  fs.mkdirSync(kvDir, { recursive: true })
  fs.writeFileSync(path.join(kvDir, 'kv_store_full_entities.json'), JSON.stringify({
    'doc-aaa': { entity_names: ['员工休假管理办法（2025年修订）', '差旅费管理办法'] },
    'doc-bbb': { entity_names: ['员工休假管理办法(2025年修订)'] },
    'doc-ccc': { entity_names: ['员工休假管理办法(2025年修订) ', '唯一实体'] },
  }))
  process.env.KB_RAG_STORAGE = kvDir
  const r = await w.analyzer.analyzeDupEntities()
  if (r.candidates !== 1) throw new Error('expected 1 candidate group, got ' + r.candidates)
  if (r.items[0].count !== 3) throw new Error('expected 3 variants: ' + JSON.stringify(r.items[0]))
  if (r.source !== 'kv-entity-names') throw new Error('expected kv-entity-names source, got ' + r.source)
  console.log('  → ' + r.items[0].names.join(' ≈ '))
})

await check('缺口三分类：a-missing / b-retrieval-jitter / b-missing-text', async () => {
  const w = makeWorld()
  const t = new Date().toISOString()
  w.curator.logQuery({ query: '波动问题', mode: 'mix', references: [], ts: t })
  w.curator.logQuery({ query: '实体在但文不在的问题', mode: 'mix', references: [], ts: t })
  w.curator.logQuery({ query: '完全不存在的问题', mode: 'mix', references: [], ts: t })
  w.curator.logQuery({ query: '有引用的正常问题', mode: 'mix', references: [{ file: 'x' }], ts: t })
  const g = await w.analyzer.analyzeGaps({ maxProbes: 10 })
  if (g.zero_ref_total !== 3) throw new Error('zero-ref count: ' + g.zero_ref_total)
  const cls = g.by_class
  if (cls['b-retrieval-jitter'] !== 1 || cls['b-missing-text'] !== 1 || cls['a-missing'] !== 1) throw new Error('classes: ' + JSON.stringify(cls))
  const a = g.items.find((i) => i.class === 'a-missing')
  if (!a.suggested.includes('采购')) throw new Error('a-missing suggestion: ' + a.suggested)
  console.log('  → ' + JSON.stringify(cls))
})

await check('周报：检索信号汇总（总量 / 零命中率 / 高频查询）', () => {
  const w = makeWorld()
  const ts = new Date().toISOString()
  w.curator.logQuery({ query: 'q1', mode: 'mix', references: [], ts })
  w.curator.logQuery({ query: 'q1', mode: 'mix', references: [], ts })
  w.curator.logQuery({ query: 'q2', mode: 'mix', references: [{ file: 'x' }], ts })
  const r = w.analyzer.buildReport({ days: 1 })
  if (r.queries.total !== 3 || Math.abs(r.queries.zero_ref_rate - 2 / 3) > 0.0001) throw new Error('query stats: ' + JSON.stringify(r.queries))
  if (r.queries.top_queries[0].query !== 'q1' || r.queries.top_queries[0].count !== 2) throw new Error('top queries: ' + JSON.stringify(r.queries.top_queries))
  if (r.health.failed_docs !== 1) throw new Error('health: ' + JSON.stringify(r.health))
  console.log('  → 零命中率 ' + (r.queries.zero_ref_rate * 100).toFixed(0) + '% ｜ 高频 ' + r.queries.top_queries[0].query + '×' + r.queries.top_queries[0].count)
})

console.log('\n===== analyze unit results (' + tmp + ') =====')
let failed = 0
for (const [s, n] of results) {
  if (s === 'FAIL') failed++
  console.log(' ' + s + '  ' + n)
}
process.exit(failed ? 1 : 0)
