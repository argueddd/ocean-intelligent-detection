/**
 * render-smoke · 前端组件树冒烟测试。
 *
 * 以 stub React（createElement + 可重放 useState）渲染 client.js 的三个
 * 一级视图（总览 / 文档管理 / 反馈诊断）的全部子页组合，验证：
 *  1. 所有配置下组件树构建无异常（含空态、加载态）；
 *  2. 关键文案存在（质量指标 / 文档列表 / 实体检索 / 改进建议…）；
 *  3. 线性图标 svg 产出 path/circle/line/rect 节点；
 *  4. 跨视图焦点请求（viewRequest）落到目标子页并确认消费。
 */
import fs from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'

const ROOT = path.join(path.dirname(new URL(import.meta.url).pathname), '..')
const src = fs.readFileSync(path.join(ROOT, 'client/client.js'), 'utf8')

// ---- stub React：元素为普通对象；useState 槽位每次渲染重建 ----
// 子页预设：视图组件的第一个 useState 是 sub（KbDocsView/KbAutoView），
// 预先占用槽 0 即可渲染指定子页；其余 hook 全部走新建槽（初始值）。
let passState = []
let cursor = 0
/** >0 时按序执行前 N 个 useEffect（用于 viewRequest 消费测试），避免触发网络型 effect。 */
let effectBudget = 0
const React = {
  createElement: (type, props, ...children) => {
    const kids = children.filter((c) => c !== null && c !== undefined && c !== false && c !== true)
    // 与真实 React 一致：children 同时挂在 props.children（函数组件依赖它）与 el.children
    return { type, props: Object.assign({}, props, { children: kids }), children: kids }
  },
  useState: (init) => {
    const slot = passState[cursor] || (passState[cursor] = { value: typeof init === 'function' ? init() : init })
    const v = slot.value
    cursor++
    return [v, (nv) => { slot.value = typeof nv === 'function' ? nv(slot.value) : nv }]
  },
  useEffect: (fn) => {
    if (effectBudget <= 0) return
    effectBudget--
    try { fn() } catch { /* 冒烟环境无网络，effect 内的同步失败可忽略 */ }
  },
  useRef: (v) => ({ current: v }),
  useMemo: (fn) => fn(),
}
const requireShim = (name) => { if (name === 'react') return React; throw new Error('unexpected require: ' + name) }

// ---- 加载 client.js：捕获模块与 conversation.view 的三个注册条目 ----
let modExports = null
const captured = {}
globalThis.window = {
  __ModuleLoader__: {
    load: (mod) => { modExports = mod.factory(requireShim) },
  },
}
globalThis.document = {
  createElement: () => ({ setAttribute() {}, style: {}, remove() {} }),
  head: { appendChild() {} },
  addEventListener() {},
  removeEventListener() {},
}
eval(src)
assert.ok(modExports && typeof modExports.apply === 'function', 'module must export apply')

const slotsStub = {
  inject: (name, reg) => {
    const list = captured[name] || (captured[name] = [])
    const r = reg()
    if (r && r.render) list.push(r)
  },
  register: (meta, render) => ({ meta, render }),
}
modExports.apply({ slots: slotsStub, effect: () => {} })

const views = {}
for (const r of captured['conversation.view'] || []) views[r.meta.id] = r
assert.deepEqual(
  Object.keys(views).sort(),
  ['knowledge-auto', 'knowledge-docs', 'knowledge-health', 'knowledge-home'],
  'conversation.view 必须注册总览 / 文档与图谱管理 / 反馈与诊断 / 健康体检四个一级视图',
)

// ---- 递归渲染：函数型元素就地调用，收集全部文本与节点类型 ----
function renderTree(el, out) {
  if (el === null || el === undefined || el === false || el === true) return
  if (Array.isArray(el)) { for (const c of el) renderTree(c, out); return }
  if (typeof el === 'string' || typeof el === 'number') { out.text.push(String(el)); return }
  if (typeof el.type === 'function') { renderTree(el.type(el.props), out); return }
  out.types.push(el.type)
  if (el.props && el.props.className && typeof el.props.className === 'string') out.classes.push(el.props.className)
  if (el.children) renderTree(el.children, out)
}

function renderView(viewId, presetSub, props) {
  passState = presetSub !== undefined ? [{ value: presetSub }] : []
  cursor = 0
  const out = { text: [], types: [], classes: [] }
  renderTree(views[viewId].render(props), out)
  return { text: out.text.join('·'), out }
}

