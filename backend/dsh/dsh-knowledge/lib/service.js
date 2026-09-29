/**
 * dsh-knowledge v2 · KnowledgeService —— 单一写入口（chokepoint）。
 *
 * 所有知识库变更（Web 路由 / 模型工具 / 收敛器）都必须经过本层。
 * 相对 v1 的结构性修正（对应重构 P2-10/P2-11/P2-9/P0-3）：
 *
 *  - 强制点在执行处：origin 策略链。
 *      origin 'user'    （Web 工作台，人已确认）→ 直接执行
 *      origin 'agent'   （模型工具 kb_update）   → 破坏性与图谱写操作必须 approved（审批通过）
 *      origin 'system'  （收敛器/意图账本）      → 直接执行（账本即意图）
 *    绕过审批不再是"纪律问题"，而是结构上不可能（v1 的 kb_update 直通洞）。
 *  - actor 服务端派生：工具路径取 exec.agent（由 index.js 注入），客户端自报仅作展示。
 *  - 文档变更全部落意图账本（lib/intent.js）：先持久化意图再执行，重启不丢。
 *  - retryDoc 修复 v1 双 bug：显式 doc_ids，无"全局重试所有失败文档"路径。
 *
 * 查询路径刻意薄：不过门控、不做重计算，唯一副作用是 query_log 追加（curator 侧）。
 */

import path from 'node:path'
import crypto from 'node:crypto'
import { flattenGraphArrays, isPipelineBusy } from './engine-port.js'

const MAX_BYTES = 100 * 1024 * 1024

function badReq(msg) { const e = new Error(msg); e.status = 400; return e }
function notFound(msg) { const e = new Error(msg); e.status = 404; return e }
function conflict(msg) { const e = new Error(msg); e.status = 409; return e }
function forbidden(msg) { const e = new Error(msg); e.status = 403; return e }

const LIVE_STATUSES = ['active', 'pending', 'processing', 'updating']

