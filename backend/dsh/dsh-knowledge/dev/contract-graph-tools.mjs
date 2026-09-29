/**
 * dsh-knowledge v2 · 契约测试：模型工具层的图谱链路。
 *
 * 用 mock 宿主 ctx 装配 lib/index.js 插件入口；引擎请求打给本地 HTTP shim
 * （把 LightRAG graph 端点映射到 createFakeEngine），锁定：
 *  - kb_graph_search：检索 / 单命中自动展开 / label 展开 / max_nodes / 未知 kb / render 文本
 *  - kb_update 图谱操作：审批拒绝不执行 / 审批通过落库 / pipeline busy 409 / render 文本
 *
 * KB_DATA_DIR 指向临时目录（curator/feedback 不落真实 ~/.dsh）。
 * 运行：node dev/contract-graph-tools.mjs
 */

import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'

process.env.KB_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'kb-graphtools-'))

const { makeRunner, ok, eq, throws } = await import('./harness.mjs')
const { check, finish } = makeRunner('contract-graph-tools')

// ------------------------------------------------------------ LightRAG shim（graph 端点 → fake-engine）

const engine = (await import('../lib/fake-engine.js')).createFakeEngine()

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      const text = Buffer.concat(chunks).toString('utf8')
      try { resolve(text ? JSON.parse(text) : {}) } catch (e) { reject(e) }
    })
    req.on('error', reject)
  })
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || '/', 'http://shim')
  const send = (code, data) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(data)) }
  const notFound = () => send(404, { detail: 'shim: not implemented: ' + req.method + ' ' + url.pathname })
  try {
    const body = await readBody(req)
    if (req.method === 'GET' && url.pathname === '/health') {
      return send(200, { status: 'healthy', core_version: 'fake-1.5.6', pipeline_busy: false })
    }
    if (req.method === 'GET' && url.pathname === '/graph/label/search') {
      return send(200, await engine.labelSearch(url.searchParams.get('q') || '', Number(url.searchParams.get('limit')) || 20))
    }
    if (req.method === 'GET' && url.pathname === '/graph/label/list') {
      return send(200, await engine.labelList())
    }
    if (req.method === 'GET' && url.pathname === '/graphs') {
      return send(200, await engine.graphs({
        label: url.searchParams.get('label') || undefined,
        max_depth: Number(url.searchParams.get('max_depth')) || 2,
        max_nodes: Number(url.searchParams.get('max_nodes')) || 200,
      }))
    }
    if (req.method === 'POST' && url.pathname === '/graph/entity/create') {
      return send(200, await engine.entityCreate(body.entity_name, body.entity_data || {}))
    }
    if (req.method === 'POST' && url.pathname === '/graph/entity/edit') {
      return send(200, await engine.entityEdit(body.entity_name, body.updated_data || {}))
    }
    if (req.method === 'POST' && url.pathname === '/graph/entities/merge') {
      return send(200, await engine.entityMerge(body.entities_to_change, body.entity_to_change_into))
    }
    if (req.method === 'DELETE' && url.pathname === '/graph/entity/delete') {
      return send(200, await engine.entityDelete(body.entity_name))
    }
    if (req.method === 'POST' && url.pathname === '/graph/relation/create') {
      return send(200, await engine.relationCreate(body.source_entity, body.target_entity, body.relation_data || {}))
    }
    if (req.method === 'POST' && url.pathname === '/graph/relation/edit') {
      return send(200, await engine.relationEdit(body.source_id, body.target_id, body.updated_data || {}))
    }
    if (req.method === 'DELETE' && url.pathname === '/graph/relation/delete') {
      return send(200, await engine.relationDelete(body.source_entity, body.target_entity))
    }
    // 启动对账/健康采样等未实现端点：明确 404，由调用方按失败分诊
    notFound()
  } catch (e) {
    send(e && e.status ? e.status : 500, { detail: String(e && e.message ? e.message : e) })
  }
})
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const shimPort = server.address().port
process.env.LIGHTRAG_BASE_URL = 'http://127.0.0.1:' + shimPort

// ------------------------------------------------------------ mock 宿主 ctx + 装配插件

const tools = new Map()
const disposers = []
const approvalCalls = []
let approvalDecide = async () => 'allowed-once'

const ctx = {
  webServer: { register() {}, host: '127.0.0.1', port: shimPort },
  tools: { register: (def) => tools.set(def.name, def) },
  approval: { request: async (req) => { approvalCalls.push(req); return approvalDecide(req) } },
  logger: { info() {} },
  emit() {},
  effect(fn) { const d = fn(); if (typeof d === 'function') disposers.push(d) },
}

const { apply } = await import('../lib/index.js')
apply(ctx)

const graphSearch = tools.get('kb_graph_search')
const kbUpdate = tools.get('kb_update')

/** kb_update 审批链路需要 exec.agent（mock 宿主下普通对象即可）。 */
const execAgent = { agent: { id: 'test-agent' }, callId: 'call-test' }

ok(graphSearch, 'kb_graph_search 已注册')
ok(kbUpdate, 'kb_update 已注册')

// ------------------------------------------------------------ kb_graph_search

await check('search 空图：无匹配，render 说明没有匹配', async () => {
  const v = await graphSearch.execute({ query: '不存在的实体' })
  eq(v.ok, true)
  eq(v.matches.length, 0)
  const text = graphSearch.output.render({}, v)[0].text
  ok(text.includes('没有匹配的实体'), 'render 应说明没有匹配，实际: ' + text)
})

