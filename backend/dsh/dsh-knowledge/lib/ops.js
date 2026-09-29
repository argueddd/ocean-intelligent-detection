/**
 * dsh-knowledge · ops（知识库运营指标）。
 *
 * 从反馈账本与诊断账本计算"越用越准"运营指标（全部只读、确定性）：
 *  - 负反馈重复率：同一问题（query_id 或归一化问题原文）的多条负反馈占比
 *  - 相似问题聚类准确率：相似反馈组中被同一诊断案例合并处理的比例
 *  - 提案批准率 / 拒绝率：已决策提案中批准与拒绝的占比
 *  - 提案执行成功率：已执行提案中成功的占比
 *  - 用户确认解决率 / 仍有问题率：用户复核判定中 resolved 与 unresolved 的占比
 *  - 问题重新出现率：执行成功的提案，其问题在成功后再次收到负反馈的比例
 *  - 模型输出需人工补充比例：智能诊断案例降级为 needs_manual_review 的占比
 *  - 问题层级分布：诊断案例按 cause_layer 的计数
 *
 * 指标口径：分母为 0 时 value 为 null（前端显示 –，不臆造 0%）。
 */

import { ADVISORY_ACTIONS } from './diagnosis.js'

/** 反馈的问题键：优先 query_id，退回归一化问题原文。 */
function feedbackKey(row) {
  if (row.query_id) return 'qid:' + row.query_id
  const norm = String(row.query || '').replace(/\s+/g, '').toLowerCase()
  return norm ? 'q:' + norm : 'fb:' + (row.feedback_id || '')
}

function rate(num, den) {
  if (!den) return { value: null, num, den }
  return { value: +(num / den).toFixed(4), num, den }
}

