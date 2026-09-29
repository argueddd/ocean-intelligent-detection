/**
 * 契约测试 · curator（检索日志数据层）。
 *
 * 覆盖：query_log 追加/读取/重启恢复、检索快照补丁行归并（attachRetrievalSnapshot
 * 与 logQuery 直传两种形态）。
 */
import { makeStack, makeRunner, ok, eq } from './harness.mjs'

const { check, finish } = makeRunner('contract-curator')

await check('query_log：追加 + 最新在前 + limit/since 过滤', async () => {
  const s = await makeStack()
  s.curator.logQuery({ query: '甲', references: [{ file: 'a.md' }], outcome: 'cited' })
  s.curator.logQuery({ query: '乙', latency_ms: 5 })
  s.curator.logQuery({ query: '丙', kb: 'other' })
  const all = s.curator.listQueries({ kb: 'company' })
  eq(all.length, 2)
  eq(all[0].query, '乙', 'newest first')
  eq(all[1].references.length, 1)
  const one = s.curator.listQueries({ limit: 1 })
  eq(one.length, 1)
  const future = new Date(Date.now() + 60 * 1000).toISOString()
  eq(s.curator.listQueries({ since: future }).length, 0, 'since filters by ts')
  // 重启（同盘重建）后可读
  const s2 = await makeStack({ dir: s.dir, engine: s.engine })
  eq(s2.curator.listQueries({ kb: 'company' }).length, 2, 'query log survives restart')
})

await check('检索快照：异步补丁行按 query_id 归并 + getQuery 精确取', async () => {
  const s = await makeStack()
  s.curator.logQuery({ query_id: 'q-a', query: '问题A' })
  s.curator.logQuery({ query_id: 'q-b', query: '问题B' })
  // 查询完成后异步补快照（补丁行，不追加主行）
  s.curator.attachRetrievalSnapshot('q-a', { entities: [], relationships: [], chunks: [{ reference_id: 'c-1', file_path: 'a.md', content: 'x' }], references: [] })
  const all = s.curator.listQueries({ kb: null })
  eq(all.length, 2, 'patch row merged, not a separate query')
  const qa = s.curator.getQuery('q-a')
  eq(qa.query, '问题A')
  ok(qa.retrieval_snapshot && qa.retrieval_snapshot.chunks.length === 1, 'snapshot attached to main row')
  const qb = s.curator.getQuery('q-b')
  eq(qb.retrieval_snapshot, null, 'unpatched query has null snapshot')
  eq(s.curator.getQuery('q-nope'), null)
  // 后补的快照覆盖早补的（末行生效）
  s.curator.attachRetrievalSnapshot('q-a', { entities: [], relationships: [], chunks: [], references: [], truncated: true })
  eq(s.curator.getQuery('q-a').retrieval_snapshot.truncated, true, 'latest snapshot wins')
  // 主行自带快照（logQuery 直传）也可读
  s.curator.logQuery({ query_id: 'q-c', query: '问题C', retrieval_snapshot: { entities: [], relationships: [], chunks: [], references: [] } })
  eq(s.curator.getQuery('q-c').retrieval_snapshot.entities.length, 0, 'inline snapshot readable')
  // 重启后归并仍成立
  const s2 = await makeStack({ dir: s.dir, engine: s.engine })
  eq(s2.curator.getQuery('q-a').retrieval_snapshot.truncated, true, 'snapshot merge survives restart')
})

const failed = finish()
if (process.argv[1] && import.meta.url === (await import('node:url')).pathToFileURL(process.argv[1]).href) process.exit(failed ? 1 : 0)