await check('search 多命中：只返回 matches 不展开子图', async () => {
  await engine.entityCreate('研发部', { entity_type: 'organization', description: '研发部门' })
  await engine.entityCreate('研发中心', { entity_type: 'organization', description: '研发中台' })
  const v = await graphSearch.execute({ query: '研发' })
  ok(v.matches.includes('研发部') && v.matches.includes('研发中心'), '应命中两个实体: ' + JSON.stringify(v.matches))
  eq(v.entities, undefined, '多命中不应展开子图')
})

await check('search 单命中：自动展开子图（实体+关系进 render）', async () => {
  await engine.relationCreate('研发部', '研发中心', { description: '下属关系' })
  const v = await graphSearch.execute({ query: '研发中心' })
  eq(v.matches.length, 1)
  ok(v.entities.some((e) => e.id === '研发部'), '子图应含研发部')
  ok(v.entities.some((e) => e.id === '研发中心'), '子图应含研发中心')
  ok(v.relations.some((r) => r.source === '研发部' && r.target === '研发中心'), '子图应含关系')
  const text = graphSearch.output.render({}, v)[0].text
  ok(text.includes('研发部') && text.includes('研发中心'), '实体名必须进 render（模型可见面）')
  ok(text.includes('研发部 → 研发中心'), '关系必须进 render，实际: ' + text)
})

await check('search 指定 label：不看 query 直接展开', async () => {
  const v = await graphSearch.execute({ label: '研发部' })
  ok(v.entities.some((e) => e.id === '研发中心'), 'label 展开应含邻居研发中心')
})

await check('search max_nodes：下限 clamp 10 生效', async () => {
  for (let i = 0; i < 12; i++) await engine.entityCreate('批量实体' + i, { entity_type: 'thing' })
  const v = await graphSearch.execute({ label: '研发部', max_nodes: 1 })
  eq(v.entities.length, 10, 'max_nodes=1 应 clamp 到下限 10')
})

await check('search 未知 kb：400', async () => {
  await throws(() => graphSearch.execute({ query: 'x', kb: 'nope' }), /未知知识库/)
})

// ------------------------------------------------------------ kb_update 图谱操作（审批链路）

await check('entity_create 审批拒绝：报错且不落库', async () => {
  approvalDecide = async () => 'rejected'
  await throws(() => kbUpdate.execute({ action: 'entity_create', entity_name: '测试部', reason: '测试' }, execAgent), /人工审批未通过/)
  const hit = await engine.labelSearch('测试部', 20)
  eq(hit.length, 0, '拒绝后实体不应存在')
  eq(approvalCalls[approvalCalls.length - 1].toolName, 'kb_update')
  ok(approvalCalls[approvalCalls.length - 1].reason.includes('entity_create'), '审批 reason 应带动作名')
  approvalDecide = async () => 'allowed-once'
})

await check('entity_create 审批通过：落库并进 render', async () => {
  const v = await kbUpdate.execute({ action: 'entity_create', entity_name: '测试部', entity_type: 'organization', description: '测试用实体' }, execAgent)
  eq(v.ok, true)
  eq(v.entity, '测试部')
  const text = kbUpdate.output.render({}, v)[0].text
  ok(text.includes('测试部'), 'render 应含实体名')
  const hit = await engine.labelSearch('测试部', 20)
  eq(hit.length, 1, '通过后实体应存在')
})

await check('entity_create 缺 entity_name：报错', async () => {
  await throws(() => kbUpdate.execute({ action: 'entity_create' }, execAgent), /entity_name/)
})

await check('relation_create 通过后 search 可见，relation_delete 后消失', async () => {
  const v = await kbUpdate.execute({ action: 'relation_create', src: '测试部', tgt: '研发部', description: '协作' }, execAgent)
  eq(v.ok, true)
  eq(v.relation.src, '测试部')
  eq(v.relation.tgt, '研发部')
  const seen = await graphSearch.execute({ label: '测试部' })
  ok(seen.relations.some((r) => r.source === '测试部' && r.target === '研发部'), '删除前关系应可见')
  await kbUpdate.execute({ action: 'relation_delete', src: '测试部', tgt: '研发部' }, execAgent)
  const gone = await graphSearch.execute({ label: '测试部' })
  ok(!gone.relations.some((r) => r.source === '测试部' && r.target === '研发部'), '删除后关系应消失')
})

await check('pipeline busy：审批通过但执行报 409 管道忙碌', async () => {
  engine.setBusy(true)
  try {
    await throws(() => kbUpdate.execute({ action: 'entity_create', entity_name: '忙碌部' }, execAgent), /管道忙碌/)
    const hit = await engine.labelSearch('忙碌部', 20)
    eq(hit.length, 0, '忙碌失败后实体不应存在')
  } finally {
    engine.setBusy(false)
  }
})

await check('未知 action：报错', async () => {
  await throws(() => kbUpdate.execute({ action: 'nope' }, execAgent), /未知 action/)
})

// ------------------------------------------------------------ 清理与收尾

for (const d of disposers.reverse()) {
  try { d() } catch (e) { /* 测试卸载顺序无关紧要 */ }
}
await new Promise((resolve) => server.close(resolve))
process.exit(finish())
