/**
 * 契约测试 · 单一写入口 service。
 *
 * 覆盖：origin 策略链（agent 无审批 → 403，ingest/retry 豁免，user/system 直行）、
 * 幂等（同 source 409、会话反哺二次走替换）、retryDoc 显式 doc_ids（v1 双 bug 修正）、
 * 文件名校音/扩展校验、listDocuments 的 pending 意图合并。
 */
import { makeStack, makeRunner, ok, eq, throws, sleep } from './harness.mjs'

const { check, finish } = makeRunner('contract-service')

await check('origin 策略：agent 发起破坏性/图谱写 → 403；审批通过 → 放行', async () => {
  const s = await makeStack()
  s.registry.ensureDoc({ docId: 'doc-1', source: 'a.md', title: 'A' })
  s.registry.touchStatus('doc-1', 'active')
  await s.engine.entityCreate('E', { description: 'd' })

  const e1 = await throws(() => s.kb.deleteDoc({ docId: 'doc-1', origin: 'agent' }), /.*/, 'delete')
  eq(e1.status, 403, 'agent delete without approval must be 403')
  const e2 = await throws(() => s.kb.replaceText({ docId: 'doc-1', title: 't', text: 'x', origin: 'agent' }), /.*/, 'replace')
  eq(e2.status, 403)
  const e3 = await throws(() => s.kb.entityEdit({ name: 'E', updates: { description: 'x' }, origin: 'agent' }), /.*/, 'entityEdit')
  eq(e3.status, 403)
  const e4 = await throws(() => s.kb.entityCreate({ name: 'N', origin: 'agent' }), /.*/, 'entityCreate')
  eq(e4.status, 403)

  // 审批通过后放行
  const okDel = await s.kb.deleteDoc({ docId: 'doc-1', origin: 'agent', approved: true })
  ok(okDel.ok && okDel.intent_id)
  // user origin 直行
  const okEdit = await s.kb.entityEdit({ name: 'E', updates: { description: 'y' }, origin: 'user' })
  ok(okEdit.ok)
})

await check('origin 策略：ingest 与 retry 豁免审批（agent 可沉淀）', async () => {
  const s = await makeStack()
  const r = await s.kb.ingestText({ title: 'T', text: '正文', topic: 'T', actor: 'agent', origin: 'agent' })
  ok(r.ok && r.intent_id, 'agent ingest must be allowed')
  // retry：对 failed 文档
  const fr = await s.engine.insertText('x', 'bad.md')
  s.engine.advanceTicks()
  const d = s.engine._state.docs.get(fr.documents[0].id)
  d.status = 'failed'
  s.registry.ensureDoc({ docId: d.id, source: 'bad.md', title: 'B' })
  s.registry.touchStatus(d.id, 'failed')
  const rr = await s.kb.retryDoc({ docId: d.id, actor: 'agent' })
  ok(rr.ok, 'agent retry must be allowed')
  eq(s.registry.getDoc(d.id).status, 'processing')
})

await check('retryDoc：显式 doc_ids，不做全局重试（v1 双 bug 修正）', async () => {
  const s = await makeStack()
  let seenIds = null
  const orig = s.engine.reprocessFailed.bind(s.engine)
  s.engine.reprocessFailed = async (ids) => { seenIds = ids; return orig(ids) }
  const fr = await s.engine.insertText('x', 'r1.md')
  s.engine.advanceTicks()
  const d = s.engine._state.docs.get(fr.documents[0].id)
  d.status = 'failed'
  s.registry.ensureDoc({ docId: d.id, source: 'r1.md', title: 'R' })
  s.registry.touchStatus(d.id, 'failed')
  await s.kb.retryDoc({ docId: d.id })
  ok(Array.isArray(seenIds) && seenIds.length === 1 && seenIds[0] === d.id, 'must pass explicit single doc_ids, got ' + JSON.stringify(seenIds))
})

await check('ingestText：同 source 重复 → 409；user origin 正常', async () => {
  const s = await makeStack()
  const a = await s.kb.ingestText({ title: 'A', text: '内容一' })
  ok(a.ok)
  // 同 title+text → 同 source：意图仍在途 → 409（不撞引擎怪癖 1）
  const err = await throws(() => s.kb.ingestText({ title: 'A', text: '内容一' }), /相同来源/)
  eq(err.status, 409)
  const b = await s.kb.ingestText({ title: 'B', text: '内容三' })
  ok(b.ok && b.intent_id !== a.intent_id)
  // 空 title / 空 text
  await throws(() => s.kb.ingestText({ title: '', text: 'x' }), /标题/)
  await throws(() => s.kb.ingestText({ title: 't', text: '' }), /正文/)
})

await check('ingestFile：文件名净化 + 扩展校验 + 空文件/超限', async () => {
  const s = await makeStack()
  const r = await s.kb.ingestFile({ filename: '我们 的 文件!!name.md', bytes: Buffer.from('x'), title: 'F' })
  ok(r.ok)
  const pend = s.intents.get(r.intent_id)
  eq(pend.params.filename, '我们_的_文件_name.md', 'filename must be sanitized')
  const bad = await throws(() => s.kb.ingestFile({ filename: 'virus.exe', bytes: Buffer.from('x') }), /不支持的文件类型/)
  eq(bad.status, 400)
  await throws(() => s.kb.ingestFile({ filename: 'e.md', bytes: Buffer.alloc(0) }), /内容为空/)
  const good = await s.kb.ingestFile({ filename: 'n.docx', bytes: Buffer.alloc(200), title: 'N' })
  ok(good.ok, 'docx within supported list must pass')
  // 未定扩展（无后缀）→ 400
  await throws(() => s.kb.ingestFile({ filename: 'noext', bytes: Buffer.from('x') }), /不支持的文件类型/)
})

