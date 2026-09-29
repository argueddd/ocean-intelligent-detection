/**
 * Feedback diagnosis and proposal ledger.
 *
 * Diagnosis groups open negative feedback into a small number of root-cause
 * candidates. It does not mutate LightRAG. A caller supplies the analysis
 * function so a Harness Agent can produce richer evidence while this module
 * owns limits, persistence, and proposal state.
 *
 * 两种诊断入口：
 *  - create()：规则聚类（模型不可用时的 fallback，mode='rules'）。
 *  - submitCases()：模型提交的结构化诊断案例（mode='agent'），每条案例
 *    先经 diagnosis-submit.js 的确定性校验（feedback/query/chunk/实体真实存在、
 *    action 与 payload 匹配），校验失败或建议类动作只能进入
 *    needs_manual_review（不可执行，只供人工处置参考）。
 *
 * 问题分层（cause_layer）：knowledge（知识内容）/ graph（图谱结构）/
 * retrieval（检索过程）/ answer_generation（回答生成）/ user_expectation（用户预期）。
 */
import crypto from 'node:crypto'
import path from 'node:path'
import { createAppendLog } from './store.js'

const MAX_FEEDBACK = 50
const MAX_CANDIDATES = 10
const MAX_RECOMMENDED = 3

/** 问题层枚举：决定修复方向（补知识 / 改图谱 / 调检索 / 调回答 / 对齐预期）。 */
export const CAUSE_LAYERS = Object.freeze(['knowledge', 'graph', 'retrieval', 'answer_generation', 'user_expectation'])

/** 可执行动作：payload 校验通过后走审批执行。 */
export const EXECUTABLE_ACTIONS = Object.freeze(['add_text', 'edit_entity', 'edit_relation', 'replace_document', 'review_document'])

/** 建议类动作：诊断结论可给出，但不可直接执行，状态固定 needs_manual_review。 */
export const ADVISORY_ACTIONS = Object.freeze(['reindex_document', 'adjust_chunking', 'adjust_retrieval', 'prompt_fix', 'manual_review'])

/** 诊断动作全集（模型提交的 action 必须落在其中）。 */
export const DIAGNOSIS_ACTIONS = Object.freeze([...EXECUTABLE_ACTIONS, ...ADVISORY_ACTIONS])

function keyFor(row) {
  return row.issue_type || (row.query || '').toLowerCase().replace(/\s+/g, '').slice(0, 80) || 'other'
}

function defaultAction(issueType) {
  switch (issueType) {
    case 'missing_content': return 'add_text'
    case 'wrong_entity': return 'edit_entity'
    case 'wrong_relation': return 'edit_relation'
    case 'outdated_content': return 'replace_document'
    case 'wrong_source': return 'review_document'
    case 'incomplete_citation': return 'add_text'
    default: return 'review_required'
  }
}

