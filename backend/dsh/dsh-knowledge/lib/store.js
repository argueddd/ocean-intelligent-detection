/**
 * dsh-knowledge v2 · 存储原语（零依赖，plain Node ESM）。
 *
 * 三个原语，覆盖注册表/账本/日志三类落盘形态：
 *  - createJsonStore：单 JSON 文档，原子写（tmp+rename），可防抖合并高频写。
 *  - createAppendLog：append-only JSONL，启动一次载入内存，之后读走内存、写走追加。
 *  - compactJsonl：把 JSONL 里"同 key 末行生效"的账本压缩成快照重写（行数超阈值时用）。
 *
 * 设计要点（对应 v2 重构 P1 问题：全文件读写 + 无界增长）：
 *  - 读路径全部走内存索引，文件只在线程启动与压缩时被整体读一次。
 *  - JSON 写盘带防抖（默认 200ms），高频繁状态变更不再每次全量序列化。
 *  - 追加写永不重读文件；账本压缩显式触发，保留被压行数与时间审计。
 */

import fs from 'node:fs'
import path from 'node:path'

/** 原子写单个 JSON 文件（tmp + rename，同目录保证 rename 原子性）。 */
export function writeJsonAtomic(filePath, value) {
  const tmp = filePath + '.tmp'
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2))
  fs.renameSync(tmp, filePath)
}

/**
 * 单 JSON 文档存储。load() 已在创建时完成；save() 防抖合并。
 * flushSync() 供关闭/测试前强制落盘。
 */
export function createJsonStore(filePath, { debounceMs = 200 } = {}) {
  let data = null
  try {
    data = JSON.parse(fs.readFileSync(filePath, 'utf8'))
  } catch (e) { /* 首次启动或损坏：从空开始 */ }
  let timer = null
  let dirty = false

  function save() {
    dirty = true
    if (timer) return
    timer = setTimeout(() => {
      timer = null
      if (!dirty) return
      dirty = false
      try { writeJsonAtomic(filePath, data) } catch (e) { dirty = true /* 下次再试 */ }
    }, debounceMs)
    if (typeof timer.unref === 'function') timer.unref()
  }

  return {
    get: () => data,
    set(next) { data = next; save() },
    /** 就地变更后调用（引用未变也要标记脏）。 */
    touch() { save() },
    flushSync() {
      if (timer) { clearTimeout(timer); timer = null }
      if (dirty) { dirty = false; writeJsonAtomic(filePath, data) }
    },
  }
}

/**
 * append-only JSONL 日志。创建时整读一次建内存索引；
 * 之后 append 同步写文件并推进内存，readAll 只读内存。
 */
export function createAppendLog(filePath, { compact = null } = {}) {
  let rows = []
  try {
    const raw = fs.readFileSync(filePath, 'utf8')
    // 崩溃可能留下半行。保留原始内容，并隔开下一条记录；完整但缺换行的末行也保留。
    if (raw && !raw.endsWith('\n')) fs.appendFileSync(filePath, '\n', 'utf8')
    rows = raw.split('\n').filter(Boolean)
      .map((l) => { try { return JSON.parse(l) } catch (e) { return null } })
      .filter(Boolean)
  } catch (e) {
    if (e.code !== 'ENOENT') throw e
  }

  function append(row) {
    fs.appendFileSync(filePath, JSON.stringify(row) + '\n', 'utf8')
    rows.push(row)
    return row
  }

  return {
    append,
    readAll: () => rows,
    get length() { return rows.length },
    /**
     * 压缩：对每条行调用 keyOf 取分组键，同键只保留末行（或 keepAll 时保留全部），
     * 原子重写文件并重建内存。返回压缩掉的历史行数。
     */
    compact({ keyOf = null, dropPredicate = null } = {}) {
      if (!keyOf && !dropPredicate) return 0
      const before = rows.length
      let kept = rows
      if (keyOf) {
        const latest = new Map()
        for (const r of rows) latest.set(keyOf(r), r)
        kept = [...latest.values()]
      }
      if (dropPredicate) kept = kept.filter((r) => !dropPredicate(r))
      if (kept.length === before) return 0
      const keptRows = kept
      const tmp = filePath + '.tmp'
      const body = keptRows.map((r) => JSON.stringify(r)).join('\n')
      fs.writeFileSync(tmp, body ? body + '\n' : '')
      fs.renameSync(tmp, filePath)
      rows = keptRows
      return before - keptRows.length
    },
  }
}
