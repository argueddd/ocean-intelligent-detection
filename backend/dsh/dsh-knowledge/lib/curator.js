/**
 * dsh-knowledge v2 · curator（检索日志数据层）。
 *
 *  - query_log：所有经 dsh 入口的检索请求 → append-only JSONL（带 session/client/latency/references）
 *  - retrieval_snapshot：查询完成后异步补挂的检索快照（补丁行按 query_id 归并），
 *    诊断按 query_id 还原"当时检索到了什么"
 *
 * v2 存储改造（对应重构 P1/P2：全文件读写 + 无界增长）：
 *  - query_log 改 createAppendLog：启动载入一次，读走内存、写走追加。
 *
 * 存储位置：${DSH_HOME:-$HOME/.dsh}/storages/dsh-knowledge/
 */

import fs from 'node:fs'
import path from 'node:path'
import { dataDir } from './registry.js'
import { createAppendLog } from './store.js'

export function createCurator({ registry = null, dir = dataDir(), log = () => {} } = {}) {
  fs.mkdirSync(dir, { recursive: true })

  const queryLog = createAppendLog(path.join(dir, 'query_log.jsonl'))

  // ---------------------------------------------------------------- query log

  /** 记录一次检索请求（append-only）。entry 可覆盖默认字段。 */
  function logQuery(entry) {
    const row = {
      ts: new Date().toISOString(),
      kb: 'company',
      session_id: null,
      client: 'tool',
      mode: 'mix',
      latency_ms: null,
      references: [],
      outcome: null, // gap（资料不足）/ neg_feedback / cited —— 供缺口分诊与采样回放
      ...entry,
    }
    queryLog.append(row)
    return row
  }

  /** 读最近 N 条（可选 kb/时间过滤），最新在前。检索快照补丁行按 query_id 归并进主行。 */
  function listQueries({ limit = 100, since = null, kb = 'company' } = {}) {
    let items = queryLog.readAll()
    const snapshots = new Map()
    const patched = new Set()
    for (const it of items) {
      if (it && it.__patch_query_id) {
        patched.add(it.__patch_query_id)
        if (it.retrieval_snapshot) snapshots.set(it.__patch_query_id, it.retrieval_snapshot)
      }
    }
    if (patched.size) items = items.filter((i) => !i.__patch_query_id)
    if (kb) items = items.filter((i) => i.kb === kb)
    if (since) items = items.filter((i) => i.ts >= since)
    const merged = items.map((i) => patched.has(i.query_id)
      ? { ...i, retrieval_snapshot: snapshots.get(i.query_id) || null }
      : { ...i, retrieval_snapshot: i.retrieval_snapshot || null })
    return merged.slice(-Number(limit)).reverse()
  }

  /** 按 query_id 精确取一次检索记录（诊断上下文与复核重放用；含归并后的检索快照）。 */
  function getQuery(queryId) {
    if (!queryId) return null
    return listQueries({ limit: 10000, kb: null }).find((q) => q.query_id === queryId) || null
  }

  /**
   * 异步补挂检索快照：查询主行已落盘后，/query/data 结果以补丁行追加，
   * 读取时按 query_id 归并。主查询路径不等待快照（不增加检索延迟）。
   */
  function attachRetrievalSnapshot(queryId, snapshot) {
    if (!queryId || !snapshot) return null
    const row = { ts: new Date().toISOString(), kb: 'company', __patch_query_id: queryId, retrieval_snapshot: snapshot }
    queryLog.append(row)
    return row
  }

  return {
    dir,
    logQuery,
    listQueries,
    getQuery,
    attachRetrievalSnapshot,
  }
}