// ---- 断言全部页面组合 ----
const cases = [
  ['knowledge-home', undefined, ['知识库运营', '知识资产', '文档总数', '检索信号', '零命中率', '知识变更', '知识健康', '去健康体检']],
  ['knowledge-docs', undefined, ['文档列表']],
  ['knowledge-docs', 'add', ['上传文档', '录入文本']],
  ['knowledge-docs', 'graph', ['实体检索', '关联网络']],
  ['knowledge-auto', undefined, ['诊断总览', '让每一次反馈都变成一次改进', '待处理反馈', '最近修复', '诊断运营指标', '负反馈重复率', '问题层级分布']],
  ['knowledge-auto', 'feedback', ['反馈与诊断', '快速诊断']],
  ['knowledge-health', undefined, ['知识库健康体检', '开始体检', '还没有体检记录']],
  ['knowledge-auto', 'proposals', ['修复提案', '智能诊断', '暂无诊断提案']],
  ['knowledge-auto', 'execution', ['执行记录']],
]

for (const [viewId, presetSub, expects] of cases) {
  const page = renderView(viewId, presetSub)
  for (const e of expects) {
    assert.ok(page.text.includes(e), `${viewId}${presetSub ? '/' + presetSub : ''} 应包含「${e}」；实际文本片段：${page.text.slice(0, 300)}`)
  }
  console.log(`  ✓ ${viewId}${presetSub ? '/' + presetSub : ''} 渲染通过（含 ${page.text.length} 段文本）`)
}

// 图标节点检查：svg 树中应出现 path / circle / line
{
  const page = renderView('knowledge-home')
  const out = page.out
  assert.ok(out.types.includes('svg'), '应渲染 svg 图标')
  assert.ok(out.types.includes('path'), 'svg 内应有 path 节点')
  assert.ok(out.types.includes('circle') || out.types.includes('line'), 'svg 内应有 circle/line 节点')
  console.log('  ✓ 线性图标 svg/path/circle 节点正常')
}

// 跨视图焦点请求：viewRequest 落到目标子页并立即确认消费
{
  effectBudget = 1
  passState = [{ value: 'docs' }]
  cursor = 0
  let completed = 0
  const props = {
    viewRequest: { view: 'knowledge-docs', focus: 'add' },
    completeViewRequest: () => { completed++ },
  }
  renderTree(views['knowledge-docs'].render(props), { text: [], types: [], classes: [] })
  assert.equal(completed, 1, '焦点请求应被确认一次')
  effectBudget = 0
  cursor = 0
  const out = { text: [], types: [], classes: [] }
  renderTree(views['knowledge-docs'].render(props), out)
  assert.ok(out.text.includes('录入文本'), '焦点请求应把文档管理切到「添加文档」子页')
  console.log('  ✓ viewRequest 焦点请求消费正常（切子页 + 确认一次）')
}

// 提案编辑弹窗回归：编辑态从 null → 提案的重渲染不得崩溃（白屏回归）。
// editing 槽位动态定位：逐个把 null 槽位试设为提案，唯一让弹窗出现的就是它，
// 不依赖 hook 调用顺序（顺序变化不会让本测试静默失效）。
{
  const proposal = {
    proposal_id: 'dp-smoke', action: 'add_text', status: 'awaiting_approval',
    issue_type: 'missing_content', confidence: 0.5, risk: 'low',
    payload: {}, evidence: [{ query: '差旅报销流程' }], feedback_ids: [],
  }
  passState = [{ value: 'proposals' }]
  cursor = 0
  renderTree(views['knowledge-auto'].render({ onSubChange() {} }), { text: [], types: [], classes: [] })
  const base = passState
  let editingIdx = -1
  for (let i = 1; i < base.length; i++) {
    if (base[i].value !== null) continue
    passState = base.map((s, j) => ({ value: j === i ? proposal : s.value }))
    cursor = 0
    const out = { text: [], types: [], classes: [] }
    renderTree(views['knowledge-auto'].render({ onSubChange() {} }), out)
    if (out.text.includes('补充知识内容') && out.text.includes('保存并执行')) { editingIdx = i; break }
  }
  passState = base
  cursor = 0
  assert.ok(editingIdx > 0, '必须能定位 editing 槽位（弹窗应随编辑态出现且不崩溃）')

  const out1 = { text: [], types: [], classes: [] }
  renderTree(views['knowledge-auto'].render({ onSubChange() {} }), out1)
  assert.ok(!out1.text.includes('补充知识内容'), '未点编辑时不应渲染弹窗')

  passState = base.map((s, j) => ({ value: j === editingIdx ? proposal : s.value }))
  cursor = 0
  const out2 = { text: [], types: [], classes: [] }
  renderTree(views['knowledge-auto'].render({ onSubChange() {} }), out2)
  assert.ok(out2.text.includes('补充知识内容'), '编辑后应打开弹窗且不崩溃（form 需由提案初始化）')
  assert.ok(out2.text.includes('填写文本') && out2.text.includes('上传文档'), 'add_text 提案应提供填写文本 / 上传文档双模式')

  // 上传模式分支：弹窗挂载后的状态数组含 mode 槽位（初始值 text），切到 upload 后
  // 文件选择入口出现且不崩溃（条件挂载下弹窗槽位不在 base 里，需从挂载后快照取）
  const withModal = passState
  const modeIdx = withModal.findIndex((s) => s.value === 'text')
  assert.ok(modeIdx > 0, 'mode 槽位应存在于弹窗挂载后的状态快照（初始值 text）')
  passState = withModal.map((s, j) => ({ value: j === modeIdx ? 'upload' : s.value }))
  cursor = 0
  const out3 = { text: [], types: [], classes: [] }
  renderTree(views['knowledge-auto'].render({ onSubChange() {} }), out3)
  assert.ok(out3.text.includes('选择文件') && out3.text.includes('尚未选择文件'), '上传模式应渲染文件选择入口')
  console.log('  ✓ 提案编辑弹窗：null → 提案重渲染不崩溃（白屏回归）+ 上传模式渲染')
}

