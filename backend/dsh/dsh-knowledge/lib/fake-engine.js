/**
 * dsh-knowledge v2 · 假引擎 —— 与 lib/engine-port.js 同接口的内存实现，
 * 模拟 LightRAG v1.5.6 的全部实测怪癖（引擎契约，见 engine-port.js 头注）：
 *
 *  1. 同 source 重插 → 409（Document storage already contains）
 *  2. 删除异步；管道忙时删除请求被静默丢弃（200 但不执行）
 *  3. 管道忙时插入/图谱写 → 409 Pipeline is busy
 *  4. 文档 id 内容寻址：相同内容 → 相同 doc_id
 *  5. 图数据含数组值 → 500（模拟 GraphML 不支持 list）
 *  6. track_status 返回 {track_id, documents:[{id,status,error_msg}]}
 *  7. page_size ≥ 10；/graphs 必填 label
 *
 * 测试钩子：setBusy / advanceTracks / failNextUpload / setQueryHandler 等。
 * 契约测试（dev/contract-engine.mjs）据此锁定怪癖；意图/收敛/服务层
 * 单元测试用同一假引擎跑全链路，不依赖真实容器。
 */

import crypto from 'node:crypto'

export function createFakeEngine({ processAfterPolls = 1, deleteApplyTicks = 1 } = {}) {
  const state = {
    busy: false,
    dropDeletesWhenBusy: true,
    // 文档表：docId -> { id, file_path, status, error_msg, created_at, updated_at, content_key }
    docs: new Map(),
    // source -> docId（同 source 唯一）
    sources: new Map(),
    // trackId -> { docId, status, error_msg, polls }
    tracks: new Map(),
    // 待执行删除：[{ docId, ticksLeft }]
    pendingDeletes: [],
    // 图谱：实体名 -> { entity_name, entity_id, entity_type, description }
    entities: new Map(),
    // 关系：src\u0000tgt -> { source, target, description, keywords }
    relations: new Map(),
    // 查询处理器：(payload) => data
    queryHandler: () => ({ chunks: [], entities: [], relationships: [], references: [] }),
    failNextUpload: null, // 'reject409' | 'trackFailed' | 'noTrackId'
    now: () => new Date().toISOString(),
  }

  function sha(s) { return crypto.createHash('sha1').update(String(s)).digest('hex').slice(0, 12) }

  function docIdOf(content, source) {
    // 内容寻址：相同内容得到相同 doc_id（与 source 无关，模拟引擎行为）
    return 'doc-' + sha(content)
  }

  function httpError(status, message) {
    const e = new Error(message)
    e.status = status
    return e
  }

  function assertNotBusy(what) {
    if (state.busy) throw httpError(409, 'Pipeline is busy with another operation (' + what + ')')
  }

  /** 检查图数据不含数组值（模拟 GraphML 不支持 list → 500）。 */
  function assertNoArrays(value, where) {
    if (Array.isArray(value)) throw httpError(500, 'GraphML storage does not support list values at ' + where)
    if (value && typeof value === 'object') {
      for (const [k, v] of Object.entries(value)) assertNoArrays(v, where + '.' + k)
    }
  }

  function createDoc(source, content) {
    const existing = state.sources.get(source)
    if (existing) {
      throw httpError(409, 'Document storage already contains a document with source "' + source + '". Delete the existing record before re-inserting.')
    }
    const id = docIdOf(content, source)
    // 内容寻址：若同内容文档已存在（不同 source），引擎侧仍返回同 id（共享索引）
    const doc = {
      id,
      file_path: source,
      status: 'processing',
      error_msg: '',
      content_key: sha(content),
      created_at: state.now(),
      updated_at: state.now(),
    }
    state.docs.set(id, doc)
    state.sources.set(source, id)
    const trackId = 'track-' + sha(source + ':' + content)
    state.tracks.set(trackId, { docId: id, status: 'processing', error_msg: '', polls: 0 })
    return { track_id: trackId, documents: [{ id, status: 'processing' }] }
  }

  /** 推进异步世界：track 处理与删除落地。每 tick 一步。 */
  function advanceTicks() {
    for (const [trackId, t] of state.tracks.entries()) {
      if (t.status !== 'processing') continue
      t.polls++
      if (t.polls >= processAfterPolls) {
        if (state.failNextUpload === 'trackFailed' && t.docId === lastTrackDocId) {
          t.status = 'failed'
          t.error_msg = 'injected parse failure'
          const d = state.docs.get(t.docId)
          if (d) { d.status = 'failed'; d.error_msg = 'injected parse failure'; d.updated_at = state.now() }
        } else {
          t.status = 'processed'
          const d = state.docs.get(t.docId)
          if (d) { d.status = 'processed'; d.updated_at = state.now() }
        }
      }
    }
    const still = []
    for (const del of state.pendingDeletes) {
      del.ticksLeft--
      if (del.ticksLeft > 0) { still.push(del); continue }
      // 落地时刻：忙则静默丢弃（200 已返回过、删除不执行）——怪癖 2
      if (state.dropDeletesWhenBusy && state.busy) {
        state.droppedDeletes = (state.droppedDeletes || 0) + 1
        continue
      }
      const doc = state.docs.get(del.docId)
      if (doc) {
        state.docs.delete(del.docId)
        if (state.sources.get(doc.file_path) === del.docId) state.sources.delete(doc.file_path)
      }
    }
    state.pendingDeletes = still
  }

  let lastTrackDocId = null

  const engine = {
    kind: 'fake',
    // ---- 测试钩子 ----
    setBusy(busy) { state.busy = !!busy },
    setQueryHandler(fn) { state.queryHandler = fn },
    failNextUpload(mode) { state.failNextUpload = mode },
    advanceTicks,
    /** 直接查内部状态（断言用）。 */
    _state: state,

    health: async () => ({ status: state.busy ? 'healthy' : 'healthy', core_version: 'fake-1.5.6', pipeline_busy: state.busy, llm_queue_status: {}, embedding_queue_status: null }),
    pipelineStatus: async () => ({ busy: state.busy }),

    // ---- 检索 ----
    async query(payload) {
      const data = state.queryHandler(payload)
      return { status: 'success', response: 'fake-answer:' + String(payload.query || ''), references: data.references || [], data }
    },
    async queryStream(payload, onLine) {
      const data = state.queryHandler(payload)
      onLine({ response: 'fake-answer:' + String(payload.query || '') })
      if (data.references) onLine({ references: data.references })
    },
    async queryData(payload) {
      const data = state.queryHandler(payload)
      return { status: 'success', data }
    },

    // ---- 文档 ----
    async listDocuments(opts = {}) {
      const page = opts.page || 1
      const pageSize = Math.max(10, opts.page_size || 20) // 怪癖 7：下限 10
      const all = [...state.docs.values()].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))
      const start = (page - 1) * pageSize
      return {
        documents: all.slice(start, start + pageSize),
        pagination: { page, page_size: pageSize, total_count: all.length },
      }
    },
    async statusCounts() {
      const counts = {}
      for (const d of state.docs.values()) counts[d.status] = (counts[d.status] || 0) + 1
      return { status_counts: counts }
    },
    async supportedFileTypes() {
      return { supported_extensions: ['.docx', '.pdf', '.md', '.txt', '.xlsx', '.pptx'] }
    },
    async uploadFile(filename, bytes) {
      if (state.failNextUpload === 'reject409') {
        state.failNextUpload = null
        throw httpError(409, 'Pipeline is busy with another operation (upload)')
      }
      assertNotBusy('upload') // 怪癖 3：忙时插入 409
      const content = 'file:' + filename + ':' + bytes.length + ':' + sha(bytes)
      lastTrackDocId = null
      if (state.failNextUpload === 'trackFailed') {
        // 保持钩子给 createDoc 内部使用
      }
      const res = createDoc(filename, content)
      lastTrackDocId = res.documents[0].id
      if (state.failNextUpload === 'noTrackId') {
        state.failNextUpload = null
        return { status: 'success' } // 怪癖防御：无 track_id
      }
      return res
    },
    async insertText(text, fileSource) {
      assertNotBusy('insert')
      const source = fileSource !== undefined ? fileSource : 'text:' + sha(text)
      const res = createDoc(source, 'text:' + text)
      lastTrackDocId = res.documents[0].id
      return res
    },
    async deleteDocuments(docIds) {
      // 怪癖 2：异步删除，先 200；落地在 advanceTicks；忙时静默丢弃
      for (const id of docIds) state.pendingDeletes.push({ docId: id, ticksLeft: deleteApplyTicks })
      return { status: 'deletion_started', message: 'Deletion is processing in the background' }
    },
    async reprocessFailed(docIds) {
      let n = 0
      for (const d of state.docs.values()) {
        if (d.status !== 'failed') continue
        if (docIds && docIds.length && !docIds.includes(d.id)) continue
        d.status = 'processing'
        d.updated_at = state.now()
        for (const [tid, t] of state.tracks.entries()) {
          if (t.docId === d.id) { t.status = 'processing'; t.polls = 0 }
        }
        n++
      }
      return { status: 'reprocessing', count: n }
    },
    async trackStatus(trackId) {
      const t = state.tracks.get(trackId)
      if (!t) throw httpError(404, 'track not found: ' + trackId)
      const d = state.docs.get(t.docId)
      return {
        track_id: trackId,
        status: t.status,
        documents: [{ id: t.docId, status: d ? d.status : t.status, error_msg: d ? d.error_msg : t.error_msg }],
      }
    },

    // ---- 治理 ----
    async sourceConflicts() { return { conflicts: [] } },

    // ---- 图谱 ----
    async entityExists(name) { return { exists: state.entities.has(name) } },
    async entityCreate(entityName, entityData) {
      assertNotBusy('graph')
      assertNoArrays(entityData, 'entity_data') // 怪癖 5
      if (state.entities.has(entityName)) throw httpError(409, 'Entity already exists: ' + entityName)
      state.entities.set(entityName, { entity_name: entityName, entity_id: 'e-' + sha(entityName), ...entityData })
      return { status: 'success' }
    },
    async entityEdit(entityName, updatedData) {
      assertNotBusy('graph')
      assertNoArrays(updatedData, 'updated_data')
      const e = state.entities.get(entityName)
      if (!e) throw httpError(404, 'Entity not found: ' + entityName)
      Object.assign(e, updatedData)
      return { status: 'success', updated_entity: e }
    },
    async entityDelete(entityName) {
      assertNotBusy('graph')
      if (!state.entities.has(entityName)) throw httpError(404, 'Entity not found: ' + entityName)
      state.entities.delete(entityName)
      // 级联删除涉及该实体的关系
      for (const [k, r] of state.relations.entries()) {
        if (r.source === entityName || r.target === entityName) state.relations.delete(k)
      }
      return { status: 'success' }
    },
    async entityMerge(entitiesToChange, entityToChangeInto) {
      assertNotBusy('graph')
      const target = state.entities.get(entityToChangeInto)
      if (!target) throw httpError(404, 'Entity not found: ' + entityToChangeInto)
      for (const name of entitiesToChange) {
        const src = state.entities.get(name)
        if (!src) throw httpError(404, 'Entity not found: ' + name)
        // 关系重挂到目标实体
        for (const [k, r] of state.relations.entries()) {
          if (r.source === name) { state.relations.delete(k); state.relations.set(entityToChangeInto + '\u0000' + r.target, { ...r, source: entityToChangeInto }) }
          if (r.target === name) { state.relations.delete(k); state.relations.set(r.source + '\u0000' + entityToChangeInto, { ...r, target: entityToChangeInto }) }
        }
        state.entities.delete(name)
      }
      return { status: 'success' }
    },
    async relationCreate(sourceEntity, targetEntity, relationData) {
      assertNotBusy('graph')
      assertNoArrays(relationData, 'relation_data')
      if (!state.entities.has(sourceEntity) || !state.entities.has(targetEntity)) throw httpError(404, 'entity not found')
      state.relations.set(sourceEntity + '\u0000' + targetEntity, { source: sourceEntity, target: targetEntity, ...relationData })
      return { status: 'success' }
    },
    async relationEdit(sourceId, targetId, updatedData) {
      assertNotBusy('graph')
      assertNoArrays(updatedData, 'updated_data')
      const r = state.relations.get(sourceId + '\u0000' + targetId)
      if (!r) throw httpError(404, 'relation not found')
      Object.assign(r, updatedData)
      return { status: 'success' }
    },
    async relationDelete(sourceEntity, targetEntity) {
      assertNotBusy('graph')
      if (!state.relations.delete(sourceEntity + '\u0000' + targetEntity)) throw httpError(404, 'relation not found')
      return { status: 'success' }
    },
    async labelSearch(q, limit = 20) {
      const needle = String(q || '').toLowerCase()
      return [...state.entities.keys()].filter((n) => !needle || n.toLowerCase().includes(needle)).slice(0, limit)
    },
    async labelList() { return [...state.entities.keys()] },
    async graphs(opts = {}) {
      if (!opts.label) throw httpError(400, 'label is required') // 怪癖 7
      const nodes = [...state.entities.entries()].slice(0, opts.max_nodes || 200)
        .map(([id, e]) => ({ id, properties: { entity_type: e.entity_type || '', description: e.description || '', source_id: e.source_id || '' } }))
      const edges = [...state.relations.values()].slice(0, opts.max_nodes || 200)
        .map((r, i) => ({ id: 'r' + i, source: r.source, target: r.target, properties: { description: r.description || '', weight: r.weight || 1 } }))
      return { nodes, edges }
    },
  }

  return engine
}
