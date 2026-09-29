/**
 * 模型诊断案例的确定性校验器（大模型只判断，代码负责校验）。
 *
 * kb_diagnosis_submit 收到的每条案例在进入提案账本前必须过本模块：
 *  - feedback_id / query_id 真实存在（反馈须为 open 负反馈）；
 *  - 证据引用（chunk/文件）属于该 query 的检索快照或引用列表；
 *  - action 与 payload 匹配（add_text 要 title+text；edit_entity 要
 *    entity_name+updates；edit_relation 要 src+tgt+updates；建议类动作要
 *    advice 操作指令——每条以【改文档】【改图谱】【核对】【配置】【不改】【改提问】开头）；
 *  - edit_entity / edit_relation 的目标实体在图谱中真实存在；
 *  - cause_layer 落在枚举内、confidence 在 [0,1]。
 *
 * 校验失败的案例不是丢弃，而是带 errors 落为 needs_manual_review：
 * 诊断结论仍有参考价值，但绝不允许直接执行。所有对引擎的查询只读。
 */
import { CAUSE_LAYERS, EXECUTABLE_ACTIONS, ADVISORY_ACTIONS } from './diagnosis.js'

const MAX_CASES = 10
const MAX_ROOT_CAUSE = 2000

function isPlainObject(v) { return !!v && typeof v === 'object' && !Array.isArray(v) }

/** 单条案例的静态结构校验（不触引擎、不查账本）。 */
function checkShape(item) {
  const errors = []
  if (!isPlainObject(item)) return { errors: ['案例必须是对象'] }
  if (!Array.isArray(item.feedback_ids) || item.feedback_ids.length === 0) errors.push('feedback_ids 不能为空')
  if (item.cause_layer !== undefined && item.cause_layer !== null && !CAUSE_LAYERS.includes(item.cause_layer)) {
    errors.push('未知 cause_layer: ' + item.cause_layer + '（允许: ' + CAUSE_LAYERS.join('/') + '）')
  }
  if (item.confidence !== undefined && item.confidence !== null
    && !(Number.isFinite(item.confidence) && item.confidence >= 0 && item.confidence <= 1)) {
    errors.push('confidence 必须在 0 到 1 之间')
  }
  const action = item.action
  if (!EXECUTABLE_ACTIONS.includes(action) && !ADVISORY_ACTIONS.includes(action)) {
    errors.push('未知 action: ' + action + '（允许: ' + [...EXECUTABLE_ACTIONS, ...ADVISORY_ACTIONS].join('/') + '）')
  }
  if (item.root_cause !== undefined && item.root_cause !== null && String(item.root_cause).length > MAX_ROOT_CAUSE) {
    errors.push('root_cause 超长（上限 ' + MAX_ROOT_CAUSE + ' 字符）')
  }
  return { errors, action }
}

/** action 与 payload 匹配校验（可执行动作要参数，建议动作要具体建议）。 */
function checkPayload(action, payload) {
  const errors = []
  const p = isPlainObject(payload) ? payload : {}
  if (action === 'add_text') {
    if (!p.title || typeof p.title !== 'string') errors.push('add_text 的 payload 需要 title')
    if (!p.text || typeof p.text !== 'string') errors.push('add_text 的 payload 需要 text')
  } else if (action === 'edit_entity') {
    if (!p.entity_name || typeof p.entity_name !== 'string') errors.push('edit_entity 的 payload 需要 entity_name')
    if (!isPlainObject(p.updates) || Object.keys(p.updates).length === 0) errors.push('edit_entity 的 payload 需要 updates')
  } else if (action === 'edit_relation') {
    if (!p.src || typeof p.src !== 'string') errors.push('edit_relation 的 payload 需要 src')
    if (!p.tgt || typeof p.tgt !== 'string') errors.push('edit_relation 的 payload 需要 tgt')
    if (!isPlainObject(p.updates) || Object.keys(p.updates).length === 0) errors.push('edit_relation 的 payload 需要 updates')
  } else if (ADVISORY_ACTIONS.includes(action)) {
    // 建议类动作不可在线执行，advice 是它唯一的人工处置价值：
    // 每条必须是运维者/提问用户可执行的操作指令，以【改文档】【改图谱】【核对】【配置】【不改】【改提问】
    // 开头，说清要不要动知识库、动哪个文档/实体/关系、做什么、提问怎么改；策略性描述不可执行
    const advice = p.advice
    const adviceList = (Array.isArray(advice) ? advice : [advice])
      .filter((a) => typeof a === 'string' && a.trim())
      .map((a) => a.trim())
    if (adviceList.length === 0) {
      errors.push(action + ' 的 payload 需要 advice（分条操作指令）')
    } else if (adviceList.some((a) => !/^【(改文档|改图谱|核对|配置|不改|改提问)】/.test(a))) {
      errors.push(action + ' 的 advice 每条须以【改文档】【改图谱】【核对】【配置】【不改】【改提问】之一开头（写明文件名/实体关系与操作/具体内容/提问改进示例，或明确无需修改及原因），不要写策略性描述')
    }
  }
  return errors
}