export function createKnowledgeService({ engine, registry, intents, curator, logger = () => {} } = {}) {
  let supportedExt = null
  let supportedExtAt = 0

  async function supportedExtensions(signal) {
    if (supportedExt && Date.now() - supportedExtAt < 3600 * 1000) return supportedExt
    const r = await engine.supportedFileTypes(signal)
    supportedExt = (r && Array.isArray(r.supported_extensions)) ? r.supported_extensions : null
    supportedExtAt = Date.now()
    return supportedExt
  }

  function sanitizeName(name) {
    return String(name || 'doc').replace(/[^\w.\u4e00-\u9fa5-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 120) || 'doc'
  }

  /**
   * origin 策略：agent 发起的变更必须有审批令牌或门控背书。
   * 豁免：ingest（沉淀是 kb_ingest 的文档化用途，审计+账本可回退）、
   * retry（幂等修复，不改变知识集合）。破坏性与图谱写操作不豁免。
   */
  function enforceOrigin(op, { origin = 'user', approved = false }) {
    if (origin !== 'agent') return
    if (!approved) {
      throw forbidden('模型发起的 ' + op + ' 需要人工审批')
    }
  }

  async function checkExtension(name) {
    const ext = path.extname(name).toLowerCase()
    const supported = await supportedExtensions()
    if (supported && !supported.includes(ext)) {
      throw badReq('不支持的文件类型: ' + ext + '（支持：' + supported.join('、') + '）')
    }
  }

  // ---------------------------------------------------------------- 沉淀（意图账本）

  async function ingestText({ title, text, topic = '未分类', actor = 'web', origin = 'user', approved = false, source = null }) {
    title = String(title || '').trim()
    text = String(text || '').trim()
    if (!title) throw badReq('标题不能为空')
    if (!text) throw badReq('正文不能为空')
    const src = source || ('text:' + crypto.createHash('sha1').update(title + '\n' + text).digest('hex').slice(0, 16))
    const existing = registry.findBySource(src)
    if (existing && LIVE_STATUSES.includes(existing.status)) {
      throw conflict('已存在相同来源的文档《' + existing.title + '》，如需更新请走替换流程')
    }
    const inflight = intents.list().find((i) =>
      !['verified', 'failed', 'stuck'].includes(i.status)
      && ['ingest_text', 'ingest_file', 'replace'].includes(i.kind)
      && i.params.source === src)
    if (inflight) {
      throw conflict('相同来源的内容正在处理中（' + inflight.id + '），请等待完成后再提交')
    }
    const intent = intents.submitText({ text, source: src, title, topic, actor, origin })
    registry.audit({ actor, action: 'ingest', target: intent.id, detail: { title, topic, origin, intent: intent.id } })
    return { ok: true, intent_id: intent.id, document: { id: intent.id, title, status: 'pending', intent: true } }
  }

  async function ingestFile({ filename, bytes, title = null, topic = '未分类', actor = 'web', origin = 'user', approved = false }) {
    const name = sanitizeName(filename)
    if (!name || name === 'doc') throw badReq('文件名无效')
    if (!bytes || !bytes.length) throw badReq('文件内容为空')
    if (bytes.length > MAX_BYTES) throw badReq('文件超过 100MB 上限')
    await checkExtension(name)
    const docTitle = title ? String(title).trim() : name
    const intent = intents.submitFile({ filename: name, bytes, title: docTitle, topic, actor, origin, source: name })
    registry.audit({ actor, action: 'ingest', target: intent.id, detail: { title: docTitle, topic, origin, intent: intent.id } })
    return { ok: true, intent_id: intent.id, document: { id: intent.id, title: docTitle, status: 'pending', intent: true } }
  }

  // ---------------------------------------------------------------- 替换 / 删除 / 重试（意图账本）

  async function replaceFile({ docId, filename, bytes, actor = 'web', origin = 'user', approved = false, reason = '' }) {
    const old = registry.getDoc(docId)
    if (!old) throw notFound('文档不存在: ' + docId)
    const name = sanitizeName(filename)
    if (!name || name === 'doc') throw badReq('文件名无效')
    if (!bytes || !bytes.length) throw badReq('文件内容为空')
    if (bytes.length > MAX_BYTES) throw badReq('文件超过 100MB 上限')
    enforceOrigin('replace', { origin, approved })
    await checkExtension(name)
    const intent = intents.submitFile({
      filename: name, bytes, title: old.title, topic: old.topic, actor, origin,
      replacesDocId: docId, source: old.source,
    })
    registry.touchStatus(docId, 'updating')
    registry.audit({ actor, action: 'replace_started', target: docId, detail: { reason, intent: intent.id } })
    return { ok: true, intent_id: intent.id, document: { id: docId, title: old.title, status: 'updating' } }
  }

  async function replaceText({ docId, title, text, actor = 'web', origin = 'user', approved = false, reason = '' }) {
    const old = registry.getDoc(docId)
    if (!old) throw notFound('文档不存在: ' + docId)
    const body = String(text || '').trim()
    if (!body) throw badReq('正文不能为空')
    enforceOrigin('replace', { origin, approved })
    // 文本替换保留原 source：内容寻址产生新 doc_id，账本负责先删旧再插新
    const intent = intents.submitText({
      text: body, source: old.source, title: title ? String(title).trim() : old.title,
      topic: old.topic, actor, origin, replacesDocId: docId,
    })
    registry.touchStatus(docId, 'updating')
    registry.audit({ actor, action: 'replace_started', target: docId, detail: { reason, intent: intent.id } })
    return { ok: true, intent_id: intent.id, document: { id: docId, title: old.title, status: 'updating' } }
  }

  async function deleteDoc({ docId, actor = 'web', origin = 'user', approved = false, reason = '' }) {
    const entry = registry.getDoc(docId)
    if (!entry) throw notFound('文档不存在: ' + docId)
    enforceOrigin('delete', { origin, approved })
    const intent = intents.submit('delete_doc', { docId, source: entry.source, reason: reason || '删除', actor },
      { priority: 'user', actor, origin })
    registry.retireDoc(docId, actor, 'retired')
    return { ok: true, deleted: docId, intent_id: intent.id, engine_status: 'queued' }
  }

  /** 幂等修复：只重试目标文档（显式 doc_ids），不做全局兜底重试（v1 双 bug 修正）。 */
  async function retryDoc({ docId, actor = 'web', origin = 'user' }) {
    const entry = registry.getDoc(docId)
    if (!entry) throw notFound('文档不存在: ' + docId)
    let res = null
    try {
      res = await engine.reprocessFailed([docId])
    } catch (e) {
      if (isPipelineBusy(e)) {
        const be = new Error('知识库引擎正在处理其他任务（管道忙碌），请稍后重试')
        be.status = 409
        be.code = 'pipeline_busy'
        throw be
      }
      throw e
    }
    registry.touchStatus(docId, 'processing')
    registry.audit({ actor, action: 'retry', target: docId, detail: { engine_status: (res && res.status) || '' } })
    return { ok: true, engine_status: (res && res.status) || 'requested' }
  }

  /** 会话反哺沉淀：同一 message 重复沉淀 → 幂等更新（走替换）。 */
  async function saveConversation({ sessionId, messageId, title, body, topic = '未分类', actor = 'web' }) {
    title = String(title || '').trim()
    body = String(body || '').trim()
    if (!title) throw badReq('标题不能为空')
    if (!body) throw badReq('正文不能为空')
    const source = 'conv:' + String(sessionId || 's') + '/' + String(messageId || 'm')
    const existing = registry.findBySource(source)
    if (existing && LIVE_STATUSES.includes(existing.status)) {
      return replaceText({ docId: existing.doc_id, title, text: body, actor, reason: '会话反哺更新' })
    }
    return ingestText({ title, text: body, topic, actor, origin: 'user', source })
  }

  // ---------------------------------------------------------------- 图谱（同步写，引擎报错即知）

  /** 管道忙 409 → 友好提示（UI 侧同时以健康状态禁用编辑入口）。 */
  async function callGraph(fn) {
    try {
      return await fn()
    } catch (e) {
      if (isPipelineBusy(e)) {
        const be = new Error('知识库引擎正在处理其他任务（管道忙碌），请稍后再试图谱编辑')
        be.status = 409
        be.code = 'pipeline_busy'
        throw be
      }
      throw e
    }
  }

  function graphAudit(op, target, detail, actor) {
    registry.audit({ actor, action: op, target: String(target), detail })
    registry.emitGraph(op, { entity: String(target), detail })
  }

  function graphOrigin(op, { origin = 'user', approved = false }) {
    enforceOrigin(op, { origin, approved })
  }

  async function entityCreate({ name, type = '', description = '', actor = 'web', origin = 'user', approved = false }) {
    name = String(name || '').trim()
    if (!name) throw badReq('实体名不能为空')
    graphOrigin('entity_create', { origin, approved })
    const entityData = flattenGraphArrays({ description: description || '' })
    if (type) entityData.entity_type = type
    const res = await callGraph(() => engine.entityCreate(name, entityData))
    graphAudit('entity_create', name, { type, description }, actor)
    return { ok: true, entity: name, engine: res }
  }

  async function entityEdit({ name, updates, actor = 'web', origin = 'user', approved = false }) {
    name = String(name || '').trim()
    if (!name) throw badReq('实体名不能为空')
    if (!updates || typeof updates !== 'object') throw badReq('updates 不能为空')
    graphOrigin('entity_edit', { origin, approved })
    const res = await callGraph(() => engine.entityEdit(name, flattenGraphArrays(updates)))
    graphAudit('entity_edit', name, updates, actor)
    return { ok: true, entity: name, engine: res }
  }

  async function entityMerge({ sources, target, actor = 'web', origin = 'user', approved = false }) {
    if (!Array.isArray(sources) || !sources.length) throw badReq('至少需要一个被合并实体')
    target = String(target || '').trim()
    if (!target) throw badReq('合并目标实体不能为空')
    graphOrigin('entity_merge', { origin, approved })
    const srcs = sources.map((s) => String(s).trim()).filter(Boolean)
    if (!srcs.length) throw badReq('被合并实体不能为空')
    const res = await callGraph(() => engine.entityMerge(srcs, target))
    graphAudit('entity_merge', target, { sources: srcs }, actor)
    return { ok: true, merged: { sources: srcs, target }, engine: res }
  }

  async function entityDelete({ name, actor = 'web', origin = 'user', approved = false }) {
    name = String(name || '').trim()
    if (!name) throw badReq('实体名不能为空')
    graphOrigin('entity_delete', { origin, approved })
    const res = await callGraph(() => engine.entityDelete(name))
    graphAudit('entity_delete', name, {}, actor)
    return { ok: true, entity: name, engine: res }
  }

  async function relationCreate({ src, tgt, description = '', keywords = null, actor = 'web', origin = 'user', approved = false }) {
    src = String(src || '').trim()
    tgt = String(tgt || '').trim()
    if (!src || !tgt) throw badReq('关系两端实体不能为空')
    graphOrigin('relation_create', { origin, approved })
    const relationData = flattenGraphArrays({ description: description || '' })
    if (keywords) relationData.keywords = Array.isArray(keywords) ? keywords.map(String).join('，') : String(keywords)
    const res = await callGraph(() => engine.relationCreate(src, tgt, relationData))
    graphAudit('relation_create', src + ' → ' + tgt, { description }, actor)
    return { ok: true, relation: { src, tgt }, engine: res }
  }

  async function relationEdit({ src, tgt, updates, actor = 'web', origin = 'user', approved = false }) {
    src = String(src || '').trim()
    tgt = String(tgt || '').trim()
    if (!src || !tgt) throw badReq('关系两端实体不能为空')
    if (!updates || typeof updates !== 'object') throw badReq('updates 不能为空')
    graphOrigin('relation_edit', { origin, approved })
    const res = await callGraph(() => engine.relationEdit(src, tgt, flattenGraphArrays(updates)))
    graphAudit('relation_edit', src + ' → ' + tgt, updates, actor)
    return { ok: true, relation: { src, tgt }, engine: res }
  }

  async function relationDelete({ src, tgt, actor = 'web', origin = 'user', approved = false }) {
    src = String(src || '').trim()
    tgt = String(tgt || '').trim()
    if (!src || !tgt) throw badReq('关系两端实体不能为空')
    graphOrigin('relation_delete', { origin, approved })
    const res = await callGraph(() => engine.relationDelete(src, tgt))
    graphAudit('relation_delete', src + ' → ' + tgt, {}, actor)
    return { ok: true, relation: { src, tgt }, engine: res }
  }

  /** 意图视角的文档列表（注册表为准，无扫描上限）：修复 v1 20 页截断。 */
  function listDocuments({ status, topic, q, page = 1, pageSize = 20, includeRetired = false }) {
    const all = registry.listDocs({ status, topic, q, excludeRetired: !includeRetired })
    const pending = intents.list()
      .filter((i) => !['verified', 'failed', 'stuck'].includes(i.status) && (i.kind === 'ingest_file' || i.kind === 'ingest_text'))
      .map((i) => ({
        id: i.id, title: i.params.title, source: i.params.source, topic: i.params.topic,
        status: 'pending', engine_status: '', intent: true,
        created_at: i.createdAt, updated_at: i.updated_at,
      }))
    const items = (page === 1 ? [...pending.filter((p) => !status || status === 'pending'), ...all] : all)
      .slice((page - 1) * pageSize, (page - 1) * pageSize + pageSize)
    return {
      total: all.length + pending.length,
      page, page_size: pageSize,
      items: items.map((d) => ({
        id: d.doc_id || d.id,
        title: d.title,
        source: d.source || '',
        topic: d.topic || '未分类',
        version: d.version || 1,
        status: d.status,
        engine_status: d.engine_status || d.status,
        error_msg: d.status_detail || '',
        created_at: d.created_at || '',
        updated_at: d.updated_at || '',
        intent: !!d.intent,
      })),
    }
  }

  // ---------------------------------------------------------------- 图谱读（按文档）

  /**
   * source_id 取文件名集合：引擎侧该字段可能是数组（Neo4j）或
   * ";;"/"，" 拼接串（GraphML / 写入时拍平），两种形态都归一为 basename 集合。
   */
  function sourceIdBaseNames(v) {
    const out = new Set()
    const add = (s) => {
      const b = path.basename(String(s || '').trim())
      if (b) out.add(b)
    }
    if (Array.isArray(v)) v.forEach(add)
    else if (typeof v === 'string') v.split(/;;|；|，|,|;|\n/).forEach((s) => { if (s.trim()) add(s) })
    return out
  }

  /**
   * 取引擎全图：graphs 的 label 必填（引擎契约怪癖），缺省回退第一个已知
   * label；无 label 或空图时返回空集（与 engine-port 的兜底语义一致）。
   */
  async function wholeGraph() {
    let g
    try {
      g = await engine.graphs({ max_depth: 2, max_nodes: 500 })
    } catch (e) {
      if (!(e && e.status === 400)) throw e
      const labels = await engine.labelList().catch(() => [])
      const list = Array.isArray(labels) ? labels : []
      if (!list.length) return { nodes: [], edges: [] }
      g = await engine.graphs({ label: list[0], max_depth: 2, max_nodes: 500 })
    }
    return {
      nodes: Array.isArray(g && g.nodes) ? g.nodes : [],
      edges: Array.isArray(g && g.edges) ? g.edges : [],
    }
  }

  /**
   * 文档知识图谱：文档入库时引擎从正文抽取的实体/关系，经 source_id 关联回文档。
   * 取引擎全图后按本文档过滤；关系保留两端实体都来自本文档的部分。
   */
  async function docGraph({ docId }) {
    const doc = registry.getDoc(docId)
    if (!doc) throw notFound('文档不存在: ' + docId)
    const { nodes, edges } = await wholeGraph()
    const want = path.basename(String(doc.source || ''))
    const entities = []
    const nameSet = new Set()
    for (const n of nodes) {
      const p = (n && n.properties) || {}
      const sources = sourceIdBaseNames(p.source_id)
      if (!want || !sources.has(want)) continue
      const id = String(n.id || '')
      entities.push({ id, type: p.entity_type || '', description: p.description || '' })
      nameSet.add(id)
    }
    const relations = []
    for (const e of edges) {
      if (!nameSet.has(String(e.source || '')) || !nameSet.has(String(e.target || ''))) continue
      relations.push({
        source: String(e.source || ''),
        target: String(e.target || ''),
        description: (e.properties && e.properties.description) || '',
        weight: (e.properties && e.properties.weight) || 0,
      })
    }
    return {
      ok: true,
      doc: { id: doc.doc_id, title: doc.title, topic: doc.topic, status: doc.status, version: doc.version },
      entities, relations,
    }
  }

  return {
    supportedExtensions,
    ingestText,
    ingestFile,
    replaceFile,
    replaceText,
    saveConversation,
    deleteDoc,
    retryDoc,
    entityCreate,
    entityEdit,
    entityMerge,
    entityDelete,
    relationCreate,
    relationEdit,
    relationDelete,
    listDocuments,
    docGraph,
  }
}