// 品牌槽与辅助槽注册检查
assert.ok(captured['conversation.chat.assistant-actions'], 'assistant-actions 槽应注册')
assert.ok(captured['conversation.session.header.utilities'], 'header.utilities 槽应注册')
assert.ok(captured['conversation.hero.brand.mark'], 'hero.brand.mark 槽应注册（知识标志替代默认鲸鱼）')
{
  const mark = (captured['conversation.hero.brand.mark'] || [])[0]
  const out = { text: [], types: [], classes: [] }
  passState = []; cursor = 0
  renderTree(mark.render({ size: 34 }), out)
  assert.ok(out.types.includes('svg') && out.types.includes('circle'), '知识标志应渲染 svg + 圆形节点')
}
console.log('  ✓ 会话反哺 / 健康徽章槽位注册正常')

// 会话反哺按钮：宿主传入 useChat 快照时渲染不崩溃，且反馈提交把
// 会话快照里的问题/回答/引用/查询 id 一并带给后端（readChatContext 契约）。
// 节点形状对齐宿主 legacy 投影：user/assistant/tool-result 均为顶层记录。
{
  const entry = (captured['conversation.chat.assistant-actions'] || [])[0]
  assert.ok(entry && entry.render, 'assistant-actions 条目应可渲染')
  const snap = {
    legacy: { nodes: [
      { kind: 'user', seq: 1, content: [{ type: 'text', text: '差旅报销流程是什么' }] },
      { kind: 'tool-result', seq: 2, call: { name: 'lightrag_query', argsRaw: '' }, content: [{ type: 'text', text: '报销需提供发票。\n\n引用：差旅管理办法.docx、财务报销细则.xlsx\n查询 id：q-abc123' }] },
      { kind: 'assistant', seq: 3, messageId: 'msg-1', turn: 3, blocks: [{ kind: 'text', text: '回答正文' }] },
    ] },
  }
  // 槽位：0 open / 1 feedbackOpen / 2 issueType / 3 feedbackNote —— 预置打开弹窗并填好备注
  passState = [
    { value: false }, { value: true }, { value: 'missing_content' }, { value: '缺少报销标准' },
  ]
  cursor = 0
  let posted = null
  const realFetch = globalThis.fetch
  globalThis.fetch = (path, opts) => {
    posted = { path, body: opts && opts.body ? JSON.parse(opts.body) : null }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
  }
  try {
    const out = { text: [], types: [], classes: [] }
    renderTree(entry.render({ useChat: (sel) => sel(snap), messageId: 'msg-1', sessionId: 's1' }), out)
    assert.ok(out.text.includes('反馈此回答') && out.text.includes('提交反馈'), '反馈弹窗应渲染')
    cursor = 0
    const root = entry.render({ useChat: (sel) => sel(snap), messageId: 'msg-1', sessionId: 's1' })
    const buttons = []
    const walk = (el) => {
      if (Array.isArray(el)) { el.forEach(walk); return }
      if (el === null || el === undefined || typeof el === 'string' || typeof el === 'number') return
      if (typeof el.type === 'function') { walk(el.type(el.props)); return }
      if (el.props && typeof el.props.onClick === 'function') {
        const kids = Array.isArray(el.props.children) ? el.props.children : [el.props.children]
        if (kids.includes('提交反馈')) buttons.push(el.props.onClick)
      }
      if (el.children) walk(el.children)
    }
    walk(root)
    assert.equal(buttons.length, 1, '提交反馈按钮唯一')
    buttons[0]()
    await Promise.resolve()
    assert.ok(posted && posted.path === '/kb/feedback', '应 POST /kb/feedback')
    assert.equal(posted.body.query, '差旅报销流程是什么', '提交体应携带会话中的用户问题')
    assert.equal(posted.body.answer, '回答正文', '提交体应携带回答正文')
    assert.deepEqual(posted.body.references, [{ file: '差旅管理办法.docx' }, { file: '财务报销细则.xlsx' }], '提交体应携带解析出的引用文件')
    assert.equal(posted.body.query_id, 'q-abc123', '提交体应携带工具卡的查询 id')
  } finally {
    globalThis.fetch = realFetch
    passState = []
  }
  console.log('  ✓ 会话反哺：提交反馈携带问题/回答/引用/查询 id')
}

console.log('\n全部渲染冒烟断言通过。')