/** basename 比较（引擎 file_path 可能带目录，注册表 source 是纯文件名）。 */
function sameFile(a, b) {
  if (!a || !b) return false
  const base = (s) => String(s).split(/[\\/]/).pop().trim()
  return base(a) === base(b)
}

/**
 * 校验并规整一批诊断案例。
 * @param {object} opts
 * @param {Array} opts.cases - 模型提交的案例数组（至多 10 条，超出报错）。
 * @param {object} opts.feedback - 反馈账本（createFeedbackLedger 实例）。
 * @param {object} opts.curator - 检索日志数据层（getQuery 用）。
 * @param {object} opts.engine - LightRAG 适配器（entityExists 只读查询）。
 * @returns {{ ok: boolean, error?: string, cases: Array }} 每条案例附带
 *   validation: { ok, errors } 与 evidence（query 证据自动带上 query_id/原文）。
 */
export async function validateDiagnosisCases({ cases, feedback, curator, engine }) {
  if (!Array.isArray(cases) || cases.length === 0) return { ok: false, error: 'cases 不能为空', cases: [] }
  if (cases.length > MAX_CASES) return { ok: false, error: '一次最多提交 ' + MAX_CASES + ' 个案例', cases: [] }

  // 证据预取：本批涉及的 query 各取一次查询记录（含检索快照）
  const queryCache = new Map()
  async function loadQuery(queryId) {
    if (queryId === undefined || queryId === null || queryId === '') return null
    if (!queryCache.has(queryId)) queryCache.set(queryId, curator.getQuery(String(queryId)))
    return queryCache.get(queryId)
  }

  const validated = []
  for (const raw of cases) {
    const { errors, action } = checkShape(raw)
    const item = isPlainObject(raw) ? raw : {}
    const knownAction = (EXECUTABLE_ACTIONS.includes(action) || ADVISORY_ACTIONS.includes(action)) ? action : 'manual_review'

    // feedback_ids 存在性与状态
    const feedbackRows = []
    const seen = new Set()
    for (const fid of (Array.isArray(item.feedback_ids) ? item.feedback_ids : [])) {
      if (seen.has(fid)) continue
      seen.add(fid)
      const row = feedback.get(String(fid))
      if (!row) { errors.push('反馈不存在: ' + fid); continue }
      if (row.rating !== 'negative') { errors.push('反馈不是负反馈: ' + fid); continue }
      if (row.status !== 'open') { errors.push('反馈已处理（' + row.status + '）: ' + fid); continue }
      feedbackRows.push(row)
    }

    // query 证据：从反馈行取 query_id，全部必须可解析到查询记录
    const queryIds = [...new Set(feedbackRows.map((r) => r.query_id).filter(Boolean))]
    const queryRows = []
    for (const qid of queryIds) {
      const q = await loadQuery(qid)
      if (!q) errors.push('查询记录不存在: ' + qid)
      else queryRows.push(q)
    }
    // 案例自身声明的 query_id 也要校验（证据区块里 type=query 的引用）
    const declaredQueryIds = (Array.isArray(item.evidence) ? item.evidence : [])
      .filter((e) => e && e.type === 'query' && e.query_id).map((e) => String(e.query_id))
    for (const qid of [...new Set(declaredQueryIds)]) {
      const q = await loadQuery(qid)
      if (!q) errors.push('证据引用的查询不存在: ' + qid)
      else if (!queryRows.some((r) => r.query_id === qid)) queryRows.push(q)
    }

    // 证据引用校验：chunk/文件必须出现在该案例任一 query 的快照或引用里
    const snapshotChunks = new Set()
    const snapshotFiles = new Set()
    for (const q of queryRows) {
      const snap = q.retrieval_snapshot
      for (const c of (snap && Array.isArray(snap.chunks) ? snap.chunks : [])) {
        if (c && c.reference_id) snapshotChunks.add(String(c.reference_id))
        if (c && c.file_path) snapshotFiles.add(String(c.file_path))
      }
      for (const r of (Array.isArray(q.references) ? q.references : [])) {
        if (r && r.file) snapshotFiles.add(String(r.file))
      }
    }
    const evidence = Array.isArray(item.evidence) ? item.evidence.slice(0, 10) : []
    for (const ev of evidence) {
      if (!isPlainObject(ev)) continue
      if (ev.type === 'chunk' && ev.reference_id && !snapshotChunks.has(String(ev.reference_id))) {
        errors.push('证据 chunk 不属于关联查询的检索结果: ' + ev.reference_id)
      }
      if (ev.type === 'file' && ev.file_path && ![...snapshotFiles].some((f) => sameFile(f, ev.file_path))) {
        errors.push('证据文件不在关联查询的引用中: ' + ev.file_path)
      }
    }
    // feedback 证据自动带上原文（前端与复核要用，模型不必重复抄写）
    const enrichedEvidence = [
      ...feedbackRows.slice(0, 5).map((r) => ({ type: 'feedback', feedback_id: r.feedback_id, query_id: r.query_id, query: r.query, note: r.note, issue_type: r.issue_type })),
      ...queryRows.slice(0, 5).map((q) => ({ type: 'query', query_id: q.query_id, query: q.query, mode: q.mode })),
      ...evidence.filter((e) => isPlainObject(e) && e.type !== 'feedback' && e.type !== 'query'),
    ]

    // payload 匹配（仅可执行动作）
    errors.push(...checkPayload(knownAction, item.payload))

    // 实体存在性（edit_* 目标必须已在图谱中；引擎不可达时跳过该检查并记警告）
    const p = isPlainObject(item.payload) ? item.payload : {}
    if (knownAction === 'edit_entity' && p.entity_name && engine) {
      try {
        const r = await engine.entityExists(String(p.entity_name))
        if (r && r.exists === false) errors.push('实体不存在于图谱: ' + p.entity_name)
      } catch (e) { /* 引擎不可达不阻塞提交，approve 阶段仍会失败兜底 */ }
    }
    if (knownAction === 'edit_relation' && p.src && p.tgt && engine) {
      for (const name of [p.src, p.tgt]) {
        try {
          const r = await engine.entityExists(String(name))
          if (r && r.exists === false) errors.push('关系端点实体不存在于图谱: ' + name)
        } catch (e) { /* 同上 */ }
      }
    }

    validated.push({
      case_id: item.case_id ? String(item.case_id) : null,
      feedback_ids: [...seen],
      issue_type: item.issue_type || 'other',
      cause_layer: CAUSE_LAYERS.includes(item.cause_layer) ? item.cause_layer : null,
      root_cause: String(item.root_cause || '').slice(0, MAX_ROOT_CAUSE),
      title: item.title ? String(item.title) : null,
      summary: item.summary ? String(item.summary) : null,
      action: knownAction,
      payload: isPlainObject(item.payload) ? item.payload : {},
      evidence: enrichedEvidence,
      confidence: Number.isFinite(item.confidence) ? Math.max(0, Math.min(1, item.confidence)) : null,
      impact: ['high', 'medium', 'low'].includes(item.impact) ? item.impact : 'medium',
      missing_information: Array.isArray(item.missing_information) ? item.missing_information.slice(0, 10).map(String) : [],
      recommend: item.recommend === true,
      validation: { ok: errors.length === 0, errors },
    })
  }
  return { ok: true, cases: validated }
}