export function createOpsMetrics({ feedback, diagnoses, registry = null, curator = null }) {
  /** 计算全量运营指标。 */
  function compute() {
    const feedbackRows = feedback.list({ rating: 'negative', status: null, limit: 200 })
    const diagnosisRows = diagnoses.all()
    const proposals = diagnosisRows.flatMap((d) => (d.proposals || []).map((p) => ({ ...p, mode: d.mode })))
    const feedbackById = new Map(feedbackRows.map((r) => [r.feedback_id, r]))

    // ---- 负反馈重复率：同问题键的组中超出第一条的部分 / 总数
    const byKey = new Map()
    for (const r of feedbackRows) {
      const k = feedbackKey(r)
      if (!byKey.has(k)) byKey.set(k, [])
      byKey.get(k).push(r)
    }
    const dupCount = [...byKey.values()].reduce((a, rows) => a + Math.max(0, rows.length - 1), 0)
    const feedbackDupRate = rate(dupCount, feedbackRows.length)

    // ---- 相似问题聚类准确率：相似组（≥2 条）中被同一诊断案例合并处理（feedback_ids
    // 覆盖组内 ≥2 条）的比例——衡量诊断是否把相似问题归并到同一案例
    const agentProposalFids = proposals.map((p) => new Set(p.feedback_ids || []))
    const similarGroups = [...byKey.values()].filter((rows) => rows.length >= 2)
    const clustered = similarGroups.filter((rows) =>
      agentProposalFids.some((set) => rows.filter((r) => set.has(r.feedback_id)).length >= 2))
    const clusteringRate = rate(clustered.length, similarGroups.length)

    // ---- 提案批准 / 拒绝 / 执行成功率
    const decided = proposals.filter((p) => ['approved', 'executing', 'succeeded', 'failed', 'rejected'].includes(p.status))
    const approved = decided.filter((p) => p.status !== 'rejected')
    const rejected = decided.filter((p) => p.status === 'rejected')
    const executed = proposals.filter((p) => p.status === 'succeeded' || p.status === 'failed')
    const succeeded = proposals.filter((p) => p.status === 'succeeded')
    const approveRate = rate(approved.length, decided.length)
    const rejectRate = rate(rejected.length, decided.length)
    const execSuccessRate = rate(succeeded.length, executed.length)

    // ---- 用户复核判定
    const verdicts = proposals
      .map((p) => p.verification && p.verification.user_verdict ? p.verification.user_verdict : null)
      .filter(Boolean)
    const resolved = verdicts.filter((v) => v.verdict === 'resolved')
    const unresolved = verdicts.filter((v) => v.verdict === 'unresolved')
    const resolvedRate = rate(resolved.length, verdicts.length)
    const unresolvedRate = rate(unresolved.length, verdicts.length)

    // ---- 问题重新出现率：执行成功的提案，其问题在成功时间后又收到新负反馈
    const recurred = []
    for (const p of succeeded) {
      const successAt = p.updated_at || ''
      const keys = new Set((p.feedback_ids || []).map((id) => {
        const r = feedbackById.get(id)
        return r ? feedbackKey(r) : null
      }).filter(Boolean))
      if (!keys.size) continue
      const re = feedbackRows.some((r) =>
        !(p.feedback_ids || []).includes(r.feedback_id)
        && keys.has(feedbackKey(r))
        && (!successAt || r.created_at > successAt))
      if (re) recurred.push(p)
    }
    const recurrenceRate = rate(recurred.length, succeeded.length)

    // ---- 模型输出需人工补充比例：智能诊断案例中建议类动作或校验失败降级的占比。
    // 处置口径：被「不采用」关闭的案例仍计入分子——"需要人工"是案例固有属性
    // （建议类动作不可执行、校验失败缺证据），不随处置状态消失
    const agentProposals = proposals.filter((p) => p.mode === 'agent')
    const manual = agentProposals.filter((p) =>
      p.status === 'needs_manual_review'
      || ADVISORY_ACTIONS.includes(p.action)
      || (p.validation && p.validation.ok === false))
    const manualRate = rate(manual.length, agentProposals.length)

    // ---- 问题层级分布（智能诊断才有 cause_layer）
    const layers = {}
    for (const p of agentProposals) {
      if (p.cause_layer) layers[p.cause_layer] = (layers[p.cause_layer] || 0) + 1
    }

    return {
      generated_at: new Date().toISOString(),
      feedback_total: feedbackRows.length,
      feedback_dup_rate: feedbackDupRate,
      clustering_rate: clusteringRate,
      proposal_approve_rate: approveRate,
      proposal_reject_rate: rejectRate,
      execution_success_rate: execSuccessRate,
      verdict_resolved_rate: resolvedRate,
      verdict_unresolved_rate: unresolvedRate,
      recurrence_rate: recurrenceRate,
      manual_review_rate: manualRate,
      layer_distribution: layers,
    }
  }

  /** 审计动作 → 运营变更分类。 */
  const CHANGE_CLASS = {
    ingest: '入库', text_ingest: '入库',
    replace: '文档变更', replace_started: '文档变更', delete: '文档变更', retry: '文档变更',
    entity_create: '图谱编辑', entity_edit: '图谱编辑', entity_merge: '图谱编辑', entity_delete: '图谱编辑',
    relation_create: '图谱编辑', relation_edit: '图谱编辑', relation_delete: '图谱编辑',
  }

  /**
   * 知库运营总览（知识资产 / 检索信号 / 知识变更 / 健康快览）。
   * 与 compute() 的诊断域指标互补：这里统计知识库作为资产的规模、流量与变更活跃度。
   */
  function computeOverview({ days = 7 } = {}) {
    const since = new Date(Date.now() - days * 24 * 3600 * 1000).toISOString()

    // ---- 知识资产：规模 / 处理 / 新增 / 主题分布
    const docs = registry ? registry.listDocs({}) : []
    const active = docs.filter((d) => d.status !== 'retired')
    const processing = active.filter((d) => ['pending', 'processing', 'updating'].includes(d.status)).length
    const failed = active.filter((d) => d.status === 'failed').length
    const added = active.filter((d) => (d.created_at || '') >= since).length
    const topicCount = new Map()
    for (const d of active) {
      const t = d.topic || '未分类'
      topicCount.set(t, (topicCount.get(t) || 0) + 1)
    }
    const byTopic = [...topicCount.entries()]
      .map(([topic, count]) => ({ topic, count }))
      .sort((a, b) => b.count - a.count)

    // ---- 检索信号：近 N 天查询 / 零命中 / 高频
    const queries = curator ? curator.listQueries({ limit: 100000, since }) : []
    const zeroRef = queries.filter((q) => !Array.isArray(q.references) || q.references.length === 0)
    const byQuery = new Map()
    for (const q of queries) {
      const key = String(q.query || '').replace(/[\s，。！？!?,:：；;.]+/g, '').slice(0, 60) || '(空)'
      byQuery.set(key, (byQuery.get(key) || 0) + 1)
    }
    const topQueries = [...byQuery.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5)
      .map(([query, count]) => ({ query, count }))

    // ---- 知识变更：近 N 天审计流水按分类 / 来源统计
    const audit = registry ? registry.listAudit({ pageSize: 100000 }).items : []
    const recentAudit = audit.filter((a) => (a.ts || '') >= since)
    const byClass = { '入库': 0, '文档变更': 0, '图谱编辑': 0, '其他': 0 }
    const byActor = {}
    for (const a of recentAudit) {
      byClass[CHANGE_CLASS[a.action] || '其他']++
      byActor[a.actor || 'unknown'] = (byActor[a.actor || 'unknown'] || 0) + 1
    }

    return {
      generated_at: new Date().toISOString(),
      days,
      documents: { total: active.length, processing, failed, added, by_topic: byTopic },
      queries: {
        total: queries.length,
        zero_ref: zeroRef.length,
        zero_ref_rate: queries.length ? +(zeroRef.length / queries.length).toFixed(4) : null,
        top_queries: topQueries,
      },
      changes: { total: recentAudit.length, by_class: byClass, by_actor: byActor },
    }
  }

  return { compute, computeOverview }
}
