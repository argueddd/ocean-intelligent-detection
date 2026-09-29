/**
 * dsh-knowledge v2 · 文档注册表 + 审计流水。
 *
 * harness 侧的权威元数据（意图账本的"事实源"视图）：版本链、主题、状态、
 * 来源与全部写操作审计。索引数据在 LightRAG（按 doc_id/file_path 关联）。
 *
 * v2 存储改造（对应重构 P1：全文件读写 + 无界增长）：
 *  - registry.json：启动载入内存索引（byId/bySource），写盘防抖合并 + 原子替换；
 *    文件格式与 v1 完全兼容（{documents, settings}），无迁移成本。
 *  - audit.jsonl：append-only，启动一次载入内存；listAudit 只读内存不再整读文件。
 *  - findBySource O(1)（v1 为全表线性扫，会话反哺幂等检查热路径）。
 *
 * 存储位置：${DSH_HOME:-$HOME/.dsh}/storages/dsh-knowledge/
 */

import fs from 'node:fs'
import path from 'node:path'
import { createJsonStore, createAppendLog } from './store.js'

export function dataDir() {
  const home = process.env.DSH_HOME || path.join(process.env.HOME || '/tmp', '.dsh')
  return process.env.KB_DATA_DIR || path.join(home, 'storages', 'dsh-knowledge')
}

