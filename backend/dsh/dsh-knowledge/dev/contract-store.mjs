/**
 * 契约测试 · store 原语（原子写 / 防抖 JSON store / append-only 账本 / 压缩）。
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { makeRunner, ok, eq, sleep } from './harness.mjs'

const { check, finish } = makeRunner('contract-store')
const { writeJsonAtomic, createJsonStore, createAppendLog } = await import('../lib/store.js')

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'kb-store-'))

await check('writeJsonAtomic：写后无 .tmp 残留，内容可读', async () => {
  const dir = tmp()
  const p = path.join(dir, 'x.json')
  writeJsonAtomic(p, { a: 1 })
  eq(JSON.parse(fs.readFileSync(p, 'utf8')).a, 1)
  eq(fs.readdirSync(dir).length, 1, 'tmp file remains')
})

await check('createJsonStore：set 防抖合并，flushSync 立即落盘', async () => {
  const dir = tmp()
  const p = path.join(dir, 's.json')
  const store = createJsonStore(p, { debounceMs: 80 })
  ok(store.get() === null, 'fresh store should be null')
  store.set({ n: 1 })
  store.set({ n: 2 })
  ok(!fs.existsSync(p), 'debounced: file should not exist yet')
  store.set({ n: 3 })
  store.flushSync()
  eq(JSON.parse(fs.readFileSync(p, 'utf8')).n, 3)
  // touch：就地变更后标脏
  const data = store.get()
  data.n = 4
  store.touch()
  await sleep(140)
  eq(JSON.parse(fs.readFileSync(p, 'utf8')).n, 4, 'touch did not persist')
})

await check('createJsonStore：重启加载已有文件', async () => {
  const dir = tmp()
  const p = path.join(dir, 's.json')
  const a = createJsonStore(p, { debounceMs: 50 })
  a.set({ k: 'v' })
  a.flushSync()
  const b = createJsonStore(p, { debounceMs: 50 })
  eq(b.get().k, 'v', 'reload failed')
})

await check('createAppendLog：append 后 readAll 内存读；新实例读盘', async () => {
  const dir = tmp()
  const p = path.join(dir, 'l.jsonl')
  const log = createAppendLog(p)
  eq(log.length, 0)
  log.append({ id: 'a', v: 1 })
  log.append({ id: 'b', v: 2 })
  eq(log.readAll().length, 2)
  const log2 = createAppendLog(p)
  eq(log2.readAll().length, 2, 'reopen lost rows')
  eq(log2.readAll()[1].v, 2)
  // 坏行跳过：截断半行后重建
  fs.appendFileSync(p, '{"id":"c"', 'utf8')
  const log3 = createAppendLog(p)
  eq(log3.readAll().length, 2, 'corrupt line should be skipped')
})

await check('compact：同 key 末行生效 + dropPredicate 剔除', async () => {
  const dir = tmp()
  const p = path.join(dir, 'l.jsonl')
  const log = createAppendLog(p)
  log.append({ id: 'P-1', status: 'proposed' })
  log.append({ id: 'P-2', status: 'proposed' })
  log.append({ id: 'P-1', status: 'approved' })
  log.append({ id: 'P-3', status: 'rejected' })
  const dropped = log.compact({ keyOf: (r) => r.id, dropPredicate: (r) => r.status === 'rejected' })
  eq(dropped, 2, 'compact should drop 2 rows')
  const rows = log.readAll()
  eq(rows.length, 2)
  eq(rows.find((r) => r.id === 'P-1').status, 'approved', 'last row per id must win')
  ok(!rows.some((r) => r.id === 'P-3'), 'rejected row should be dropped')
  // 文件与内存一致
  const log2 = createAppendLog(p)
  eq(log2.readAll().length, 2, 'file diverges from memory after compact')
})

const failed = finish()
if (process.argv[1] && import.meta.url === (await import('node:url')).pathToFileURL(process.argv[1]).href) process.exit(failed ? 1 : 0)