await check('saveConversation：同一会话消息二次沉淀 → 幂等替换', async () => {
  const s = await makeStack()
  const first = await s.kb.saveConversation({ sessionId: 's1', messageId: 'm1', title: '结论一', body: '第一版结论' })
  ok(first.intent_id)
  await s.intents.tickNow(); await s.intents.tickNow()
  s.engine.advanceTicks()
  await s.intents.tickNow()
  eq(s.intents.get(first.intent_id).status, 'verified')
  const docId = s.intents.get(first.intent_id).docId
  eq(s.registry.getDoc(docId).status, 'active')
  // 第二次：同 session/message → 走替换（先删旧再插新，source 不变）
  const second = await s.kb.saveConversation({ sessionId: 's1', messageId: 'm1', title: '结论一', body: '第二版结论' })
  ok(second.intent_id && second.intent_id !== first.intent_id)
  const it = s.intents.get(second.intent_id)
  eq(it.kind, 'replace', 're-save must be a replace intent, got ' + it.kind)
  eq(it.params.replacesDocId, docId)
})

await check('listDocuments：pending 意图并入第 1 页，带 intent 标记', async () => {
  const s = await makeStack()
  await s.kb.ingestText({ title: '待处理文档', text: 'x' })
  const page1 = s.kb.listDocuments({ page: 1, pageSize: 20 })
  eq(page1.total, 1)
  const item = page1.items[0]
  ok(item.intent === true, 'pending intent must be flagged')
  eq(item.status, 'pending')
  ok(item.id.startsWith('it-'), 'pending item id is the intent id')
  // 意图落档后从 pending 消失、正式文档出现
  await s.intents.tickNow(); await s.intents.tickNow()
  s.engine.advanceTicks()
  await s.intents.tickNow()
  const after = s.kb.listDocuments({ page: 1, pageSize: 20 })
  eq(after.total, 1)
  eq(after.items[0].intent, false)
  eq(after.items[0].status, 'active')
})

await check('管道忙：图谱写 409 → 友好错误码 pipeline_busy', async () => {
  const s = await makeStack()
  s.engine.setBusy(true)
  const err = await throws(() => s.kb.entityCreate({ name: 'X', description: 'd' }), /管道忙碌/)
  eq(err.status, 409)
  eq(err.code, 'pipeline_busy')
})

await check('审计：所有写入口落审计行', async () => {
  const s = await makeStack()
  const r = await s.kb.ingestText({ title: '审计文档', text: 'x', actor: 'tester' })
  await s.engine.entityCreate('E1', { description: 'd' })
  await s.kb.entityEdit({ name: 'E1', updates: { description: 'd2' }, actor: 'tester' })
  const e404 = await throws(() => s.kb.deleteDoc({ docId: 'doc-不存在', actor: 'tester' }), /文档不存在/)
  eq(e404.status, 404)
  const ingestAudit = s.registry.listAudit({ action: 'ingest' })
  ok(ingestAudit.total >= 1, 'ingest audit missing')
  const editAudit = s.registry.listAudit({ action: 'entity_edit' })
  eq(editAudit.total, 1)
  eq(editAudit.items[0].actor, 'tester')
  // 多值过滤：只返回两个指定 action 的并集，供前端分类筛选
  const multi = s.registry.listAudit({ actions: ['ingest', 'entity_edit'] })
  eq(multi.total, ingestAudit.total + editAudit.total)
  ok(multi.items.every((x) => x.action === 'ingest' || x.action === 'entity_edit'), 'actions 过滤混入了其他类型')
  ok(r.intent_id)
})

await check('docGraph：按 source_id 过滤实体与关系；文档不存在 → 404', async () => {
  const s = await makeStack()
  const r = await s.kb.ingestText({ title: '图谱文档', text: '正文', actor: 'tester' })
  await s.intents.tickNow(); await s.intents.tickNow()
  s.engine.advanceTicks()
  await s.intents.tickNow()
  const it = s.intents.get(r.intent_id)
  eq(it.status, 'verified', '前置：入库意图须完成，got ' + it.status)
  const docId = it.docId
  const source = s.registry.getDoc(docId).source

  // 模拟引擎抽取的实体（source_id 指回文档）；另一个实体来自别的文档
  await s.engine.entityCreate('来自本文档', { description: 'd1', source_id: source })
  await s.engine.entityCreate('来自其他文档', { description: 'd2', source_id: 'other.md' })
  await s.engine.relationCreate('来自本文档', '来自其他文档', { description: '跨文档' })

  const g = await s.kb.docGraph({ docId })
  eq(g.ok, true)
  eq(g.doc.id, docId)
  eq(JSON.stringify(g.entities.map((e) => e.id)), JSON.stringify(['来自本文档']), '只保留 source_id 命中本文档的实体')
  eq(g.relations.length, 0, '关系两端必须都来自本文档（另一端是外部实体，剔除）')

  await s.engine.entityCreate('来自本文档B', { description: 'd3', source_id: source + '，extra.md' })
  await s.engine.relationCreate('来自本文档', '来自本文档B', { description: '同文档关系' })
  const g2 = await s.kb.docGraph({ docId })
  eq(g2.entities.length, 2, 'source_id 为拼接串（GraphML 拍平形态）也要命中')
  eq(g2.relations.length, 1)
  eq(g2.relations[0].source, '来自本文档')

  const e404 = await throws(() => s.kb.docGraph({ docId: 'doc-不存在' }), /文档不存在/)
  eq(e404.status, 404)
})

const failed = finish()
if (process.argv[1] && import.meta.url === (await import('node:url')).pathToFileURL(process.argv[1]).href) process.exit(failed ? 1 : 0)