export function createRegistry(opts = {}) {
  const dir = opts.dir || dataDir()
  fs.mkdirSync(dir, { recursive: true })
  const regPath = path.join(dir, 'registry.json')
  const auditPath = path.join(dir, 'audit.jsonl')

  const store = createJsonStore(regPath, { debounceMs: 150 })
  const auditLog = createAppendLog(auditPath)

  let data = store.get() || { documents: {}, settings: { default_kb: 'company', rerank_enabled: false } }
  if (!data.settings) data.settings = { default_kb: 'company', rerank_enabled: false }

  // ---- 内存索引 ----
  const byId = new Map() // docId -> entry（就是 data.documents 的值引用）
  const bySource = new Map() // source -> entry
  for (const [docId, entry] of Object.entries(data.documents)) {
    byId.set(docId, entry)
    if (entry.source) bySource.set(entry.source, entry)
  }

  function persist() { store.set(data) }

  let emit = null // (eventName, payload) => void
  function fire(name, payload) {
    if (emit) { try { emit(name, payload) } catch (e) { /* 监听器异常不阻断 */ } }
  }

  const now = () => new Date().toISOString()

  function appendAudit(entry) {
    const row = { ts: now(), kb: 'company', actor: 'system', action: 'unknown', target: '', detail: null, ...entry }
    auditLog.append(row)
    fire('kb.audit', row)
    return row
  }

  function indexEntry(entry) {
    byId.set(entry.doc_id, entry)
    if (entry.source) bySource.set(entry.source, entry)
  }

  return {
    dir,
    settings: data.settings,
    onEvent(cb) { emit = cb },

    /** 持久化更新设置（如 curator 的 auto_commit_ops）。 */
    updateSettings(patch) {
      Object.assign(data.settings, patch || {})
      persist()
      return data.settings
    },

    // ---- documents ----
    getDoc(docId) { return byId.get(docId) || null },
    findBySource(source) { return bySource.get(source) || null },
    listDocs(filter = {}) {
      let items = [...byId.values()]
      if (filter.status) items = items.filter((d) => d.status === filter.status)
      if (filter.topic) items = items.filter((d) => d.topic === filter.topic)
      if (filter.q) {
        const needle = String(filter.q).toLowerCase()
        items = items.filter((d) => d.title.toLowerCase().includes(needle) || d.source.toLowerCase().includes(needle))
      }
      if (filter.excludeRetired) items = items.filter((d) => d.status !== 'retired' && d.status !== 'outdated')
      items.sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))
      return items
    },

    /** Register (or refresh) a document row. Keeps version chain intact. */
    ensureDoc({ docId, source, title, topic = '未分类', actor = 'system', kb = 'company', version = 1, status = 'pending', extra = null }) {
      const existing = byId.get(docId)
      if (existing) {
        if (source !== undefined && source) {
          if (existing.source && existing.source !== source) bySource.delete(existing.source)
          existing.source = source
          bySource.set(source, existing)
        }
        if (title !== undefined) existing.title = title
        if (topic !== undefined) existing.topic = topic
        existing.updated_at = now()
        persist()
        return existing
      }
      const entry = {
        doc_id: docId,
        kb,
        source: source || '',
        title: title || source || docId,
        topic,
        status,
        version,
        versions: [{ v: version, ts: now(), actor, reason: 'create' }],
        created_at: now(),
        updated_at: now(),
        extra,
      }
      data.documents[docId] = entry
      indexEntry(entry)
      persist()
      appendAudit({ actor, action: 'ingest', target: docId, detail: { title: entry.title, topic } })
      fire('kb.document.ingested', { kb, document: { id: docId, title: entry.title, status: entry.status }, actor })
      return entry
    },

    /**
     * 批量收养引擎中已存在、但注册表还没有的文档（幂等）。
     * 不逐条审计、不逐条发事件，只追加一条汇总审计（registry_adopted）。
     */
    adoptDocs(rows, actor = 'system') {
      const statusMap = {
        processed: 'active', preprocessed: 'active', failed: 'failed',
        parsing: 'processing', analyzing: 'processing', processing: 'processing', pending: 'pending',
      }
      let added = 0
      for (const row of rows) {
        const docId = String(row.id)
        if (byId.has(docId)) continue
        const entry = {
          doc_id: docId,
          kb: 'company',
          source: row.file_path || '',
          title: row.file_path || docId,
          topic: '未分类',
          status: statusMap[row.status] || row.status || 'pending',
          status_detail: row.error_msg || '',
          version: 1,
          versions: [{ v: 1, ts: now(), actor, reason: 'adopted' }],
          created_at: row.created_at || now(),
          updated_at: row.updated_at || now(),
          adopted: true,
        }
        data.documents[docId] = entry
        indexEntry(entry)
        added++
      }
      if (added > 0) {
        persist()
        appendAudit({ actor, action: 'registry_adopted', target: 'engine', detail: { count: added } })
      }
      return added
    },

    touchStatus(docId, status, detail) {
      const entry = byId.get(docId)
      if (!entry) return null
      const prev = entry.status
      entry.status = status
      entry.updated_at = now()
      if (detail !== undefined) entry.status_detail = detail
      persist()
      if (prev !== status) {
        if (status === 'failed') {
          fire('kb.document.failed', { kb: entry.kb, document: { id: docId, title: entry.title }, reason: detail || '' })
        } else {
          fire('kb.document.updated', { kb: entry.kb, document: { id: docId, title: entry.title, status }, actor: 'engine' })
        }
      }
      return entry
    },

    /**
     * 版本替换（内容寻址语义：新内容 = 新 doc_id）：
     * 旧 docId 记 outdated（保留历史），新 docId 继承版本链 v+1 顶上。
     */
    replaceDoc({ docId, newDocId, source, title, topic, actor = 'system', reason = '' }) {
      const old = byId.get(docId)
      if (!old) return null
      const next = old.version + 1
      old.status = 'outdated'
      old.superseded_by = newDocId
      old.updated_at = now()
      const entry = {
        doc_id: newDocId,
        kb: old.kb,
        source: source !== undefined ? source : old.source,
        title: title !== undefined ? title : old.title,
        topic: topic !== undefined ? topic : old.topic,
        status: 'active',
        version: next,
        versions: [...old.versions, { v: next, ts: now(), actor, reason: reason || 'replace' }],
        created_at: now(),
        updated_at: now(),
      }
      data.documents[newDocId] = entry
      indexEntry(entry)
      persist()
      appendAudit({ actor, action: 'replace', target: newDocId, detail: { from_doc: docId, from_version: old.version, to_version: next, reason } })
      fire('kb.document.updated', { kb: entry.kb, document: { id: newDocId, title: entry.title, version: next }, from_version: old.version, actor })
      return entry
    },

    retireDoc(docId, actor = 'system', status = 'retired') {
      const entry = byId.get(docId)
      if (!entry) return null
      entry.status = status
      entry.retired_at = now()
      entry.updated_at = now()
      persist()
      if (status === 'retired') {
        appendAudit({ actor, action: 'delete', target: docId, detail: { title: entry.title } })
        fire('kb.document.deleted', { kb: entry.kb, document: { id: docId, title: entry.title }, actor })
      }
      return entry
    },

    removeDoc(docId) {
      const entry = byId.get(docId)
      if (!entry) return false
      delete data.documents[docId]
      if (entry.source && bySource.get(entry.source) === entry) bySource.delete(entry.source)
      byId.delete(docId)
      persist()
      return true
    },

    // ---- audit ----
    audit(entry) { return appendAudit(entry) },

    listAudit({ action, actions, actor, kb, page = 1, pageSize = 50 } = {}) {
      let items = auditLog.readAll()
      // actions 为多值过滤（前端按分类筛选）；action 单值保持兼容
      const actionFilter = Array.isArray(actions) && actions.length ? actions : (action ? [action] : null)
      if (actionFilter) items = items.filter((i) => actionFilter.includes(i.action))
      if (actor) items = items.filter((i) => i.actor === actor)
      if (kb) items = items.filter((i) => i.kb === kb)
      items.reverse() // newest first
      const total = items.length
      const start = (page - 1) * pageSize
      return { total, items: items.slice(start, start + pageSize) }
    },

    // ---- events / health ----
    emitHealth(detail) {
      fire('kb.engine.health', { kb: 'company', healthy: detail && detail.status === 'healthy', detail })
    },
    emitGraph(op, payload) {
      fire('kb.graph.changed', { kb: 'company', op, ...payload })
    },

    // ---- stats ----
    stats() {
      const byStatus = {}
      let active = 0
      for (const d of byId.values()) {
        byStatus[d.status] = (byStatus[d.status] || 0) + 1
        if (d.status === 'active' || d.status === 'processing' || d.status === 'pending') active++
      }
      return {
        documents_total: byId.size,
        by_status: byStatus,
        failed: [...byId.values()].filter((d) => d.status === 'failed').map((d) => ({ id: d.doc_id, title: d.title, reason: d.status_detail || '' })),
        missing: byStatus.missing || 0,
      }
    },

    /** 就绪前强制落盘（关闭/测试用）。 */
    flushSync() { store.flushSync() },
  }
}