export function createDiagnosisLedger({ dir, feedback, logger = () => {} } = {}) {
  const log = createAppendLog(path.join(dir, 'diagnoses.jsonl'))
  const records = new Map()
  for (const row of log.readAll()) if (row && row.diagnosis_id) records.set(row.diagnosis_id, row)

  function persist(row) { log.append(row); records.set(row.diagnosis_id, row); return row }

  function group(rows) {
    const groups = new Map()
    for (const row of rows) {
      const key = keyFor(row)
      const group = groups.get(key) || { key, issue_type: row.issue_type || 'other', feedback: [], queries: new Set() }
      group.feedback.push(row)
      if (row.query) group.queries.add(row.query)
      groups.set(key, group)
    }
    return [...groups.values()].map((g) => ({
      key: g.key,
      issue_type: g.issue_type,
      count: g.feedback.length,
      queries: [...g.queries].slice(0, 5),
      feedback_ids: g.feedback.map((r) => r.feedback_id),
      evidence: g.feedback.slice(0, 5).map((r) => ({
        query: r.query,
        note: r.note,
        references: r.references,
        message_id: r.message_id,
      })),
      action: defaultAction(g.issue_type),
    })).sort((a, b) => b.count - a.count)
  }

  function create({ actor = 'agent', limit = MAX_FEEDBACK, analysis = null } = {}) {
    const rows = feedback.list({ rating: 'negative', status: 'open', limit: Math.min(MAX_FEEDBACK, Number(limit) || MAX_FEEDBACK) })
    const diagnosisId = 'diag-' + crypto.randomBytes(6).toString('hex')
    const groups = group(rows).slice(0, MAX_CANDIDATES)
    const analyzed = typeof analysis === 'function' ? analysis(groups) : Array.isArray(analysis) ? analysis : null
    const suggestions = (Array.isArray(analyzed) && analyzed.length ? analyzed : groups).slice(0, MAX_CANDIDATES)
      .map((item, index) => ({
        proposal_id: 'dp-' + crypto.randomBytes(6).toString('hex'),
        rank: index + 1,
        issue_type: item.issue_type || 'other',
        title: item.title || titleFor(item.issue_type),
        summary: item.summary || summaryFor(item),
        action: item.action || defaultAction(item.issue_type),
        payload: item.payload || {},
        evidence: item.evidence || groups[index]?.evidence || [],
        feedback_ids: item.feedback_ids || groups[index]?.feedback_ids || [],
        confidence: Number.isFinite(item.confidence) ? Math.max(0, Math.min(1, item.confidence)) : confidenceFor(item),
        risk: item.risk || riskFor(item.action || defaultAction(item.issue_type)),
        status: 'awaiting_approval',
      }))
    const row = { diagnosis_id: diagnosisId, created_at: new Date().toISOString(), mode: 'rules', actor, feedback_count: rows.length, candidate_count: suggestions.length, recommended_count: Math.min(MAX_RECOMMENDED, suggestions.length), proposals: suggestions }
    return persist(row)
  }

  /**
   * 模型诊断入口：接收经 diagnosis-submit.js 校验的案例数组，生成一次
   * mode='agent' 的诊断记录。校验失败或建议类动作的案例进入
   * needs_manual_review（保留诊断信息，不可执行）。
   * @param {object} opts
   * @param {Array} opts.cases - 校验后的案例（validation.ok 与 validation.errors 已就位）。
   * @param {string} opts.actor - 提交者（默认 agent）。
   */
  function submitCases({ cases = [], actor = 'agent' } = {}) {
    const diagnosisId = 'diag-' + crypto.randomBytes(6).toString('hex')
    const input = Array.isArray(cases) ? cases.slice(0, MAX_CANDIDATES) : []
    const proposals = input.map((item, index) => {
      const action = DIAGNOSIS_ACTIONS.includes(item.action) ? item.action : 'manual_review'
      const advisory = ADVISORY_ACTIONS.includes(action)
      const invalid = !(item.validation && item.validation.ok)
      return {
        proposal_id: 'dp-' + crypto.randomBytes(6).toString('hex'),
        rank: index + 1,
        issue_type: item.issue_type || 'other',
        cause_layer: CAUSE_LAYERS.includes(item.cause_layer) ? item.cause_layer : null,
        root_cause: String(item.root_cause || '').slice(0, 2000),
        title: item.title || titleFor(item.issue_type),
        summary: item.summary || summaryFor(item),
        action,
        payload: item.payload && typeof item.payload === 'object' ? item.payload : {},
        evidence: Array.isArray(item.evidence) ? item.evidence.slice(0, 10) : [],
        feedback_ids: Array.isArray(item.feedback_ids) ? item.feedback_ids.slice(0, MAX_FEEDBACK) : [],
        confidence: Number.isFinite(item.confidence) ? Math.max(0, Math.min(1, item.confidence)) : null,
        impact: ['high', 'medium', 'low'].includes(item.impact) ? item.impact : 'medium',
        risk: item.risk || riskFor(action),
        missing_information: Array.isArray(item.missing_information) ? item.missing_information.slice(0, 10).map(String) : [],
        recommend: item.recommend === true,
        validation: item.validation || { ok: false, errors: ['未经校验的案例'] },
        status: advisory || invalid ? 'needs_manual_review' : 'awaiting_approval',
      }
    })
    const recommendedCount = (() => {
      const marked = proposals.filter((p) => p.recommend).length
      if (marked > 0) return Math.min(MAX_RECOMMENDED, marked)
      const byConf = [...proposals].sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
      return Math.min(MAX_RECOMMENDED, byConf.filter((p) => p.confidence !== null).length)
    })()
    const row = {
      diagnosis_id: diagnosisId,
      created_at: new Date().toISOString(),
      mode: 'agent',
      actor,
      feedback_count: [...new Set(proposals.flatMap((p) => p.feedback_ids))].length,
      candidate_count: proposals.length,
      recommended_count: recommendedCount,
      proposals,
    }
    return persist(row)
  }

  function list({ limit = 20 } = {}) { return [...records.values()].sort((a, b) => a.created_at < b.created_at ? 1 : -1).slice(0, Math.max(1, Math.min(50, Number(limit) || 20))) }
  /** 全量记录（运营指标用，不受 list 的 50 条上限约束）。 */
  function all() { return [...records.values()].sort((a, b) => a.created_at < b.created_at ? 1 : -1) }
  function get(id) { return records.get(id) || null }
  function proposal(id) { for (const d of records.values()) { const p = d.proposals.find((item) => item.proposal_id === id); if (p) return { diagnosis: d, proposal: p } } return null }
  function setProposalStatus(id, status, extra = {}) {
    const found = proposal(id)
    if (!found) throw Object.assign(new Error('提案不存在: ' + id), { status: 404 })
    const next = { ...found.proposal, ...extra, status, updated_at: new Date().toISOString() }
    const diagnosis = { ...found.diagnosis, proposals: found.diagnosis.proposals.map((p) => p.proposal_id === id ? next : p) }
    persist(diagnosis)
    return next
  }

  function settleByIntent(intent) {
    if (!intent || !intent.id) return []
    const changed = []
    for (const d of records.values()) {
      for (const p of d.proposals) {
        if (p.intent_id !== intent.id) continue
        if (intent.status === 'verified') changed.push(setProposalStatus(p.proposal_id, 'succeeded', { execution_status: intent.status }))
        else if (['failed', 'stuck'].includes(intent.status)) changed.push(setProposalStatus(p.proposal_id, 'failed', { execution_status: intent.status, error: intent.error || '意图执行失败' }))
      }
    }
    return changed
  }

  return { create, submitCases, list, all, get, proposal, setProposalStatus, settleByIntent, constants: { MAX_FEEDBACK, MAX_CANDIDATES, MAX_RECOMMENDED, CAUSE_LAYERS, EXECUTABLE_ACTIONS, ADVISORY_ACTIONS, DIAGNOSIS_ACTIONS } }
}

function titleFor(type) {
  return ({ missing_content: '补充缺失知识', wrong_entity: '修正实体信息', wrong_relation: '修正知识关系', outdated_content: '处理过期文档', wrong_source: '核对引用文档', incomplete_citation: '补充引用内容', answer_style: '改进回答方式', other: '人工核查反馈' })[type] || '人工核查反馈'
}

function summaryFor(item) { return `${item.count || 1} 条反馈指向“${titleFor(item.issue_type)}”，请核对证据后决定是否修复。` }
function confidenceFor(item) { return Math.min(0.95, 0.45 + Math.min(0.4, (item.count || 1) * 0.1)) }
function riskFor(action) { return ['replace_document', 'review_document'].includes(action) ? 'high' : ['edit_relation', 'edit_entity'].includes(action) ? 'medium' : 'low' }
