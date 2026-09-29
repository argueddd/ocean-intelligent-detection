/** 契约测试 · ops（诊断运营指标 + 知识库运营总览口径）。 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { makeStack, makeRunner, ok, eq } from './harness.mjs'

const { check, finish } = makeRunner('contract-ops')
const { createFeedbackLedger } = await import('../lib/feedback.js')
const { createDiagnosisLedger } = await import('../lib/diagnosis.js')
const { createOpsMetrics } = await import('../lib/ops.js')

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'kb-ops-'))

await check('运营指标：重复率/聚类/批准拒绝/执行/判定/重出/人工/层级分布', async () => {
  const dir = tmp()
  const f = createFeedbackLedger({ dir })
  const past = '2026-09-01T00:00:00.000Z'
  // 同一问题的两条反馈（类型不同 → 账本去重不拦截，构成相似组 q-1）
  const fb1 = f.record({ rating: 'negative', issue_type: 'wrong_source', query_id: 'q-1', query: '绩效D影响', note: 'a', created_at: past })
  const fb2 = f.record({ rating: 'negative', issue_type: 'missing_content', query_id: 'q-1', query: '绩效D影响', note: 'b', created_at: past })
  const fb3 = f.record({ rating: 'negative', issue_type: 'wrong_entity', query_id: 'q-2', query: '报销流程', note: 'c', created_at: past })

  const d = createDiagnosisLedger({ dir, feedback: f })
  const row = d.submitCases({ cases: [
    // A：相似组（q-1 两条）合并进同一案例；建议类动作 → needs_manual_review
    { feedback_ids: [fb1.feedback_id, fb2.feedback_id], issue_type: 'wrong_source', cause_layer: 'answer_generation',
      action: 'manual_review', payload: { advice: ['【不改】内容正确，回答生成问题'] }, validation: { ok: true } },
    // B：可执行提案 → 批准 → 成功 + 用户判定已解决
    { feedback_ids: [fb3.feedback_id], issue_type: 'wrong_entity', cause_layer: 'graph',
      action: 'edit_entity', payload: { entity_name: '报销', updates: { description: 'x' } }, validation: { ok: true } },
    // C：可执行提案 → 拒绝
    { feedback_ids: [fb3.feedback_id], issue_type: 'missing_content', cause_layer: 'retrieval',
      action: 'edit_relation', payload: { src: 'A', tgt: 'B', updates: { description: 'y' } }, validation: { ok: true } },
  ] })
  const [pa, pb, pc] = row.proposals
  eq(pa.status, 'needs_manual_review')
  eq(pb.status, 'awaiting_approval')
  d.setProposalStatus(pb.proposal_id, 'approved')
  d.setProposalStatus(pb.proposal_id, 'succeeded', { verification: { refs_changed: false, answer_changed: false, user_verdict: { verdict: 'resolved', note: '' } } })
  d.setProposalStatus(pc.proposal_id, 'rejected')

  // 修复成功后同一问题（q-2）再次收到负反馈：先标记原反馈已处理（否则被账本去重拦截），再提交复发反馈
  f.update(fb3.feedback_id, { status: 'reviewed' })
  f.record({ rating: 'negative', issue_type: 'wrong_entity', query_id: 'q-2', query: '报销流程', note: '又坏了', created_at: '2099-01-01T00:00:00.000Z' })

  const ops = createOpsMetrics({ feedback: f, diagnoses: d })
  const m = ops.compute()

  eq(m.feedback_total, 4)
  eq(m.feedback_dup_rate.num, 2, '重复 = fb2 + 复发 fb4')
  eq(m.feedback_dup_rate.den, 4)
  ok(Math.abs(m.feedback_dup_rate.value - 0.5) < 1e-9)

  eq(m.clustering_rate.num, 1, '两个相似组中 q-1 组被案例 A 合并处理')
  eq(m.clustering_rate.den, 2)

  eq(m.proposal_approve_rate.num, 1, 'B 批准（succeeded 归批准）')
  eq(m.proposal_approve_rate.den, 2, '已决策 = B + C')
  eq(m.proposal_reject_rate.num, 1)
  eq(m.proposal_reject_rate.den, 2)

  eq(m.execution_success_rate.num, 1)
  eq(m.execution_success_rate.den, 1)

  eq(m.verdict_resolved_rate.num, 1)
  eq(m.verdict_resolved_rate.den, 1)
  eq(m.verdict_unresolved_rate.value, 0)

  eq(m.recurrence_rate.num, 1, 'B 成功后 q-2 再次负反馈')
  eq(m.recurrence_rate.den, 1)

  eq(m.manual_review_rate.num, 1, 'A 为 needs_manual_review')
  eq(m.manual_review_rate.den, 3, 'agent 案例共 3 个')

  // 处置口径：A 被人工「不采用」关闭后仍计入分子（建议类动作是案例固有属性）
  d.setProposalStatus(pa.proposal_id, 'rejected')
  const m2 = ops.compute()
  eq(m2.manual_review_rate.num, 1, '被拒绝的建议类案例仍计入')
  eq(m2.manual_review_rate.den, 3)

  eq(m.layer_distribution.answer_generation, 1)
  eq(m.layer_distribution.graph, 1)
  eq(m.layer_distribution.retrieval, 1)
})

await check('运营指标：空数据全为 null（不臆造 0%）', async () => {
  const dir = tmp()
  const f = createFeedbackLedger({ dir })
  const d = createDiagnosisLedger({ dir, feedback: f })
  const m = createOpsMetrics({ feedback: f, diagnoses: d }).compute()
  eq(m.feedback_total, 0)
  for (const key of ['feedback_dup_rate', 'clustering_rate', 'proposal_approve_rate', 'proposal_reject_rate',
    'execution_success_rate', 'verdict_resolved_rate', 'verdict_unresolved_rate', 'recurrence_rate', 'manual_review_rate']) {
    eq(m[key].value, null, key + ' 分母为 0 → null')
  }
  eq(Object.keys(m.layer_distribution).length, 0)
})

await check('运营总览：知识资产 / 检索信号 / 知识变更', async () => {
  const s = await makeStack()
  const now = new Date().toISOString()
  // 文档：2 篇 active（同主题）+ 1 篇 failed
  s.registry.ensureDoc({ docId: 'doc-1', source: 'a.md', title: 'A', topic: '资产和财务' })
  s.registry.ensureDoc({ docId: 'doc-2', source: 'b.md', title: 'B', topic: '资产和财务' })
  s.registry.ensureDoc({ docId: 'doc-3', source: 'c.md', title: 'C', topic: '人力资源' })
  s.registry.touchStatus('doc-1', 'active')
  s.registry.touchStatus('doc-2', 'active')
  s.registry.touchStatus('doc-3', 'failed')
  // 检索：2 次命中 + 1 次零命中 + 1 次重复查询
  s.curator.logQuery({ query: '高频问题', references: [{ file: 'x' }], ts: now })
  s.curator.logQuery({ query: '高频问题', references: [{ file: 'x' }], ts: now })
  s.curator.logQuery({ query: '零命中问题', references: [], ts: now })
  // 变更审计：1 入库 + 1 图谱编辑
  s.registry.audit({ actor: 'web', action: 'ingest', target: 'doc-1', detail: {} })
  s.registry.audit({ actor: 'agent', action: 'entity_edit', target: 'E', detail: {} })

  const ops = (await import('../lib/ops.js')).createOpsMetrics({ feedback: s.feedback, diagnoses: s.diagnoses, registry: s.registry, curator: s.curator })
  const o = ops.computeOverview({ days: 7 })

  eq(o.documents.total, 3)
  eq(o.documents.failed, 1)
  eq(o.documents.added, 3, '近 7 天创建的文档')
  eq(o.documents.by_topic[0].topic, '资产和财务')
  eq(o.documents.by_topic[0].count, 2)

  eq(o.queries.total, 3)
  eq(o.queries.zero_ref, 1)
  ok(Math.abs(o.queries.zero_ref_rate - 1 / 3) < 1e-4, '零命中率 1/3（toFixed(4) 截断容差）')
  eq(o.queries.top_queries[0].query, '高频问题')
  eq(o.queries.top_queries[0].count, 2)

  ok(o.changes.total >= 2, '审计含显式 2 条变更（另有文档登记流水）')
  eq(o.changes.by_class['入库'], 4, '3 条 ensureDoc 登记（system:ingest）+ 1 条显式')
  eq(o.changes.by_class['图谱编辑'], 1)
  eq(o.changes.by_actor.web, 1)
  eq(o.changes.by_actor.agent, 1)
  eq(o.changes.by_actor.system, 3)
})

const failed = finish()
if (process.argv[1] && import.meta.url === (await import('node:url')).pathToFileURL(process.argv[1]).href) process.exit(failed ? 1 : 0)
