/**
 * dsh-knowledge · client v4（hand-written, no build step）。
 *
 * 设计方向：企业级知识运维控制台。数据前置、文案克制、渐进披露。
 * 一级视图（各自注册为 conversation.view 条目，与宿主「对话」「轨迹」同级）：
 *  - 总览       ：服务状态 + 待处理反馈 + 待审批提案 + 执行记录
 *  - 文档管理   ：文档列表 / 添加知识
 *  - 反馈诊断   ：反馈列表 / 修复提案 / 执行记录
 *
 * 文案规范：正文全中文；术语统一（反馈与诊断 / 修复提案 / 执行记录）；
 * 解释性内容收进 tooltip；ID 与原始 JSON 不直接可见。
 *
 * 落点：conversation.view×4（knowledge-home/-docs/-auto/-health，openView 跨视图跳转）、
 * assistant-actions『存入知识库』、session.header.utilities 健康徽章、sidebar.brand.*。
 * 数据全部来自 Host /kb/* 路由，主题跟随 --dsw-alias-* CSS 变量。
 */
window.__ModuleLoader__.load({
  id: "dsh-knowledge",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

    const React = require("react");
    const El = React.createElement;

    const TOPICS = ['未分类', '产品和营销', '创新和研发', '党建工作', '党组工作/公司章程/董事会运作', '风险与合规', '供应链管理', '公共关系与综合行政', '人力资源管理', '网络建设和维护', '业务支撑和IT', '战略与文化', '资产和财务']

    // ---------------------------------------------------------------- 术语与文案统一层

    const DOC_STATUS = {
      pending: { label: '排队中', cls: 'pending' },
      processing: { label: '处理中', cls: 'pending' },
      updating: { label: '更新中', cls: 'pending' },
      active: { label: '已生效', cls: 'ok' },
      failed: { label: '失败', cls: 'failed' },
      outdated: { label: '已过时', cls: 'muted' },
      retired: { label: '已删除', cls: 'muted' },
      missing: { label: '待修复', cls: 'warn' },
    }

    const INTENT_STATUS = {
      pending: { label: '排队中', cls: 'pending' },
      issuing: { label: '提交中', cls: 'pending' },
      issued: { label: '执行中', cls: 'pending' },
      verifying: { label: '核验中', cls: 'pending' },
      verified: { label: '已完成', cls: 'ok' },
      failed: { label: '失败', cls: 'failed' },
      stuck: { label: '已卡住', cls: 'failed' },
    }

    const INTENT_KIND = { ingest_file: '文件入库', ingest_text: '文本入库', delete_doc: '删除文档', replace: '替换文档' }

    // ---- 反馈诊断：内部枚举一律翻译后再露出 ----
    const ISSUE_TYPE_LABEL = {
      wrong_source: '引用文档不对', incomplete_citation: '引用内容不完整', wrong_entity: '实体不准确',
      wrong_relation: '关系不准确', missing_content: '内容缺失', outdated_content: '内容过期',
      answer_style: '回答方式', other: '其他',
    }
    const GAP_LABEL = { 'a-missing': '知识缺失', 'b-retrieval-jitter': '检索波动', 'b-missing-text': '内容不全', 'probe-error': '检测失败' }
    const DIAG_STATUS_LABEL = {
      candidate: '候选中', awaiting_approval: '待你确认', approved: '已批准', executing: '执行中',
      succeeded: '已完成', failed: '执行失败', rejected: '已拒绝', needs_manual_review: '需人工核对',
    }
    const DIAG_ACTION_LABEL = {
      add_text: '新增知识', edit_entity: '修改实体描述', edit_relation: '修改关系',
      replace_document: '替换文档', review_document: '需人工核对', review_required: '需人工核对',
      reindex_document: '重建文档索引', adjust_chunking: '调整内容切分', adjust_retrieval: '调整检索策略',
      prompt_fix: '调整回答策略', manual_review: '人工处理',
    }
    /** 问题层：决定修复方向（补知识 / 改图谱 / 调检索 / 调回答 / 对齐预期）。 */
    const CAUSE_LAYER_LABEL = {
      knowledge: '知识内容', graph: '图谱结构', retrieval: '检索过程',
      answer_generation: '回答生成', user_expectation: '用户预期',
    }
    /** 复核判定（用户确认修复效果）。 */
    const VERDICT_LABEL = { resolved: '已解决', partial: '部分解决', unresolved: '仍有问题', uncertain: '无法判断' }
    function causeLayerLabel(l) { return CAUSE_LAYER_LABEL[l] || '' }
    function verdictLabel(v) { return VERDICT_LABEL[v] || v || '' }
    const RISK_LABEL = { low: '低', medium: '中', high: '高' }
    function issueTypeLabel(t) { return ISSUE_TYPE_LABEL[t] || '其他' }
    function diagStatusTone(s) { return s === 'succeeded' ? 'ok' : (s === 'failed' || s === 'rejected') ? 'failed' : 'pending' }
    /** 置信度不露数字：映射为 高/中/低 三档判断把握。 */
    function confidenceLabel(c) { const n = Number(c); if (!isFinite(n)) return '中'; return n >= 0.7 ? '高' : n >= 0.5 ? '中' : '低' }

    const STATUS_LABEL = { proposed: '待评估', eval_passed: '评估通过', approved: '已批准', committed: '已生效', rejected: '已拒绝' }
    const OP_LABEL = {
      ingest: '入库', text_ingest: '文本入库', replace: '替换文档', replace_started: '替换开始', retry: '重试',
      delete: '删除文档', adopt: '收编文档',
      entity_create: '新建实体', entity_edit: '编辑实体', entity_merge: '合并实体', entity_delete: '删除实体',
      relation_create: '新建关系', relation_edit: '编辑关系', relation_delete: '删除关系',
      proposal_create: '提交建议', proposal_transition: '建议状态变更',
      proposal_stuck: '建议受阻', proposal_commit: '建议生效', proposal_commit_failed: '建议生效失败',
      registry_adopted: '收编引擎文档', source_conflict_repair: '源冲突修复',
    }
    const ACTOR_LABEL = {
      web: '工作台', agent: 'AI 助手', intent: '系统', system: '系统',
      gate: '自动评测', 'gate-revert': '自动回滚',
      flywheel: '自动评测', 'flywheel-revert': '自动回滚',
      engine: '引擎', reconciler: '系统对账',
    }
    /** 操作者 → 用户能懂的身份；技术原名只出现在展开的技术详情里。 */
    function actorLabel(actor) {
      if (!actor) return '系统'
      if (ACTOR_LABEL[actor]) return ACTOR_LABEL[actor]
      if (actor.indexOf('reconciler:') === 0) return '系统对账'
      if (actor === 'intent' || actor.indexOf('intent:') === 0) return '系统'
      return actor
    }
    /** 操作者 chip 配色：真人中性 / AI 品牌色 / 自动流程暖色 / 回滚与失败红色。 */
    function actorTone(actor) {
      if (actor === 'agent') return 'accent'
      if (actor === 'flywheel-revert' || actor === 'gate-revert') return 'failed'
      if (actor === 'flywheel' || actor === 'gate') return 'pending'
      return ''
    }

    // ---- 审计：分类归组（筛选器与图标用；技术 action 名不对用户露出） ----
    const AUDIT_GROUP_DOC = ['ingest', 'text_ingest', 'replace', 'replace_started', 'retry', 'delete', 'adopt']
    const AUDIT_GROUP_GRAPH = ['entity_create', 'entity_edit', 'entity_merge', 'entity_delete', 'relation_create', 'relation_edit', 'relation_delete']
    const AUDIT_GROUP_PROPOSAL = ['proposal_create', 'proposal_transition', 'proposal_stuck', 'proposal_commit', 'proposal_commit_failed']
    const AUDIT_GROUP_SYSTEM = ['registry_adopted', 'source_conflict_repair']
    const AUDIT_FILTERS = [
      { id: '', label: '全部记录', actions: null },
      { id: 'doc', label: '文档变动', actions: AUDIT_GROUP_DOC },
      { id: 'graph', label: '知识图谱', actions: AUDIT_GROUP_GRAPH },
      { id: 'proposal', label: 'AI 建议', actions: AUDIT_GROUP_PROPOSAL },
      { id: 'system', label: '系统维护', actions: AUDIT_GROUP_SYSTEM },
    ]
    const PROPOSAL_OP_VERB = {
      entity_create: '新建实体', entity_edit: '编辑实体', entity_delete: '删除实体', entity_merge: '合并实体',
      relation_create: '新建关系', relation_edit: '编辑关系', relation_delete: '删除关系',
      text_ingest: '文本入库', delete_doc: '删除文档', source_conflict_repair: '修复源冲突',
    }

    function proposalIdText(target) {
      const m = /^P-(\d+)$/.exec(String(target || ''))
      return m ? '建议 #' + parseInt(m[1], 10) : String(target || '')
    }
    /** 文档标题：后端 enrich 的 doc_title 优先，旧记录回退 detail.title。 */
    function auditDocTitle(a) {
      return a.doc_title || (a.detail && a.detail.title) || ''
    }
    function docObject(a) {
      const t = auditDocTitle(a)
      return t ? '《' + t + '》' : '一篇文档'
    }
    /** 提案流转理由中的机器话术 → 用户能据此行动的中文。 */
    function friendlyAuditReason(reason) {
      const r = String(reason || '')
      if (/golden 回归下降|golden 回归/.test(r)) return '自动评测发现可能影响现有问答效果，改动已回滚'
      if (/自证题在应用后未通过/.test(r)) return '验证题未通过，改动已回滚'
      if (/提案冗余|自证题在现网已能答上/.test(r)) return '现有知识已能回答验证题，无需修改'
      if (/golden 基线评测失败/.test(r)) return '自动评测运行失败，提案未执行'
      if (/回滚失败/.test(r)) return '回滚失败，改动可能仍留在引擎中，需人工核查'
      if (/引擎处理未完成/.test(r)) return '引擎处理未完成'
      return r.replace(/it-[0-9a-f]+/g, '系统').replace(/\s+/g, ' ').trim().slice(0, 100)
    }

    /**
     * 把一条审计流水翻译成一句话视图。
     * @returns {{group:string,icon:string,actor:string,tone:string,line:string,note:string,noteTone:string}}
     * line 为谓词+对象（操作者身份由 actor chip 单独承担）；note 是第二行补充。
     */
    function describeAudit(a) {
      const d = a.detail || {}
      const actor = actorLabel(a.actor)
      const tone = actorTone(a.actor)
      const act = a.action
      const target = String(a.target || '')
      const isFly = a.actor === 'flywheel' || a.actor === 'gate'
      const isRevert = a.actor === 'flywheel-revert' || a.actor === 'gate-revert'

      // ---- 文档变动 ----
      if (act === 'ingest' || act === 'text_ingest') {
        // target 为引擎内容 id（doc-…）的是处理完成后的登记行；it-/pending: 为提交行
        const completed = /^doc-/.test(target)
        return {
          group: 'doc', icon: 'file', actor, tone,
          line: (completed ? '完成了文档入库 ' : '提交了文档入库 ') + docObject(a),
          note: d.topic && d.topic !== '未分类' ? '主题：' + d.topic : '', noteTone: '',
        }
      }
      if (act === 'delete') {
        return { group: 'doc', icon: 'trash', actor, tone, line: '删除了文档 ' + docObject(a), note: d.reason || '', noteTone: '' }
      }
      if (act === 'retry') {
        return { group: 'doc', icon: 'refresh', actor, tone, line: '重新提交处理文档 ' + docObject(a), note: '', noteTone: '' }
      }
      if (act === 'replace_started') {
        return { group: 'doc', icon: 'swap', actor, tone, line: '开始替换文档 ' + docObject(a), note: d.reason || '', noteTone: '' }
      }
      if (act === 'replace') {
        const ver = d.from_version ? ('v' + d.from_version + ' → v' + d.to_version) : ''
        return { group: 'doc', icon: 'swap', actor, tone, line: '完成了文档版本替换 ' + docObject(a), note: ver || d.reason || '', noteTone: '' }
      }
      if (act === 'adopt') {
        return { group: 'doc', icon: 'file', actor, tone, line: '收编文档 ' + (d.title || target), note: '', noteTone: '' }
      }

      // ---- 知识图谱 ----
      if (act === 'entity_create') {
        return {
          group: 'graph', icon: 'graph', actor, tone,
          line: (isFly ? '评测中临时新建实体 ' : '新建了实体 ') + '「' + target + '」',
          note: isFly ? '用于验证改进建议' : (d.type ? '类型：' + d.type : ''), noteTone: '',
        }
      }
      if (act === 'entity_edit') {
        return { group: 'graph', icon: 'graph', actor, tone, line: '编辑了实体「' + target + '」', note: isFly ? '自动评测应用中' : '', noteTone: '' }
      }
      if (act === 'entity_merge') {
        const srcs = Array.isArray(d.sources) ? d.sources.map((s) => '「' + s + '」').join('、') : ''
        return { group: 'graph', icon: 'graph', actor, tone, line: '合并实体 ' + srcs + ' → 「' + target + '」', note: '', noteTone: '' }
      }
      if (act === 'entity_delete') {
        return {
          group: 'graph', icon: 'graph', actor, tone,
          line: isRevert ? '回滚了评测时临时新建的实体「' + target + '」' : '删除了实体「' + target + '」',
          note: isRevert ? '自动评测未通过' : '', noteTone: isRevert ? 'warn' : '',
        }
      }
      if (act === 'relation_create') {
        return {
          group: 'graph', icon: 'graph', actor, tone,
          line: (isFly ? '评测中临时新建关系 ' : '新建了关系 ') + target,
          note: isFly ? '用于验证改进建议' : (d.description ? String(d.description).slice(0, 60) : ''), noteTone: '',
        }
      }
      if (act === 'relation_edit') {
        return { group: 'graph', icon: 'graph', actor, tone, line: '编辑了关系 ' + target, note: '', noteTone: '' }
      }
      if (act === 'relation_delete') {
        return {
          group: 'graph', icon: 'graph', actor, tone,
          line: isRevert ? '回滚了评测时临时新建的关系 ' + target : '删除了关系 ' + target,
          note: isRevert ? '自动评测未通过' : '', noteTone: isRevert ? 'warn' : '',
        }
      }

      // ---- AI 建议 ----
      const pid = proposalIdText(target)
      if (act === 'proposal_create') {
        const rationale = d.rationale ? String(d.rationale) : ''
        return {
          group: 'proposal', icon: 'bulb', actor, tone,
          line: '提交了' + pid + '（' + (PROPOSAL_OP_VERB[d.op] || d.op || '改进') + '）',
          note: rationale.length > 70 ? rationale.slice(0, 70) + '…' : rationale, noteTone: '',
        }
      }
      if (act === 'proposal_transition') {
        let line, note = '', noteTone = ''
        if (d.to === 'eval_passed') { line = pid + ' 通过自动评测'; note = '等待提交生效' }
        else if (d.to === 'approved') { line = pid + ' 已批准'; note = friendlyAuditReason(d.reason) || '等待执行' }
        else if (d.to === 'committed') { line = pid + ' 已生效' }
        else if (d.to === 'rejected') { line = pid + ' 未被采纳'; note = friendlyAuditReason(d.reason); noteTone = 'err' }
        else { line = pid + ' 状态变更：' + (STATUS_LABEL[d.from] || d.from) + ' → ' + (STATUS_LABEL[d.to] || d.to) }
        return { group: 'proposal', icon: 'bulb', actor, tone, line, note, noteTone }
      }
      if (act === 'proposal_commit') {
        return { group: 'proposal', icon: 'bulb', actor, tone, line: pid + ' 已提交生效', note: d.op ? (PROPOSAL_OP_VERB[d.op] || d.op) : '', noteTone: '' }
      }
      if (act === 'proposal_commit_failed') {
        return { group: 'proposal', icon: 'bulb', actor, tone: 'failed', line: pid + ' 提交失败', note: friendlyAuditReason(d.reason), noteTone: 'err' }
      }
      if (act === 'proposal_stuck') {
        return { group: 'proposal', icon: 'bulb', actor, tone: 'failed', line: pid + ' 执行受阻，需人工处理', note: friendlyAuditReason(d.error || d.stage), noteTone: 'err' }
      }

      // ---- 系统维护 ----
      if (act === 'registry_adopted') {
        return {
          group: 'system', icon: 'refresh', actor, tone: '',
          line: '登记引擎中已有文档 ' + (d.count || 0) + ' 篇',
          note: actor === '系统对账' ? '对账时发现注册表缺失记录' : '启动扫描发现', noteTone: '',
        }
      }
      if (act === 'source_conflict_repair') {
        return { group: 'system', icon: 'refresh', actor, tone: '', line: '修复源冲突 ' + target, note: d.reason || '', noteTone: '' }
      }

      // 未知 action 的兜底：不裸显技术名以外的内容，也不崩
      return { group: 'system', icon: 'clock', actor, tone, line: (OP_LABEL[act] || act || '操作') + (target ? ' ' + target : ''), note: '', noteTone: '' }
    }

    /**
     * 列表展示折叠：一次启动/对账扫描会按批写出多条 registry_adopted，
     * 相邻且操作者相同的同批记录合并为一组（落盘流水不变，仅展示折叠）。
     * @returns {Array<{kind:'one',item:object}|{kind:'group',actor:string,items:object[]}>}
     */
    function foldAuditRows(rows) {
      const out = []
      for (const a of rows) {
        const prev = out.length ? out[out.length - 1] : null
        if (a.action === 'registry_adopted' && prev && prev.kind === 'group' && prev.actor === (a.actor || '')) {
          prev.items.push(a)
        } else if (a.action === 'registry_adopted') {
          out.push({ kind: 'group', actor: a.actor || '', items: [a] })
        } else {
          out.push({ kind: 'one', item: a })
        }
      }
      return out
    }

    // 时间统一按浏览器本地时区显示（后端时间戳为 UTC ISO 字符串）
    function pad2(n) { return String(n).padStart(2, '0') }
    function localParts(ts) {
      if (!ts) return null
      const d = new Date(ts)
      if (isNaN(d.getTime())) return null
      return {
        y: d.getFullYear(), M: pad2(d.getMonth() + 1), D: pad2(d.getDate()),
        h: pad2(d.getHours()), m: pad2(d.getMinutes()), s: pad2(d.getSeconds()),
      }
    }
    /** 完整本地时间：YYYY-MM-DD HH:mm:ss */
    const fmtTs = (ts) => {
      const p = localParts(ts)
      return p ? (p.y + '-' + p.M + '-' + p.D + ' ' + p.h + ':' + p.m + ':' + p.s) : (ts || '').slice(0, 19).replace('T', ' ')
    }
    /** 审计列表紧凑时间：今年 MM-DD HH:mm，跨年带年份。 */
    function fmtAuditTime(ts) {
      const p = localParts(ts)
      if (!p) return (ts || '').slice(0, 16).replace('T', ' ')
      const date = p.y === new Date().getFullYear() ? (p.M + '-' + p.D) : (p.y + '-' + p.M + '-' + p.D)
      return date + ' ' + p.h + ':' + p.m
    }
    /** 报错翻译：引擎报错转成可执行的提示。 */
    function friendlyError(e) {
      const msg = String(e && e.message ? e.message : e)
      if (/pipeline_busy|管道忙碌/.test(msg)) return '引擎正在处理其他任务，请稍后重试'
      if (/超出工作区边界/.test(msg)) return '路径超出工作区范围，无法访问'
      if (/fetch|network|ECONN/i.test(msg)) return '无法连接知识库服务，请确认服务已启动'
      return msg
    }
    // ---------------------------------------------------------------- 图标（线性 SVG）

    const P = (d) => El('path', { d })
    const C = (cx, cy, r) => El('circle', { cx, cy, r })
    const L = (x1, y1, x2, y2) => El('line', { x1, y1, x2, y2 })
    const R = (x, y, w, h, rx) => El('rect', { x, y, width: w, height: h, rx })
    const ICONS = {
      overview: [R(2, 2, 4.75, 4.75, 1), R(9.25, 2, 4.75, 4.75, 1), R(2, 9.25, 4.75, 4.75, 1), R(9.25, 9.25, 4.75, 4.75, 1)],
      knowledge: [P('M3.5 2h8A1.5 1.5 0 0 1 13 3.5V14H5a1.5 1.5 0 0 1-1.5-1.5V2z'), P('M3.5 12.5A1.5 1.5 0 0 1 5 11h8')],
      automation: [P('M2 8h3l2-4.5 3 9L12 8h2')],
      shield: [P('M8 1.5l5.5 2v4.2c0 3.3-2.3 5.6-5.5 6.8-3.2-1.2-5.5-3.5-5.5-6.8V3.5l5.5-2z')],
      bulb: [P('M8 2a4 4 0 0 1 4 4c0 1.6-.9 2.6-1.6 3.4-.4.5-.4.9-.4 1.1H6c0-.2 0-.6-.4-1.1C4.9 8.6 4 7.6 4 6a4 4 0 0 1 4-4z'), L(6.5, 12.5, 9.5, 12.5), L(7, 14.5, 9, 14.5)],
      chart: [P('M4 13.5V11 M8 13.5V6 M12 13.5V8.5 M2.5 13.5h11')],
      list: [L(5.5, 3.5, 13.5, 3.5), L(5.5, 8, 13.5, 8), L(5.5, 12.5, 13.5, 12.5), C(3, 3.5, 0.5), C(3, 8, 0.5), C(3, 12.5, 0.5)],
      search: [C(7, 7, 4.2), L(10.2, 10.2, 13.8, 13.8)],
      plus: [L(8, 3, 8, 13), L(3, 8, 13, 8)],
      refresh: [P('M13.2 8a5.2 5.2 0 1 1-1.6-3.8'), P('M13.4 2.9v2.8h-2.8')],
      file: [P('M4 1.5h5.5L12 4v10.5H4z'), P('M9.5 1.5V4H12')],
      graph: [C(8, 3, 1.8), C(3.5, 11, 1.8), C(12.5, 11, 1.8), L(7, 4.2, 4.3, 9.6), L(9, 4.2, 11.7, 9.6), L(5.3, 11, 10.7, 11)],
      help: [C(8, 8, 5.8), P('M6.6 6.2c.2-.9 1-1.5 1.9-1.4 1 .1 1.6.8 1.6 1.6 0 1.4-2 1.4-2 2.8'), C(8, 11.6, 0.5)],
      check: [P('M3 8.5l3.2 3.2L13 5')],
      trash: [P('M3 4.5h10'), P('M6.5 4.5V3h3v1.5'), P('M4.5 4.5l.7 9h5.6l.7-9')],
      swap: [P('M4 5.5h8L9.5 3'), P('M12 10.5H4l2.5 2.5')],
      clock: [C(8, 8, 5.5), P('M8 4.8V8l2.4 1.6')],
      eye: [P('M1.8 8s2.2-4 6.2-4 6.2 4 6.2 4-2.2 4-6.2 4S1.8 8 1.8 8z'), C(8, 8, 1.8)],
      message: [P('M3 3.5h10A1.5 1.5 0 0 1 14.5 5v5A1.5 1.5 0 0 1 13 11.5H8l-3.5 2v-2H3A1.5 1.5 0 0 1 1.5 10V5A1.5 1.5 0 0 1 3 3.5z')],
      sparkle: [P('M8 1.5l.9 4.6L13.5 7l-4.6.9L8 12.5l-.9-4.6L2.5 7l4.6-.9L8 1.5z'), P('M13 11l.4 1.6L15 13l-1.6.4L13 15l-.4-1.6L11 13l1.6-.4L13 11z')],
      edit: [P('M11.7 2.3l2 2a1 1 0 0 1 0 1.4L6.5 13 3 14l1-3.5 7.3-7.7a1 1 0 0 1 1.4 0z'), L(10.5, 3.5, 12.5, 5.5)],
    }
    /** 线性图标：按 props 特征还原节点类型（P→path / C→circle / L→line / R→rect）。 */
    function icon(name, size, style) {
      const paths = ICONS[name] || []
      const kids = paths.map((p, i) => {
        const tag = p.props && p.props.d !== undefined && p.props.cx === undefined && p.props.x1 === undefined && p.props.width === undefined ? 'path'
          : p.props && p.props.r !== undefined ? 'circle'
            : p.props && p.props.x1 !== undefined ? 'line'
              : 'rect'
        return El(tag, Object.assign({ key: 'i' + i }, p.props))
      })
      return El('svg', {
        width: size || 16, height: size || 16, viewBox: '0 0 16 16',
        fill: 'none', stroke: 'currentColor', strokeWidth: 1.5,
        strokeLinecap: 'round', strokeLinejoin: 'round',
        className: 'kb-ic', style: style, 'aria-hidden': true,
      }, kids)
    }

    // ---------------------------------------------------------------- CSS（设计系统）

    const CSS = [
      // 基础与设计令牌
      '.kb-root{height:100%;display:flex;flex-direction:column;overflow:hidden;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);font-family:system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:13.5px;-webkit-font-smoothing:antialiased;}',
      '.kb-root{--kb-ok:var(--dsw-alias-state-success-primary);--kb-err:var(--dsw-alias-state-error-primary);--kb-warn:#d97706;--kb-accent:var(--dsw-alias-brand-primary);}',
      '.kb-ic{flex:none;vertical-align:-2px;}',
      // 顶栏
      '.kb-topbar{display:flex;align-items:center;gap:10px;padding:12px 20px;border-bottom:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-1);}',
      '.kb-title{font-weight:700;font-size:15px;letter-spacing:.01em;}',
      '.kb-spacer{flex:1;}',
      '.kb-dot{width:8px;height:8px;border-radius:50%;background:var(--dsw-alias-label-secondary);flex:none;display:inline-block;}',
      '.kb-dot.ok{background:var(--kb-ok);}.kb-dot.bad{background:var(--kb-err);}.kb-dot.warn{background:var(--kb-warn);}',
      '.kb-hint{color:var(--dsw-alias-label-secondary);font-size:12px;}',
      '.kb-err{color:var(--dsw-alias-state-error-primary);font-size:12.5px;}',
      // 主导航（顶栏内的 kb-seg kb-topnav 分段控件，样式见 kb-seg）
      // 内容区与卡片
      '.kb-content{flex:1;overflow-y:auto;padding:18px 20px;}',
      '.kb-stack{display:flex;flex-direction:column;}',
      '@keyframes kb-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}',
      '.kb-stack>*{animation:kb-in .3s ease both;}',
      '.kb-stack>*:nth-child(2){animation-delay:.04s}.kb-stack>*:nth-child(3){animation-delay:.08s}.kb-stack>*:nth-child(4){animation-delay:.12s}',
      '.kb-2col{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px;}',
      '@media (max-width:1100px){.kb-2col{grid-template-columns:1fr;}}',
      '.kb-card{background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);border-radius:10px;padding:16px;margin-bottom:14px;}',
      '.kb-2col .kb-card{margin-bottom:0;height:fit-content;}',
      '.kb-cardhead{display:flex;align-items:center;gap:8px;margin-bottom:12px;}',
      '.kb-cardhead h4{margin:0;font-size:14px;font-weight:600;}',
      '.kb-cardhead .kb-spacer{flex:1;}',
      '.kb-eyebrow{font-size:11.5px;letter-spacing:.06em;color:var(--dsw-alias-label-secondary);font-weight:600;margin:12px 0 6px;}',
      // 状态条
      '.kb-strip{display:flex;align-items:center;gap:14px;padding:12px 16px;border:1px solid var(--dsw-alias-border-l1);border-left:3px solid var(--kb-ok);border-radius:10px;background:var(--dsw-alias-bg-layer-1);margin-bottom:14px;}',
      '.kb-strip.warn{border-left-color:var(--kb-warn);}',
      '.kb-strip.bad{border-left-color:var(--kb-err);}',
      '.kb-strip .kb-strip-main{font-weight:600;font-size:14px;}',
      '.kb-strip .kb-strip-sub{font-size:12px;color:var(--dsw-alias-label-secondary);margin-top:2px;}',
      '.kb-strip-metrics{display:flex;gap:14px;flex-wrap:wrap;}',
      '.kb-strip-metrics .m{display:flex;align-items:baseline;gap:5px;font-size:12.5px;color:var(--dsw-alias-label-secondary);cursor:default;}',
      '.kb-strip-metrics .m b{font-size:15px;font-weight:700;color:var(--dsw-alias-label-primary);font-variant-numeric:tabular-nums;}',
      // 统计块
      '.kb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;}',
      '.kb-stat{background:var(--dsw-alias-bg-layer-2);border:1px solid var(--dsw-alias-border-l1);border-radius:8px;padding:12px 14px;}',
      '.kb-stat .num{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.15;}',
      '.kb-stat .lab{font-size:12px;color:var(--dsw-alias-label-secondary);margin-top:3px;display:flex;align-items:center;gap:4px;}',
      '.kb-trend{font-size:11px;font-weight:700;}.kb-trend.up{color:var(--kb-ok);}.kb-trend.down{color:var(--kb-err);}.kb-trend.flat{color:var(--dsw-alias-label-secondary);}',
      // 按钮
      '.kb-btn{display:inline-flex;align-items:center;gap:6px;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-primary);border:1px solid var(--dsw-alias-border-l1);border-radius:7px;padding:7px 14px;cursor:pointer;font-size:13px;font-family:inherit;transition:background .15s,border-color .15s;}',
      '.kb-btn:hover{border-color:var(--dsw-alias-label-secondary);}',
      '.kb-btn.primary{background:var(--kb-accent);color:#fff;border-color:transparent;}',
      '.kb-btn.primary:hover{filter:brightness(1.08);border-color:transparent;}',
      '.kb-btn.danger{color:var(--kb-err);}.kb-btn.danger:hover{border-color:var(--kb-err);}',
      '.kb-btn.big{font-size:13.5px;padding:9px 20px;}',
      '.kb-btn:disabled{opacity:.45;cursor:default;}',
      '.kb-btn.linky{background:transparent;border:none;color:var(--kb-accent);padding:4px 6px;font-size:12.5px;}',
      '.kb-btn.linky:hover{filter:brightness(1.1);}',
      '.kb-btn:focus-visible,.kb-input:focus-visible,.kb-select:focus-visible,.kb-textarea:focus-visible,.kb-seg button:focus-visible{outline:2px solid var(--kb-accent);outline-offset:1px;}',
      // 表单
      '.kb-input,.kb-select,.kb-textarea{background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);border:1px solid var(--dsw-alias-border-l1);border-radius:7px;padding:7px 11px;font-size:13px;font-family:inherit;}',
      '.kb-input:focus,.kb-textarea:focus,.kb-select:focus{outline:none;border-color:var(--kb-accent);}',
      '.kb-textarea{width:100%;resize:vertical;min-height:110px;box-sizing:border-box;}',
      '.kb-form-row{display:flex;gap:8px;margin-bottom:10px;align-items:center;flex-wrap:wrap;}',
      '.kb-form-row label{font-size:12px;color:var(--dsw-alias-label-secondary);}',
      // 表格
      '.kb-table{width:100%;border-collapse:collapse;font-size:12.5px;}',
      '.kb-table th,.kb-table td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--dsw-alias-border-l1);vertical-align:top;}',
      '.kb-table th{color:var(--dsw-alias-label-secondary);font-weight:600;font-size:11.5px;letter-spacing:.03em;background:var(--dsw-alias-bg-layer-1);position:sticky;top:0;}',
      '.kb-table tr:hover td{background:var(--dsw-alias-bg-layer-2);}',
      // 状态标签
      '.kb-chip{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;padding:2px 8px;border-radius:5px;background:var(--dsw-alias-bg-layer-2);border:1px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-label-secondary);white-space:nowrap;}',
      '.kb-chip.ok{color:var(--kb-ok);border-color:color-mix(in srgb,var(--kb-ok) 40%,transparent);}',
      '.kb-chip.failed{color:var(--kb-err);border-color:color-mix(in srgb,var(--kb-err) 40%,transparent);}',
      '.kb-chip.pending{color:var(--kb-warn);border-color:color-mix(in srgb,var(--kb-warn) 40%,transparent);}',
      '.kb-chip.accent{color:var(--kb-accent);border-color:color-mix(in srgb,var(--kb-accent) 40%,transparent);}',
      '.kb-chip b{font-weight:700;color:var(--dsw-alias-label-primary);}',
      // 分段控件（子导航）
      '.kb-seg{display:inline-flex;background:var(--dsw-alias-bg-layer-2);border:1px solid var(--dsw-alias-border-l1);border-radius:8px;padding:3px;gap:2px;margin-bottom:14px;}',
      '.kb-seg button{border:none;background:transparent;padding:6px 14px;border-radius:6px;color:var(--dsw-alias-label-secondary);cursor:pointer;font-size:12.5px;font-family:inherit;transition:background .15s,color .15s;}',
      '.kb-seg button:hover{color:var(--dsw-alias-label-primary);}',
      '.kb-seg button.active{background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);font-weight:600;box-shadow:0 1px 3px rgba(0,0,0,.1);}',
      // 待办列表
      '.kb-todo{display:flex;align-items:center;gap:10px;width:100%;text-align:left;background:transparent;border:none;border-left:2px solid var(--kb-err);border-radius:0 8px 8px 0;padding:9px 12px;cursor:pointer;margin-bottom:6px;font-size:13px;color:var(--dsw-alias-label-primary);font-family:inherit;transition:background .15s;}',
      '.kb-todo:hover{background:var(--dsw-alias-bg-layer-2);}',
      '.kb-todo.info{border-left-color:var(--kb-accent);}',
      '.kb-todo.warn{border-left-color:var(--kb-warn);}',
      '.kb-todo .kb-todo-n{font-weight:700;font-size:16px;font-variant-numeric:tabular-nums;min-width:26px;text-align:center;}',
      '.kb-todo.info .kb-todo-n,.kb-todo.warn .kb-todo-n{color:var(--dsw-alias-label-secondary);font-size:13px;}',
      // 上传区
      '.kb-drop{border:1.5px dashed var(--dsw-alias-border-l2);border-radius:10px;padding:36px 20px;text-align:center;color:var(--dsw-alias-label-secondary);cursor:pointer;transition:border-color .15s,background .15s;}',
      '.kb-drop b{font-size:14px;color:var(--dsw-alias-label-primary);display:block;margin-bottom:4px;}',
      '.kb-drop.over{border-color:var(--kb-accent);background:color-mix(in srgb,var(--kb-accent) 6%,transparent);}',
      '.kb-upload-row{display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid var(--dsw-alias-border-l1);border-radius:8px;margin-top:8px;font-size:12.5px;}',
      // 进度条
      '.kb-progress{height:6px;border-radius:3px;background:var(--dsw-alias-bg-layer-2);overflow:hidden;margin-top:12px;}',
      '.kb-progress > div{height:100%;background:var(--kb-accent);transition:width .3s;border-radius:3px;}',
      // 图谱
      '.kb-graph-wrap{position:relative;border:1px solid var(--dsw-alias-border-l1);border-radius:10px;overflow:hidden;background:var(--dsw-alias-bg-layer-1);}',
      '.kb-graph-svg{display:block;width:100%;height:500px;}',
      '.kb-node circle{fill:var(--kb-accent);opacity:.85;cursor:pointer;}',
      '.kb-node circle:hover{opacity:1;}',
      '.kb-node text{fill:var(--dsw-alias-label-primary);font-size:10px;}',
      '.kb-node.sel circle{fill:var(--kb-warn);stroke:var(--dsw-alias-bg-layer-1);stroke-width:2px;}',
      '.kb-edge{stroke:var(--dsw-alias-border-l2);stroke-width:1;opacity:.7;cursor:pointer;}',
      '.kb-edge:hover{stroke-width:2;opacity:1;}',
      '.kb-edge.sel{stroke:var(--kb-accent);stroke-width:2.5;opacity:1;}',
      '.kb-edge-label{font-size:9px;fill:var(--dsw-alias-label-secondary);pointer-events:none;}',
      '.kb-side{display:grid;grid-template-columns:280px 1fr;gap:14px;}',
      '@media (max-width:1100px){.kb-side{grid-template-columns:1fr;}}',
      '.kb-list{max-height:300px;overflow-y:auto;border:1px solid var(--dsw-alias-border-l1);border-radius:8px;}',
      '.kb-list-item{padding:8px 11px;border-bottom:1px solid var(--dsw-alias-border-l1);cursor:pointer;font-size:12.5px;}',
      '.kb-list-item:last-child{border-bottom:none;}',
      '.kb-list-item:hover{background:var(--dsw-alias-bg-layer-2);}',
      '.kb-list-item.sel{background:var(--dsw-alias-bg-layer-2);color:var(--kb-accent);font-weight:600;}',
      // 面板（选中详情）与折叠
      '.kb-panel{border:1px solid var(--dsw-alias-border-l2);border-radius:8px;padding:12px;margin-top:10px;background:var(--dsw-alias-bg-layer-2);}',
      '.kb-panel h5{margin:0 0 8px;font-size:13px;font-weight:600;}',
      'details.kb-details{border:1px solid var(--dsw-alias-border-l1);border-radius:8px;padding:0;margin-top:12px;}',
      'details.kb-details summary{cursor:pointer;padding:9px 12px;font-size:12.5px;color:var(--dsw-alias-label-secondary);font-weight:600;list-style:none;display:flex;align-items:center;gap:6px;}',
      'details.kb-details summary::before{content:"+";font-family:monospace;font-weight:700;}',
      'details.kb-details[open] summary::before{content:"−";}',
      'details.kb-details summary:hover{color:var(--dsw-alias-label-primary);}',
      'details.kb-details > .kb-details-body{padding:2px 12px 12px;}',
      // 弹窗
      '.kb-modal-backdrop{position:fixed;inset:0;z-index:2147483000;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;padding:24px;animation:kb-in .2s ease;}',
      '.kb-modal{width:620px;max-width:94vw;max-height:84vh;overflow-y:auto;background:var(--dsw-alias-bg-overlay);border:1px solid var(--dsw-alias-border-l2);border-radius:14px;padding:20px;box-shadow:0 18px 56px rgba(0,0,0,.35);}',
      '.kb-modal h4{margin:0 0 12px;font-size:15px;font-weight:700;display:flex;align-items:center;justify-content:space-between;}',
      // 通用
      '.kb-save-wrap{margin-top:6px;}',
      '.kb-save-done{background:transparent;border:none;color:var(--kb-ok);font-size:12.5px;cursor:default;display:inline-flex;align-items:center;gap:4px;}',
      '.kb-hl{display:inline-flex;align-items:center;gap:6px;cursor:default;}',
      '.kb-empty{padding:26px 14px;text-align:center;color:var(--dsw-alias-label-secondary);font-size:12.5px;}',
      '.kb-empty svg{opacity:.45;margin-bottom:6px;}',
      '.kb-rows{display:flex;flex-direction:column;gap:8px;}',
      '.kb-row{display:flex;flex-direction:column;gap:6px;font-size:12.5px;min-width:0;padding:10px 12px;border-radius:8px;background:var(--dsw-alias-bg-layer-2);border:1px solid var(--dsw-alias-border-l1);transition:border-color .15s,background .15s;}',
      '.kb-row:hover{border-color:color-mix(in srgb,var(--kb-accent) 30%,transparent);}',
      '.kb-row .fb-head{display:flex;align-items:center;gap:10px;min-width:0;width:100%;}',
      '.kb-row .fb-head .t{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--dsw-alias-label-primary);font-weight:600;}',
      '.kb-row .fb-note{color:var(--dsw-alias-label-primary);font-size:12px;line-height:1.55;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.kb-row .fb-answer{color:var(--dsw-alias-label-secondary);font-size:12px;line-height:1.55;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}',
      '.kb-row .fb-refs{display:flex;flex-wrap:wrap;gap:4px;}',
      '.kb-row .ts{color:var(--dsw-alias-label-secondary);font-size:11.5px;font-variant-numeric:tabular-nums;flex:none;}',
      '.kb-row-actions{display:inline-flex;gap:2px;flex:none;opacity:0;transition:opacity .12s;}',
      '.kb-row:hover .kb-row-actions{opacity:1;}',
      '.kb-btn.linky.danger-text{color:var(--kb-err);}',
      // 操作审计（一句话时间线 + 折叠的技术详情）
      '.kb-audit-time{color:var(--dsw-alias-label-secondary);font-size:11.5px;font-variant-numeric:tabular-nums;white-space:nowrap;}',
      'tr.kb-audit-row{cursor:pointer;}',
      '.kb-audit-main{display:flex;align-items:flex-start;gap:9px;min-width:0;}',
      '.kb-audit-main .kb-ic{margin-top:2px;color:var(--dsw-alias-label-secondary);flex:none;}',
      '.kb-audit-body{min-width:0;flex:1;}',
      '.kb-audit-line{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12.5px;}',
      '.kb-audit-line .kb-audit-text{min-width:0;}',
      '.kb-audit-note{font-size:11.5px;color:var(--dsw-alias-label-secondary);margin-top:3px;}',
      '.kb-audit-note.err{color:var(--kb-err);}.kb-audit-note.warn{color:var(--kb-warn);}',
      '.kb-audit-more{color:var(--dsw-alias-label-secondary);font-size:11px;flex:none;margin-left:auto;}',
      '.kb-audit-tech{font-size:11.5px;color:var(--dsw-alias-label-secondary);display:flex;flex-direction:column;gap:5px;padding:4px 0 10px;}',
      '.kb-audit-tech .kb-tech-row{display:flex;gap:6px;align-items:baseline;}',
      '.kb-audit-tech b{color:var(--dsw-alias-label-secondary);font-weight:600;flex:none;}',
      '.kb-audit-tech code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px;word-break:break-all;}',
      '.kb-audit-json{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px;background:var(--dsw-alias-bg-base);border:1px solid var(--dsw-alias-border-l1);border-radius:6px;padding:8px;max-height:180px;overflow:auto;white-space:pre-wrap;word-break:break-all;}',
      // markdown 渲染
      '.kb-md{line-height:1.65;font-size:13px;}',
      '.kb-md p{margin:0 0 8px;}.kb-md p:last-child{margin-bottom:0;}',
      '.kb-md h1,.kb-md h2,.kb-md h3{margin:10px 0 6px;font-weight:600;line-height:1.3;}',
      '.kb-md h1{font-size:17px;}.kb-md h2{font-size:15.5px;}.kb-md h3{font-size:14.5px;}',
      '.kb-md ul,.kb-md ol{margin:0 0 8px;padding-left:20px;}.kb-md li{margin:2px 0;}',
      '.kb-md strong{font-weight:600;}',
      '.kb-md code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;background:var(--dsw-alias-bg-layer-2);border-radius:4px;padding:0 4px;}',
      '.kb-md pre{margin:0 0 8px;background:var(--dsw-alias-bg-base);border:1px solid var(--dsw-alias-border-l1);border-radius:8px;padding:10px;overflow-x:auto;}',
      '.kb-md pre code{background:transparent;border:none;padding:0;}',
      '.kb-md blockquote{margin:0 0 8px;padding:4px 12px;border-left:3px solid var(--dsw-alias-border-l2);color:var(--dsw-alias-label-secondary);}',
      // 关闭平台对话区的左右宽度拖拽把手（用户反馈：竖条难看且影响功能）
      '[data-width-handle]{display:none!important;}',
      // v5 workspace visual system: calm canvas, clear hierarchy, compact navigation.
      '.kb-root{--kb-accent:#315efb;--kb-violet:#7257d8;--kb-teal:#159a88;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);} .kb-topbar{min-height:64px;padding:0 28px;border-bottom:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-1);backdrop-filter:blur(14px);} .kb-title{font-size:16px;font-weight:600;color:var(--dsw-alias-label-primary);} .kb-content{padding:28px;max-width:1320px;width:100%;box-sizing:border-box;margin:0 auto;} .kb-card,.kb-panel{border:1px solid var(--dsw-alias-border-l1);border-radius:16px;background:var(--dsw-alias-bg-layer-1);box-shadow:0 8px 28px rgba(27,39,66,.045);} .kb-card{padding:20px;margin-bottom:16px;} .kb-btn{border-color:#e1e6ef;border-radius:9px;background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-secondary);padding:8px 14px;transition:all .16s ease;} .kb-btn:hover{border-color:#b8c5da;background:#f8faff;transform:translateY(-1px);} .kb-btn.primary{background:#315efb;box-shadow:0 5px 14px rgba(49,94,251,.22);} .kb-btn.ghost{background:rgba(255,255,255,.72);color:#315efb;border-color:rgba(49,94,251,.25);} .kb-home{display:flex;flex-direction:column;gap:18px;} .kb-hero{display:flex;justify-content:space-between;gap:24px;padding:30px 32px;border-radius:20px;background:linear-gradient(120deg,#17233f,#263d72 60%,#315efb);color:#fff;box-shadow:0 18px 45px rgba(34,59,111,.2);overflow:hidden;position:relative;} .kb-hero-copy{max-width:640px;position:relative;z-index:1;} .kb-kicker{font-size:10px;letter-spacing:.18em;font-weight:700;color:#a9c0ff;margin-bottom:10px;} .kb-hero h2{margin:0 0 8px;font-size:26px;line-height:1.2;letter-spacing:-.03em;} .kb-hero p{margin:0;color:#d7e1f9;font-size:13px;line-height:1.7;} .kb-hero-actions{display:flex;align-items:center;gap:10px;position:relative;z-index:1;} .kb-status-banner{display:flex;align-items:center;gap:12px;padding:13px 16px;border-radius:12px;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);box-shadow:0 5px 18px rgba(27,39,66,.03);} .kb-status-banner.ok{border-left:3px solid #19a276;} .kb-status-banner.warn{border-left:3px solid #e39a27;} .kb-status-banner.bad{border-left:3px solid #e05555;} .kb-status-meta{font-size:12px;color:var(--dsw-alias-label-secondary);} .kb-overview-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;} .kb-overview-card{display:flex;flex-direction:column;align-items:flex-start;gap:8px;padding:18px;border:1px solid var(--dsw-alias-border-l1);border-radius:14px;background:var(--dsw-alias-bg-layer-1);text-align:left;cursor:pointer;box-shadow:0 5px 18px rgba(27,39,66,.035);transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease;} .kb-overview-card:hover{transform:translateY(-2px);box-shadow:0 12px 28px rgba(27,39,66,.09);border-color:#ccd7eb;} .kb-overview-card:before{content:"";width:28px;height:4px;border-radius:3px;background:#b6c2d6;} .kb-overview-card.accent:before{background:#315efb;} .kb-overview-card.violet:before{background:#7257d8;} .kb-overview-card.teal:before{background:#159a88;} .kb-overview-label{font-size:12px;color:var(--dsw-alias-label-secondary);} .kb-overview-card strong{font-size:30px;line-height:1;font-weight:700;color:var(--dsw-alias-label-primary);} .kb-overview-link{font-size:12px;color:#315efb;} .kb-home-columns{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:16px;} .kb-panel{padding:20px;min-height:166px;} .kb-next-action{width:100%;display:flex;align-items:center;gap:14px;padding:14px;border:1px solid #e5eaf2;border-radius:12px;background:#f8faff;text-align:left;color:var(--dsw-alias-label-primary);cursor:pointer;} .kb-next-action:hover{border-color:#b9c9ed;background:#f2f6ff;} .kb-next-number{display:grid;place-items:center;width:40px;height:40px;border-radius:12px;background:#e8efff;color:#315efb;font-size:18px;font-weight:700;} .kb-next-action strong,.kb-next-empty strong{display:block;font-size:13px;} .kb-next-action small,.kb-next-empty small{display:block;margin-top:4px;color:var(--dsw-alias-label-secondary);font-size:12px;} .kb-arrow{margin-left:auto;color:#315efb;font-size:18px;} .kb-next-empty{display:flex;align-items:center;gap:12px;padding:16px;border-radius:12px;background:#f7faf9;color:#159a88;} .kb-next-empty span{color:#203044;} .kb-metrics-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;} .kb-metric-card{padding:16px 18px;border:1px solid var(--dsw-alias-border-l1);border-radius:14px;background:var(--dsw-alias-bg-layer-1);transition:border-color .15s;} .kb-metric-card:hover{border-color:#ccd7eb;} .kb-metric-label{font-size:12px;color:var(--dsw-alias-label-secondary);} .kb-metric-num{font-size:26px;line-height:1.1;font-weight:700;color:var(--dsw-alias-label-primary);margin:8px 0 4px;font-variant-numeric:tabular-nums;} .kb-metric-sub{font-size:11.5px;color:var(--dsw-alias-label-secondary);} .kb-layer-row{display:flex;align-items:center;gap:10px;margin-top:10px;} .kb-layer-name{width:72px;flex:none;font-size:12px;color:var(--dsw-alias-label-primary);} .kb-layer-bar{flex:1;height:8px;border-radius:4px;background:#eef1f6;overflow:hidden;} .kb-layer-bar>i{display:block;height:100%;border-radius:4px;background:#315efb;} .kb-layer-count{flex:none;font-size:11.5px;color:var(--dsw-alias-label-secondary);font-variant-numeric:tabular-nums;} .kb-activity-list{display:flex;flex-direction:column;gap:4px;} .kb-activity-item{display:flex;align-items:center;gap:10px;padding:10px 4px;border-bottom:1px solid #eef1f5;} .kb-activity-item:last-child{border-bottom:0;} .kb-activity-mark{width:7px;height:7px;border-radius:50%;background:#e39a27;} .kb-activity-mark.ok{background:#19a276;} .kb-activity-mark.bad{background:#e05555;} .kb-activity-title{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--dsw-alias-label-primary);font-size:12.5px;} .kb-seg{padding:4px;background:#f1f4f8;border:1px solid var(--dsw-alias-border-l1);border-radius:10px;} .kb-seg button{border-radius:7px;color:var(--dsw-alias-label-secondary);} .kb-seg button.active{background:var(--dsw-alias-bg-layer-1);color:#315efb;box-shadow:0 2px 7px rgba(30,49,87,.1);} .kb-empty{min-height:110px;color:var(--dsw-alias-label-secondary);}',

      '@media (max-width:860px){.kb-content{padding:18px 14px}.kb-topbar{gap:10px;padding-left:14px;padding-right:14px}.kb-hero{padding:24px;flex-direction:column}.kb-hero-actions{align-items:stretch}.kb-hero-actions .kb-btn{flex:1}.kb-overview-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.kb-metrics-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.kb-home-columns{grid-template-columns:1fr}}',
    ].join('\n');

    function injectStyles() {
      const el = document.createElement('style');
      el.setAttribute('data-plugin', 'dsh-knowledge');
      el.textContent = CSS;
      document.head.appendChild(el);
      return function () { try { el.remove(); } catch (e) {} };
    }

    // ---------------------------------------------------------------- API

    async function handleResponse(r) {
      let data = null
      try { data = await r.json() } catch (e) {}
      if (!r.ok) {
        const msg = data && data.error ? data.error : ('HTTP ' + r.status)
        throw new Error(msg)
      }
      return data
    }

    function apiGet(path) { return fetch(path).then(handleResponse) }
    function apiPost(path, body) {
      return fetch(path, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body || {}),
      }).then(handleResponse)
    }
    function apiDelete(path) { return fetch(path, { method: 'DELETE' }).then(handleResponse) }
    function apiPatch(path, body) {
      return fetch(path, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body || {}),
      }).then(handleResponse)
    }
    function apiUpload(path, params, file) {
      const qs = new URLSearchParams()
      Object.keys(params || {}).forEach((k) => { if (params[k] !== undefined && params[k] !== null && params[k] !== '') qs.set(k, params[k]) })
      return fetch(path + '?' + qs.toString(), { method: 'POST', body: file }).then(handleResponse)
    }

    // ---------------------------------------------------------------- markdown（极简渲染器）

    function inlineNodes(text) {
      const out = [];
      const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)]+\))/g;
      let last = 0;
      let m;
      let n = 0;
      while ((m = re.exec(text)) !== null) {
        if (m.index > last) out.push(text.slice(last, m.index));
        if (m[1]) out.push(El('code', { key: 'k' + (n++) }, m[1].slice(1, -1)));
        else if (m[2]) out.push(El('strong', { key: 'k' + (n++) }, m[2].slice(2, -2)));
        else if (m[3]) out.push(El('em', { key: 'k' + (n++) }, m[3].slice(1, -1)));
        else if (m[4]) {
          const lm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(m[4]);
          out.push(El('a', { key: 'k' + (n++), href: lm[2], target: '_blank', rel: 'noopener noreferrer' }, lm[1]));
        }
        last = re.lastIndex;
      }
      if (last < text.length) out.push(text.slice(last));
      return out;
    }

    function mdToNodes(text) {
      const lines = String(text || '').split('\n');
      const blocks = [];
      let i = 0;
      let para = [];
      function flushPara() {
        if (para.length === 0) return;
        blocks.push(El('p', { key: 'p' + blocks.length }, inlineNodes(para.join(' '))));
        para = [];
      }
      while (i < lines.length) {
        const line = lines[i];
        if (/^\s*```/.test(line)) {
          flushPara();
          const codeLines = [];
          i++;
          while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) { codeLines.push(lines[i]); i++; }
          i++;
          blocks.push(El('pre', { key: 'pre' + blocks.length }, El('code', null, codeLines.join('\n'))));
          continue;
        }
        const hm = /^(#{1,6})\s+(.*)$/.exec(line);
        if (hm) {
          flushPara();
          const level = Math.min(6, hm[1].length);
          blocks.push(El('h' + level, { key: 'h' + blocks.length }, inlineNodes(hm[2])));
          i++;
          continue;
        }
        if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
          flushPara();
          blocks.push(El('hr', { key: 'hr' + blocks.length }));
          i++;
          continue;
        }
        if (/^\s*[-*+]\s+/.test(line)) {
          flushPara();
          const items = [];
          while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
            const im = /^\s*[-*+]\s+(.*)$/.exec(lines[i]);
            items.push(El('li', { key: 'li' + items.length }, inlineNodes(im ? im[1] : '')));
            i++;
          }
          blocks.push(El('ul', { key: 'ul' + blocks.length }, items));
          continue;
        }
        if (/^\s*\d+[.)]\s+/.test(line)) {
          flushPara();
          const items = [];
          while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
            const im = /^\s*\d+[.)]\s+(.*)$/.exec(lines[i]);
            items.push(El('li', { key: 'li' + items.length }, inlineNodes(im ? im[1] : '')));
            i++;
          }
          blocks.push(El('ol', { key: 'ol' + blocks.length }, items));
          continue;
        }
        if (/^\s*>/.test(line)) {
          flushPara();
          const q = [];
          while (i < lines.length && /^\s*>/.test(lines[i])) { q.push(lines[i].replace(/^\s*>\s?/, '')); i++; }
          blocks.push(El('blockquote', { key: 'bq' + blocks.length }, inlineNodes(q.join(' '))));
          continue;
        }
        if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/.test(lines[i + 1])) {
          flushPara();
          const splitCells = (l) => String(l).trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
          const headerCells = splitCells(line);
          i += 2;
          const bodyRows = [];
          while (i < lines.length && /^\s*\|/.test(lines[i])) { bodyRows.push(splitCells(lines[i])); i++; }
          blocks.push(El('table', { key: 'tbl' + blocks.length, className: 'kb-table' },
            El('thead', null,
              El('tr', null, headerCells.map((c, ci) => El('th', { key: 'h' + ci }, inlineNodes(c))))),
            El('tbody', null,
              bodyRows.map((r, ri) => El('tr', { key: 'r' + ri },
                r.map((c, ci) => El('td', { key: 'c' + ci, style: { fontSize: 12 } }, inlineNodes(c))))))));
          continue;
        }
        if (line.trim() === '') { flushPara(); i++; continue; }
        para.push(line.trim());
        i++;
      }
      flushPara();
      return blocks;
    }

    // ---------------------------------------------------------------- 通用小部件

    function usePoll(fn, ms, deps = []) {
      React.useEffect(function () {
        let alive = true
        const tick = () => {
          if (!alive) return
          Promise.resolve(fn()).catch(() => {})
        }
        tick()
        const t = setInterval(tick, ms)
        return function () { alive = false; clearInterval(t) }
      }, deps)
    }

    function docStatusChip(status) {
      const s = DOC_STATUS[status] || { label: status, cls: '' }
      return El('span', { className: 'kb-chip' + (s.cls ? ' ' + s.cls : ''), title: s.title || '' }, s.label)
    }

    function intentStatusChip(status) {
      const s = INTENT_STATUS[status] || { label: status, cls: '' }
      return El('span', { className: 'kb-chip' + (s.cls ? ' ' + s.cls : '') }, s.label)
    }

    function CardHead(props) {
      return El('div', { className: 'kb-cardhead' },
        props.icon ? icon(props.icon, 15, { opacity: .7 }) : null,
        El('h4', null, props.title),
        props.tip ? El('span', { className: 'kb-hint', title: props.tip, style: { cursor: 'help' } }, icon('help', 12)) : null,
        El('span', { className: 'kb-spacer' }),
        props.right || null)
    }

    function ErrorBox(props) {
      if (!props.text) return null
      return El('div', { className: 'kb-err', style: { marginTop: 8 } }, friendlyError(props.text))
    }

    function Empty(props) {
      return El('div', { className: 'kb-empty' },
        props.icon ? icon(props.icon, 22) : null,
        El('div', null, props.children))
    }

    // ---------------------------------------------------------------- 知识库运营

    /** 运营指标定义：[指标键, 名称, 含义说明（悬浮提示）]。 */
    const OPS_METRICS = [
      ['feedback_dup_rate', '负反馈重复率', '同一问题（按关联查询或问题原文识别）被重复反馈的比例；偏高说明同一问题在反复出现。'],
      ['clustering_rate', '相似问题聚类准确率', '相似反馈组被智能诊断归入同一案例的比例；越高说明诊断对相似问题的归并越准。'],
      ['proposal_approve_rate', '提案批准率', '你已决策的修复提案中批准的占比（含执行中、已完成、执行失败——它们都已通过审批）。'],
      ['proposal_reject_rate', '提案拒绝率', '你已决策的修复提案中拒绝的占比。'],
      ['execution_success_rate', '提案执行成功率', '已执行的提案中成功完成的占比；失败提案可在执行记录中查看原因并重新审批。'],
      ['verdict_resolved_rate', '用户确认解决率', '你复核时判定「已解决」的占比；衡量修复的真实效果。'],
      ['verdict_unresolved_rate', '用户确认仍有问题率', '你复核时判定「仍有问题」的占比；偏高说明诊断或修复质量待提升。'],
      ['recurrence_rate', '问题重新出现率', '修复成功后同一问题再次收到负反馈的提案占比；衡量修复的持久性。'],
      ['manual_review_rate', '模型输出需人工补充比例', '智能诊断案例中需要人工处置的比例（建议类动作不可自动执行，或证据校验不完整）；已处置关闭的案例仍计入，这是案例的固有属性。'],
    ]
    const OPS_LAYER_LABEL = { knowledge: '知识内容', graph: '图谱结构', retrieval: '检索过程', answer_generation: '回答生成', user_expectation: '用户预期' }

    /** 知识库运营总览：知识资产 / 检索信号 / 知识变更 / 健康快览（诊断域指标在「反馈与诊断 → 诊断总览」）。 */
    function OpsPane(props) {
      const [data, setData] = React.useState(null)
      const [err, setErr] = React.useState('')
      const go = props.go || function () {}
      usePoll(() => apiGet('/kb/ops/overview').then((d) => { setData(d); setErr('') }).catch((e) => setErr(e.message)), 30000)

      const docs = data && data.documents ? data.documents : null
      const queries = data && data.queries ? data.queries : null
      const changes = data && data.changes ? data.changes : null
      const health = data && data.health ? data.health : null
      const topics = docs && Array.isArray(docs.by_topic) ? docs.by_topic.slice(0, 8) : []
      const topicTotal = docs ? docs.total : 0
      const topQueries = queries && Array.isArray(queries.top_queries) ? queries.top_queries : []
      const byClass = changes && changes.by_class ? changes.by_class : {}
      const byActor = changes && changes.by_actor ? changes.by_actor : {}
      const actorLabel = (a) => ({ web: '工作台', user: '工作台', agent: '智能体', system: '系统' }[a] || a)

      const metric = (label, num, sub, tip) => El('div', { className: 'kb-metric-card', title: tip || '' },
        El('div', { className: 'kb-metric-label' }, label),
        El('div', { className: 'kb-metric-num' }, num),
        El('div', { className: 'kb-metric-sub' }, sub))

      return El('div', { className: 'kb-stack' },
        // ---- 知识资产：规模 / 增长 / 处理 / 主题分布 ----
        El('div', { className: 'kb-card' },
          El(CardHead, { title: '知识资产', icon: 'knowledge', tip: '知识库当前的规模与构成：文档总数、近期增长、处理状态与主题覆盖。' }),
          El(ErrorBox, { text: err }),
          El('div', { className: 'kb-metrics-grid' },
            metric('文档总数', data && docs ? docs.total : '…', '当前知识库文档量'),
            metric('近 7 天新增', data && docs ? docs.added : '…', '本周入库的文档数', '按文档创建时间统计近 7 天新增。'),
            metric('处理中', data && docs ? docs.processing : '…', '入库/更新进行中', '等待引擎处理的文档，可在文档管理页查看进度。'),
            metric('失败', data && docs ? docs.failed : '…', '解析或入库失败', '失败文档需要人工重试，详见文档管理页。')),
          topics.length ? El('div', { style: { marginTop: 12 } },
            El('div', { className: 'kb-hint', style: { marginBottom: 4 } }, '主题分布（Top ' + topics.length + '）：'),
            topics.map(function (t) {
              return El('div', { key: t.topic, className: 'kb-layer-row' },
                El('span', { className: 'kb-layer-name', style: { width: 130 }, title: t.topic }, t.topic),
                El('span', { className: 'kb-layer-bar' }, El('i', { style: { width: (topicTotal ? Math.round(t.count / topicTotal * 100) : 0) + '%' } })),
                El('span', { className: 'kb-layer-count' }, t.count + ' 篇 · ' + (topicTotal ? Math.round(t.count / topicTotal * 100) : 0) + '%'))
            })) : null),

        // ---- 检索信号：流量 / 零命中 / 高频查询 ----
        El('div', { className: 'kb-card' },
          El(CardHead, { title: '检索信号（近 7 天）', icon: 'chart', tip: '知识库的使用流量与命中质量；零命中偏高说明知识覆盖有缺口（可在健康体检里做缺口分诊）。' }),
          El('div', { className: 'kb-metrics-grid' },
            metric('查询总量', data && queries ? queries.total : '…', '近 7 天检索请求'),
            metric('零命中查询', data && queries ? queries.zero_ref : '…', '没有任何引用命中的查询'),
            metric('零命中率', data && queries && queries.zero_ref_rate !== null && queries.zero_ref_rate !== undefined ? (queries.zero_ref_rate * 100).toFixed(1) + '%' : '–', '零命中 / 总量')),
          topQueries.length ? El('div', { style: { marginTop: 12 } },
            El('div', { className: 'kb-hint', style: { marginBottom: 4 } }, '高频查询：'),
            El('div', { className: 'kb-rows' }, topQueries.map(function (t, i) {
              return El('div', { key: 'q' + i, className: 'kb-row', style: { padding: '6px 10px' } },
                El('span', { className: 'kb-hint', style: { width: 20 } }, (i + 1) + '.'),
                El('span', { className: 't', title: t.query }, t.query))
            }))) : El('div', { className: 'kb-hint', style: { marginTop: 10 } }, data ? '近 7 天暂无查询' : '加载中…')),

        // ---- 知识变更：活跃度 / 分类 / 来源 ----
        El('div', { className: 'kb-card' },
          El(CardHead, { title: '知识变更（近 7 天）', icon: 'clock', tip: '知识库内容的变更活跃度：入库、文档变更、图谱编辑，以及谁做的（工作台 / 智能体 / 系统）。' }),
          El('div', { className: 'kb-metrics-grid' },
            metric('变更总数', data && changes ? changes.total : '…', '近 7 天全部知识操作'),
            metric('入库', data ? (byClass['入库'] || 0) : '…', '新增文档/文本'),
            metric('文档变更', data ? (byClass['文档变更'] || 0) : '…', '替换/删除/重试'),
            metric('图谱编辑', data ? (byClass['图谱编辑'] || 0) : '…', '实体与关系的增删改')),
          El('div', { className: 'kb-hint', style: { marginTop: 10 } },
            '变更来源：' + (Object.keys(byActor).length
              ? Object.keys(byActor).map(function (a) { return actorLabel(a) + ' ' + byActor[a] + ' 次' }).join(' · ')
              : (data ? '近 7 天无变更' : '加载中…')))),

        // ---- 知识健康：快览 + 入口 ----
        El('div', { className: 'kb-card' },
          El(CardHead, { title: '知识健康', icon: 'shield', tip: '快速掌握失败文档与最近体检；完整体检在「健康体检」视图。' }),
          El('div', { className: 'kb-form-row' },
            El('span', { className: 'kb-hint' }, '失败文档 ', El('b', null, health ? health.failed_docs : '–'), ' 篇'),
            El('span', { className: 'kb-hint' }, '上次体检 ' + (health && health.last_analysis_at ? fmtTs(health.last_analysis_at) : '尚未体检')),
            El('span', { className: 'kb-spacer' }),
            El('button', { className: 'kb-btn', onClick: () => go('health') }, icon('shield', 13), '去健康体检'))))
    }

    // ---------------------------------------------------------------- 总览

    /** 诊断总览：反馈/提案/执行的状态入口 + 诊断域运营指标（10 项 + 问题层级分布）。 */
    function OverviewPane(props) {
      const setSub = props.setSub || function () {}
      const openView = props.openView
      function go(tabId, subId) {
        if (tabId === 'auto') setSub(subId || 'overview')
        else if (openView) openView('knowledge-' + tabId, subId || '')
      }
      const [health, setHealth] = React.useState(null)
      const [feedback, setFeedback] = React.useState(null)
      const [diagnoses, setDiagnoses] = React.useState(null)
      const [docs, setDocs] = React.useState(null)

      const [opsData, setOpsData] = React.useState(null)
      usePoll(() => Promise.all([
        apiGet('/kb/health').then(setHealth),
        apiGet('/kb/feedback?status=open&rating=negative&limit=200').then(setFeedback),
        apiGet('/kb/diagnoses?limit=20').then(setDiagnoses),
        apiGet('/kb/documents?page=1&page_size=10').then(setDocs),
      ]).catch((e) => setHealth({ ok: false, error: e.message })), 15000)
      // 诊断域运营指标（10 项 + 问题层级分布）：与总览页（知识库运营）互补
      usePoll(() => apiGet('/kb/ops/metrics').then(setOpsData).catch(() => {}), 30000)

      // health 轮询仅取 stats 兜底文档总数；引擎健康详情在一级视图「健康体检」
      const regStats = health && health.stats ? health.stats : {}
      const openFeedback = feedback && Array.isArray(feedback.feedback) ? feedback.feedback : []
      const allProposals = diagnoses && Array.isArray(diagnoses.diagnoses)
        ? diagnoses.diagnoses.flatMap((d) => d.proposals || []) : []
      const pendingProposals = allProposals.filter((p) => p.status === 'awaiting_approval')
      const executing = allProposals.filter((p) => p.status === 'executing')
      const recent = allProposals.filter((p) => ['succeeded', 'failed', 'executing'].includes(p.status)).slice(0, 5)
      const docTotal = docs && docs.total !== undefined ? docs.total : regStats.documents_total

      const hero = El('section', { className: 'kb-hero' },
        El('div', { className: 'kb-hero-copy' },
          El('div', { className: 'kb-kicker' }, 'KNOWLEDGE WORKSPACE'),
          El('h2', null, '让每一次反馈都变成一次改进'),
          El('p', null, '收集真实使用中的问题，交给智能体分析，再由你决定哪些修复进入知识库。')),
        El('div', { className: 'kb-hero-actions' },
          El('button', { className: 'kb-btn primary big', onClick: () => go('auto', 'feedback') }, icon('message', 14), '查看反馈'),
          El('button', { className: 'kb-btn ghost big', onClick: () => go('docs', 'add') }, icon('plus', 14), '添加知识')))
      const cards = El('div', { className: 'kb-overview-grid' },
        El('button', { className: 'kb-overview-card accent', onClick: () => go('auto', 'feedback') }, El('span', { className: 'kb-overview-label' }, '待处理反馈'), El('strong', null, openFeedback.length), El('span', { className: 'kb-overview-link' }, openFeedback.length ? '开始诊断 →' : '暂无待处理')),
        El('button', { className: 'kb-overview-card violet', onClick: () => go('auto', 'proposals') }, El('span', { className: 'kb-overview-label' }, '待审批提案'), El('strong', null, pendingProposals.length), El('span', { className: 'kb-overview-link' }, pendingProposals.length ? '查看提案 →' : '暂无待审批')),
        El('button', { className: 'kb-overview-card teal', onClick: () => go('auto', 'execution') }, El('span', { className: 'kb-overview-label' }, '执行中任务'), El('strong', null, executing.length), El('span', { className: 'kb-overview-link' }, executing.length ? '查看进度 →' : '系统空闲')),
        El('button', { className: 'kb-overview-card neutral', onClick: () => go('docs', 'docs') }, El('span', { className: 'kb-overview-label' }, '知识文档'), El('strong', null, docTotal ?? '–'), El('span', { className: 'kb-overview-link' }, '管理文档 →')))
      const nextPanel = El('section', { className: 'kb-panel' },
        El(CardHead, { title: '下一步', icon: 'bulb' }),
        pendingProposals.length
          ? El('button', { className: 'kb-next-action', onClick: () => go('auto', 'proposals') }, El('span', { className: 'kb-next-number' }, pendingProposals.length), El('span', null, El('strong', null, '张提案等待你的决定'), El('small', null, '确认证据和变更内容后再执行')), El('span', { className: 'kb-arrow' }, '→'))
          : openFeedback.length
            ? El('button', { className: 'kb-next-action', onClick: () => go('auto', 'feedback') }, El('span', { className: 'kb-next-number' }, openFeedback.length), El('span', null, El('strong', null, '条反馈可以开始诊断'), El('small', null, '智能体会按根因聚类并生成修复建议')), El('span', { className: 'kb-arrow' }, '→'))
            : El('div', { className: 'kb-next-empty' }, icon('check', 18), El('span', null, El('strong', null, '今天没有待处理事项'), El('small', null, '继续使用，在遇到问题时反馈即可'))))
      const activityPanel = El('section', { className: 'kb-panel' },
        El(CardHead, { title: '最近修复', icon: 'clock', right: El('button', { className: 'kb-btn linky', onClick: () => go('auto', 'execution') }, '全部记录 →') }),
        recent.length
          ? El('div', { className: 'kb-activity-list' }, recent.map((p) => El('div', { className: 'kb-activity-item', key: p.proposal_id }, El('span', { className: 'kb-activity-mark ' + (p.status === 'failed' ? 'bad' : p.status === 'succeeded' ? 'ok' : 'warn') }), El('span', { className: 'kb-activity-title' }, p.title || '知识库优化提案'), El('span', { className: 'kb-chip ' + (p.status === 'succeeded' ? 'ok' : p.status === 'failed' ? 'failed' : 'pending') }, p.status === 'succeeded' ? '已完成' : p.status === 'failed' ? '失败' : '执行中'))))
          : El(Empty, { icon: 'clock' }, '还没有修复记录'))
      const columns = El('div', { className: 'kb-home-columns' }, nextPanel, activityPanel)

      // 诊断域运营指标（从反馈与诊断账本汇总，衡量"越用越准"）
      const pct = (m) => m && m.value !== null && m.value !== undefined ? (m.value * 100).toFixed(1) + '%' : '–'
      const subText = (m) => (m && m.den ? m.num + ' / ' + m.den + ' 条' : '暂无数据')
      const layers = opsData && opsData.layer_distribution ? opsData.layer_distribution : {}
      const layerKeys = Object.keys(OPS_LAYER_LABEL).filter((k) => layers[k])
      const layerTotal = layerKeys.reduce((a, k) => a + layers[k], 0)
      const metricsCard = El('div', { className: 'kb-card' },
        El(CardHead, { title: '诊断运营指标', icon: 'chart', tip: '基于反馈与诊断记录自动汇总，衡量诊断闭环的质量。鼠标悬停指标卡可查看含义。' }),
        El('div', { className: 'kb-metrics-grid' },
          OPS_METRICS.map(function (row) {
            const key = row[0], label = row[1], tip = row[2]
            const m = opsData ? opsData[key] : null
            return El('div', { key: key, className: 'kb-metric-card', title: tip },
              El('div', { className: 'kb-metric-label' }, label),
              El('div', { className: 'kb-metric-num' }, opsData ? pct(m) : '…'),
              El('div', { className: 'kb-metric-sub' }, opsData ? subText(m) : '加载中…'))
          })))
      const layerCard = El('div', { className: 'kb-card' },
        El(CardHead, { title: '问题层级分布', icon: 'list', tip: '智能诊断案例按问题层级的计数；层级决定修复方向（补知识 / 改图谱 / 调检索 / 调回答 / 对齐预期）。' }),
        layerTotal === 0
          ? El(Empty, null, opsData ? '暂无智能诊断案例' : '加载中…')
          : El('div', null,
              El('div', { className: 'kb-hint', style: { marginBottom: 6 } }, '共 ' + layerTotal + ' 个诊断案例'),
              layerKeys.map(function (k) {
                return El('div', { key: k, className: 'kb-layer-row' },
                  El('span', { className: 'kb-layer-name' }, OPS_LAYER_LABEL[k]),
                  El('span', { className: 'kb-layer-bar' }, El('i', { style: { width: Math.round(layers[k] / layerTotal * 100) + '%' } })),
                  El('span', { className: 'kb-layer-count' }, layers[k] + ' 条 · ' + Math.round(layers[k] / layerTotal * 100) + '%'))
              })))
      return El('div', { className: 'kb-home' }, hero, cards, columns, metricsCard, layerCard)

    }

    // ---------------------------------------------------------------- 文档管理

    function DocsTab(props) {
      const sub = props.sub || 'docs'
      const setSub = props.onSubChange || function () {}
      const pills = [['docs', '文档列表'], ['add', '添加文档'], ['graph', '图谱管理']]
      return El('div', { className: 'kb-stack' },
        El('div', { className: 'kb-seg' },
          pills.map(([id, label]) => El('button', {
            key: id, className: sub === id ? 'active' : '', onClick: () => setSub(id),
          }, label))),
        sub === 'add' ? El(AddPane)
          : sub === 'graph' ? El(GraphPane)
            : El(DocsPane))
    }

    // ---- 文档管理 ----

    function DocsPane() {
      const [items, setItems] = React.useState(null)
      const [status, setStatus] = React.useState('')
      const [topic, setTopic] = React.useState('')
      const [q, setQ] = React.useState('')
      const [confirmId, setConfirmId] = React.useState(null)
      const [err, setErr] = React.useState('')
      const [reloadTick, setReloadTick] = React.useState(0)
      const [page, setPage] = React.useState(1)
      const [toast, setToast] = React.useState('')

      React.useEffect(function () {
        let alive = true
        const load = () => {
          const qs = new URLSearchParams()
          if (status) qs.set('status', status)
          if (topic) qs.set('topic', topic)
          if (q) qs.set('q', q)
          qs.set('page', String(page))
          qs.set('page_size', '20')
          apiGet('/kb/documents?' + qs.toString())
            .then((d) => { if (alive) setItems(d) })
            .catch((e) => { if (alive) setErr(e.message) })
        }
        load()
        const t = setInterval(load, 10000)
        return function () { alive = false; clearInterval(t) }
      }, [status, topic, q, page, reloadTick])

      function flash(msg) { setToast(msg); setTimeout(() => setToast(''), 4000) }

      function doDelete(id) {
        apiDelete('/kb/documents/' + encodeURIComponent(id))
          .then(() => { setConfirmId(null); flash('已提交删除，处理中'); setReloadTick((x) => x + 1) })
          .catch((e) => setErr(e.message))
      }
      function doRetry(id) {
        apiPost('/kb/documents/' + encodeURIComponent(id) + '/retry', {})
          .then(() => { flash('已重新提交处理'); setReloadTick((x) => x + 1) })
          .catch((e) => setErr(e.message))
      }
      function doReplace(id, file) {
        if (!file) return
        apiUpload('/kb/documents/' + encodeURIComponent(id) + '/replace', { filename: file.name, reason: '工作台替换' }, file)
          .then(() => { flash('新版本已提交，替换中'); setReloadTick((x) => x + 1) })
          .catch((e) => setErr(e.message))
      }

      const rows = items && items.items ? items.items : []
      const pages = items ? Math.max(1, Math.ceil((items.total || 0) / (items.page_size || 20))) : 1

      return El('div', { className: 'kb-card' },
        El(CardHead, { title: '文档列表', icon: 'file', tip: '状态说明：已生效 = 可被检索；排队中/处理中 = 引擎学习中；失败 = 需重试或删除。' }),
        El('div', { className: 'kb-form-row' },
          El('input', { className: 'kb-input', placeholder: '搜索标题…', value: q, onChange: (e) => { setQ(e.target.value); setPage(1) } }),
          El('select', { className: 'kb-select', value: status, onChange: (e) => { setStatus(e.target.value); setPage(1) } },
            El('option', { value: '' }, '全部状态'),
            Object.keys(DOC_STATUS).map((s) => El('option', { key: s, value: s }, DOC_STATUS[s].label))),
          El('select', { className: 'kb-select', value: topic, onChange: (e) => { setTopic(e.target.value); setPage(1) } },
            El('option', { value: '' }, '全部主题'),
            TOPICS.map((t) => El('option', { key: t, value: t }, t))),
          El('span', { className: 'kb-hint' }, items ? '共 ' + items.total + ' 篇' : '加载中…'),
          El('span', { className: 'kb-spacer' }),
          El('button', { className: 'kb-btn', disabled: !items || page <= 1, onClick: () => setPage((x) => Math.max(1, x - 1)) }, '‹'),
          El('span', { className: 'kb-hint' }, page + ' / ' + pages),
          El('button', { className: 'kb-btn', disabled: !items || page >= pages, onClick: () => setPage((x) => x + 1) }, '›')),
        El(ErrorBox, { text: err }),
        toast ? El('div', { className: 'kb-hint', style: { color: 'var(--kb-ok)', margin: '4px 0 8px' } }, '✓ ' + toast) : null,
        El('table', { className: 'kb-table' },
          El('thead', null,
            El('tr', null,
              El('th', null, '文档'),
              El('th', null, '主题'),
              El('th', null, '状态'),
              El('th', null, '更新时间'),
              El('th', null, '操作'))),
          El('tbody', null,
            rows.length === 0
              ? El('tr', null, El('td', { colSpan: 5 }, El(Empty, { icon: 'file' }, items ? '暂无文档，可通过「添加文档」上传' : '加载中…')))
              : rows.map((d) => {
                  const working = d.status === 'pending' || d.status === 'processing' || d.status === 'updating'
                  const failed = d.status === 'failed'
                  let actions
                  if (confirmId === d.id) {
                    actions = El('span', null,
                      El('span', { className: 'kb-hint', style: { marginRight: 6 } }, '确认删除？'),
                      El('button', { className: 'kb-btn danger', onClick: () => doDelete(d.id) }, '删除'),
                      El('button', { className: 'kb-btn', style: { marginLeft: 4 }, onClick: () => setConfirmId(null) }, '取消'))
                  } else {
                    const btns = []
                    if (!working) btns.push(El('label', { key: 'rep', className: 'kb-btn', style: { cursor: 'pointer', display: 'inline-flex' }, title: '上传新版本替换此文档' },
                      icon('swap', 12), '替换',
                      El('input', {
                        type: 'file', style: { display: 'none' },
                        onChange: (e) => { doReplace(d.id, e.target.files && e.target.files[0]); e.target.value = '' },
                      })))
                    if (failed) btns.push(El('button', { key: 'rt', className: 'kb-btn', style: { marginLeft: 4 }, title: '重新提交处理', onClick: () => doRetry(d.id) }, icon('refresh', 12), '重试'))
                    if (!working) btns.push(El('button', { key: 'del', className: 'kb-btn danger', style: { marginLeft: 4 }, title: '从知识库移除此文档', onClick: () => setConfirmId(d.id) }, icon('trash', 12), '删除'))
                    actions = El('span', null, btns)
                  }
                  return El('tr', { key: d.id },
                    El('td', { style: { wordBreak: 'break-word', maxWidth: 320 } },
                      El('div', { style: { fontWeight: 600 }, title: '文档 ID：' + d.id }, d.title),
                      El('div', { className: 'kb-hint' }, 'v' + d.version)),
                    El('td', null, El('span', { className: 'kb-chip' }, d.topic || '未分类')),
                    El('td', null,
                      docStatusChip(d.status),
                      d.error_msg ? El('div', { className: 'kb-err', style: { fontSize: 11, marginTop: 3, maxWidth: 220 } }, d.error_msg.slice(0, 100)) : null),
                    El('td', { className: 'kb-hint', style: { whiteSpace: 'nowrap' } }, (d.updated_at || d.created_at || '').slice(0, 16).replace('T', ' ')),
                    El('td', null, actions))
                }))))
    }

    // ---- 添加文档 ----

    function AddPane() {
      const [over, setOver] = React.useState(false)
      const [uploads, setUploads] = React.useState([])
      const [title, setTitle] = React.useState('')
      const [topic, setTopic] = React.useState('未分类')
      const [text, setText] = React.useState('')
      const [textMsg, setTextMsg] = React.useState(null)
      const fileRef = React.useRef(null)

      function startUpload(files) {
        const list = Array.from(files || [])
        list.forEach((file) => {
          const id = Date.now() + '-' + Math.random().toString(36).slice(2)
          setUploads((u) => u.concat([{ id, name: file.name, status: 'uploading', msg: '' }]))
          apiUpload('/kb/documents/upload', { filename: file.name, title: file.name, topic, kb: 'company' }, file)
            .then(() => {
              setUploads((u) => u.map((x) => x.id === id ? { ...x, status: 'queued', msg: '已提交，排队处理' } : x))
            })
            .catch((e) => {
              setUploads((u) => u.map((x) => x.id === id ? { ...x, status: 'error', msg: friendlyError(e) } : x))
            })
        })
      }

      function submitText() {
        if (!title.trim() || !text.trim()) { setTextMsg({ kind: 'err', text: '请填写标题和正文' }); return }
        setTextMsg(null)
        apiPost('/kb/documents/text', { title: title.trim(), text: text.trim(), topic, kb: 'company' })
          .then(() => {
            setTextMsg({ kind: 'ok', text: '已提交，排队处理完成后可在「文档管理」查看' })
            setTitle('')
            setText('')
          })
          .catch((e) => setTextMsg({ kind: 'err', text: friendlyError(e) }))
      }

      return El('div', null,
        El('div', { className: 'kb-card' },
          El(CardHead, { title: '上传文档', icon: 'file', tip: '上传后自动排队处理，完成后即可被检索。' }),
          El('div', {
            className: 'kb-drop' + (over ? ' over' : ''),
            onClick: () => fileRef.current && fileRef.current.click(),
            onDragOver: (e) => { e.preventDefault(); setOver(true) },
            onDragLeave: () => setOver(false),
            onDrop: (e) => { e.preventDefault(); setOver(false); startUpload(e.dataTransfer.files) },
          },
            El('b', null, '拖拽文件至此，或点击选择'),
            El('span', { style: { fontSize: 12 } }, '支持 Word / Excel / PPT / Markdown / 文本 · 单个 ≤ 100MB · 可多选')),
          El('input', {
            ref: fileRef, type: 'file', multiple: true, style: { display: 'none' },
            onChange: (e) => { startUpload(e.target.files); e.target.value = '' },
          }),
          El('div', { className: 'kb-form-row', style: { marginTop: 10 } },
            El('label', null, '主题'),
            El('select', { className: 'kb-select', value: topic, onChange: (e) => setTopic(e.target.value) },
              TOPICS.map((t) => El('option', { key: t, value: t }, t)))),
          uploads.length ? El('div', null, uploads.map((u) => El('div', { key: u.id, className: 'kb-upload-row' },
            El('span', { className: 'kb-dot ' + (u.status === 'error' ? 'bad' : u.status === 'queued' ? 'ok' : 'warn') }),
            El('span', { style: { flex: 1, wordBreak: 'break-all' } }, u.name),
            El('span', { className: u.status === 'error' ? 'kb-err' : 'kb-hint' }, u.status === 'uploading' ? '上传中…' : u.msg)))) : null),
        El('div', { className: 'kb-card' },
          El(CardHead, { title: '录入文本', icon: 'knowledge', tip: '适用于会议结论、制度条文等结构化文本，直接入库。' }),
          El('div', { className: 'kb-form-row' },
            El('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '标题（必填）', value: title, onChange: (e) => setTitle(e.target.value) }),
            El('select', { className: 'kb-select', value: topic, onChange: (e) => setTopic(e.target.value) },
              TOPICS.map((t) => El('option', { key: t, value: t }, t)))),
          El('textarea', { className: 'kb-textarea', placeholder: '粘贴或输入正文（必填）', value: text, onChange: (e) => setText(e.target.value) }),
          El('div', { className: 'kb-form-row', style: { marginTop: 10, marginBottom: 0 } },
            El('button', { className: 'kb-btn primary big', onClick: submitText }, '提交入库'),
            textMsg ? El('span', { className: textMsg.kind === 'err' ? 'kb-err' : 'kb-hint', style: textMsg.kind === 'ok' ? { color: 'var(--kb-ok)' } : undefined }, textMsg.text) : null)))
    }

    // ---- 知识图谱 ----

    function layoutGraph(entities, relations, width, height) {
      const ids = entities.map((n) => n.id)
      const idx = {}
      ids.forEach((id, i) => { idx[id] = i })
      const pos = {}
      ids.forEach((id) => { pos[id] = { x: width / 2 + (Math.random() - 0.5) * 240, y: height / 2 + (Math.random() - 0.5) * 240 } })
      const edges = (relations || []).filter((r) => idx[r.source] !== undefined && idx[r.target] !== undefined && r.source !== r.target)
      const K = 140
      for (let iter = 0; iter < 150; iter++) {
        const fx = new Array(ids.length).fill(0)
        const fy = new Array(ids.length).fill(0)
        for (let i = 0; i < ids.length; i++) {
          for (let j = i + 1; j < ids.length; j++) {
            let dx = pos[ids[i]].x - pos[ids[j]].x
            let dy = pos[ids[i]].y - pos[ids[j]].y
            let d = Math.sqrt(dx * dx + dy * dy) || 0.01
            if (d > 800) d = 800
            const f = (K * K) / d
            const ux = dx / d, uy = dy / d
            fx[i] += ux * f; fy[i] += uy * f
            fx[j] -= ux * f; fy[j] -= uy * f
          }
        }
        for (const e of edges) {
          const a = idx[e.source], b = idx[e.target]
          const dx = pos[e.source].x - pos[e.target].x
          const dy = pos[e.source].y - pos[e.target].y
          const d = Math.sqrt(dx * dx + dy * dy) || 0.01
          const f = (d * d) / K
          const ux = dx / d, uy = dy / d
          fx[a] -= ux * f; fy[a] -= uy * f
          fx[b] += ux * f; fy[b] += uy * f
        }
        for (let i = 0; i < ids.length; i++) {
          const id = ids[i]
          fx[i] += (width / 2 - pos[id].x) * 0.008
          fy[i] += (height / 2 - pos[id].y) * 0.008
          pos[id].x += fx[i] * 0.05
          pos[id].y += fy[i] * 0.05
          pos[id].x = Math.max(30, Math.min(width - 30, pos[id].x))
          pos[id].y = Math.max(24, Math.min(height - 24, pos[id].y))
        }
      }
      return { pos, edges }
    }

    function GraphPane() {
      const [search, setSearch] = React.useState('')
      const [results, setResults] = React.useState([])
      const [graph, setGraph] = React.useState(null)
      const [sel, setSel] = React.useState(null)
      const [err, setErr] = React.useState('')
      const [editDesc, setEditDesc] = React.useState('')
      const [mergeTarget, setMergeTarget] = React.useState('')
      const [mergeSources, setMergeSources] = React.useState([])
      const [newName, setNewName] = React.useState('')
      const [newDesc, setNewDesc] = React.useState('')
      const [relSrc, setRelSrc] = React.useState('')
      const [relTgt, setRelTgt] = React.useState('')
      const [relDesc, setRelDesc] = React.useState('')
      const [selEdge, setSelEdge] = React.useState(null)
      const [edgeDesc, setEdgeDesc] = React.useState('')
      const [reloadTick, setReloadTick] = React.useState(0)
      const [confirm, setConfirm] = React.useState(null)

      React.useEffect(function () {
        if (!search.trim()) { setResults([]); return }
        let alive = true
        apiGet('/kb/graph/entities?q=' + encodeURIComponent(search.trim()) + '&limit=30')
          .then((d) => { if (alive) setResults(d.entities || []) })
          .catch((e) => { if (alive) setErr(e.message) })
        return function () { alive = false }
      }, [search, reloadTick])

      function loadGraph(label) {
        setErr('')
        apiGet('/kb/graph/visualize?label=' + encodeURIComponent(label) + '&max_depth=2&max_nodes=120')
          .then((d) => {
            setGraph(d)
            if (!d || !d.entities || !d.entities.length) {
              setErr('未找到「' + label + '」的关联关系，请在左侧选择实体后重试')
            }
          })
          .catch((e) => setErr(e.message))
      }

      function loadFromSearch() {
        const term = search.trim()
        if (!term) return
        if (results.length > 0) {
          setSel(results[0])
          loadGraph(results[0])
        } else {
          loadGraph(term)
        }
      }

      const layout = React.useMemo(function () {
        if (!graph || !graph.entities || !graph.entities.length) return null
        return layoutGraph(graph.entities, graph.relations, 900, 500)
      }, [graph])

      function op(fn) {
        return () => Promise.resolve(fn()).then(() => {
          setSel(null)
          setSelEdge(null)
          setMergeSources([])
          setConfirm(null)
          setReloadTick((x) => x + 1)
          setErr('')
        }).catch((e) => setErr(e.message))
      }

      const selEntity = sel ? (graph && graph.entities.find((n) => n.id === sel) || { id: sel, description: '', type: '' }) : null

      return El('div', { className: 'kb-stack' },
        El('div', { className: 'kb-card' },
          El(CardHead, { title: '实体检索', icon: 'graph', tip: '输入实体名称查看其关联网络；点击节点编辑实体，点击连线编辑关系。' }),
          El('div', { className: 'kb-form-row', style: { marginBottom: 0 } },
            El('input', {
              className: 'kb-input', style: { flex: 1, minWidth: 220 }, placeholder: '输入实体名称，如「报销」「供应商」',
              value: search, onChange: (e) => setSearch(e.target.value),
              onKeyDown: (e) => { if (e.key === 'Enter') loadFromSearch() },
            }),
            El('button', { className: 'kb-btn primary', disabled: !search.trim(), onClick: loadFromSearch }, icon('search', 13), '检索')),
          El(ErrorBox, { text: err })),
        El('div', { className: 'kb-side' },
          El('div', null,
            El('div', { className: 'kb-card' },
              El(CardHead, { title: '检索结果' }),
              El('div', { className: 'kb-list' },
                results.length === 0
                  ? El(Empty, { icon: 'search' }, '输入关键词后点击实体加载关联网络')
                  : results.map((name) => El('div', {
                      key: name, className: 'kb-list-item' + (sel === name ? ' sel' : ''),
                      onClick: () => { setSel(name); loadGraph(name) },
                    }, name)))),
            El('details', { className: 'kb-details' },
              El('summary', null, '手动补充实体与关系'),
              El('div', { className: 'kb-details-body' },
                El('div', { className: 'kb-form-row' },
                  El('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '实体名称', value: newName, onChange: (e) => setNewName(e.target.value) }),
                  El('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '描述（可选）', value: newDesc, onChange: (e) => setNewDesc(e.target.value) })),
                El('button', { className: 'kb-btn primary', disabled: !newName.trim(), onClick: op(() => apiPost('/kb/graph/entities/create', { name: newName.trim(), description: newDesc })) }, icon('plus', 12), '新建实体'),
                El('div', { className: 'kb-form-row', style: { marginTop: 12 } },
                  El('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '源实体', value: relSrc, onChange: (e) => setRelSrc(e.target.value) }),
                  El('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '目标实体', value: relTgt, onChange: (e) => setRelTgt(e.target.value) }),
                  El('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '关系描述', value: relDesc, onChange: (e) => setRelDesc(e.target.value) })),
                El('button', { className: 'kb-btn primary', disabled: !relSrc.trim() || !relTgt.trim(), onClick: op(() => apiPost('/kb/graph/relations/create', { src: relSrc.trim(), tgt: relTgt.trim(), description: relDesc })) }, icon('plus', 12), '新建关系')))),
          El('div', { className: 'kb-card' },
            El(CardHead, {
              title: graph && graph.entities && graph.entities.length
                ? (sel ? '「' + sel + '」关联网络' : '关联网络')
                : '关联网络',
              right: graph && graph.entities && graph.entities.length
                ? El('span', { className: 'kb-hint' }, graph.entities.length + ' 实体 · ' + graph.relations.length + ' 关系' + (graph.is_truncated ? '（已截断）' : ''))
                : null,
            }),
            layout
              ? El('div', { className: 'kb-graph-wrap' },
                  El('svg', { className: 'kb-graph-svg', viewBox: '0 0 900 500', preserveAspectRatio: 'xMidYMid meet' },
                    layout.edges.map((e, i) => {
                      const a = layout.pos[e.source]
                      const b = layout.pos[e.target]
                      const mx = (a.x + b.x) / 2
                      const my = (a.y + b.y) / 2
                      const showLabel = graph.relations.length <= 24 && e.description
                      const labelText = e.description.length > 12 ? e.description.slice(0, 12) + '…' : e.description
                      return El('g', {
                        key: 'e' + i,
                        onClick: () => { setSelEdge(e); setEdgeDesc(e.description || '') },
                      },
                        El('line', {
                          className: 'kb-edge' + (selEdge && selEdge.id === e.id ? ' sel' : ''),
                          x1: a.x, y1: a.y, x2: b.x, y2: b.y,
                        }),
                        El('title', null, e.source + ' → ' + e.target + '：' + (e.description || '（无描述）')),
                        showLabel
                          ? El('text', { className: 'kb-edge-label', x: mx, y: my - 4, textAnchor: 'middle' }, labelText)
                          : null)
                    }),
                    graph.entities.map((n) => {
                      const p = layout.pos[n.id]
                      if (!p) return null
                      const label = n.id.length > 10 ? n.id.slice(0, 10) + '…' : n.id
                      return El('g', {
                        key: n.id, className: 'kb-node' + (sel === n.id ? ' sel' : ''),
                        onClick: () => setSel(n.id),
                      },
                        El('circle', { cx: p.x, cy: p.y, r: 6 }),
                        El('text', { x: p.x, y: p.y + 18, textAnchor: 'middle' }, label))
                    })))
              : El(Empty, { icon: 'graph' }, '检索并选择实体后，此处展示关联网络'),
            selEdge ? El('div', { className: 'kb-panel' },
              El('h5', null, selEdge.source + ' → ' + selEdge.target),
              El('div', { className: 'kb-hint', style: { margin: '4px 0 10px' } },
                selEdge.description ? selEdge.description.slice(0, 400) : '（此关系暂无描述）',
                selEdge.weight ? '（权重 ' + selEdge.weight + '）' : ''),
              El('div', { className: 'kb-form-row' },
                El('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '关系描述', value: edgeDesc, onChange: (e) => setEdgeDesc(e.target.value) }),
                El('button', {
                  className: 'kb-btn', disabled: !edgeDesc.trim(),
                  onClick: () => {
                    apiPost('/kb/graph/relations/edit', { src: selEdge.source, tgt: selEdge.target, updates: { description: edgeDesc.trim() } })
                      .then(() => { if (sel) loadGraph(sel) })
                      .catch((e) => setErr(e.message))
                  },
                }, '保存描述'),
                confirm === 'edge:' + selEdge.id
                  ? El('button', { className: 'kb-btn danger', onClick: op(() => apiPost('/kb/graph/relations/delete', { src: selEdge.source, tgt: selEdge.target })) }, '确认删除')
                  : El('button', { className: 'kb-btn danger', onClick: () => setConfirm('edge:' + selEdge.id) }, '删除关系'))) : null,
            selEntity ? El('div', { className: 'kb-panel' },
              El('h5', null, selEntity.id),
              selEntity.type ? El('div', { className: 'kb-hint' }, '类型：' + selEntity.type) : null,
              El('div', { className: 'kb-hint', style: { margin: '6px 0 10px' } }, selEntity.description ? selEntity.description.slice(0, 300) : '（此实体暂无描述，可补充）'),
              El('div', { className: 'kb-form-row' },
                El('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '实体描述', value: editDesc, onChange: (e) => setEditDesc(e.target.value) }),
                El('button', { className: 'kb-btn', disabled: !editDesc.trim(), onClick: op(() => apiPost('/kb/graph/entities/edit', { name: selEntity.id, updates: { description: editDesc.trim() } })) }, '保存描述')),
              El('div', { className: 'kb-form-row' },
                El('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '并入目标实体名（此实体并入它）', value: mergeTarget, onChange: (e) => setMergeTarget(e.target.value) }),
                El('button', { className: 'kb-btn', disabled: !mergeTarget.trim() || mergeTarget === selEntity.id, onClick: op(() => apiPost('/kb/graph/entities/merge', { sources: [selEntity.id], target: mergeTarget.trim() })) }, '合并')),
              El('div', { className: 'kb-form-row' },
                El('input', {
                  className: 'kb-input', style: { flex: 1 }, placeholder: '输入重复实体名后回车（可多个）', value: '',
                  onKeyDown: (e) => {
                    if (e.key === 'Enter' && e.target.value.trim()) {
                      const v = e.target.value.trim()
                      if (!mergeSources.includes(v)) setMergeSources((s) => s.concat([v]))
                      e.target.value = ''
                    }
                  },
                }),
                El('button', { className: 'kb-btn', disabled: !mergeSources.length, onClick: op(() => apiPost('/kb/graph/entities/merge', { sources: mergeSources, target: selEntity.id })) }, '合并至此')),
              mergeSources.length ? El('div', { className: 'kb-form-row' },
                El('span', { className: 'kb-hint' }, '待合并：'),
                mergeSources.map((s) => El('span', { key: s, className: 'kb-chip' }, s))) : null,
              El('div', { className: 'kb-form-row', style: { marginBottom: 0 } },
                confirm === 'ent:' + selEntity.id
                  ? El('button', { className: 'kb-btn danger', onClick: op(() => apiPost('/kb/graph/entities/delete', { name: selEntity.id })) }, '确认删除「' + selEntity.id + '」')
                  : El('button', { className: 'kb-btn danger', onClick: () => setConfirm('ent:' + selEntity.id) }, '删除实体'))) : null)))
    }

    // ---------------------------------------------------------------- 自动化评测

    function FeedbackPane(props) {
      const [data, setData] = React.useState(null)
      const [err, setErr] = React.useState('')
      const [running, setRunning] = React.useState(false)
      const [result, setResult] = React.useState(null)
      const [editing, setEditing] = React.useState(null)
      const [fbStatus, setFbStatus] = React.useState('open')
      usePoll(() => apiGet('/kb/feedback?status=' + fbStatus + '&rating=negative&limit=50').then((d) => { setData(d); setErr('') }).catch((e) => setErr(e.message)), 5000, [fbStatus])
      function diagnose() {
        if (running) return
        setRunning(true); setErr(''); setResult(null)
        apiPost('/kb/diagnoses/run', { limit: 50 }).then((r) => {
          setRunning(false)
          setResult(r && r.diagnosis ? r.diagnosis : { feedback_count: 0, proposals: [] })
        }).catch((e) => { setRunning(false); setErr(e.message) })
      }
      function removeFeedback(id) {
        if (!window.confirm('确定删除这条反馈吗？删除后不再参与诊断。')) return
        apiDelete('/kb/feedback/' + encodeURIComponent(id))
          .then(() => setErr(''))
          .catch((e) => setErr(e.message))
      }
      const setSub = props.onSubChange || function () {}
      const rows = data && Array.isArray(data.feedback) ? data.feedback : []
      const made = result && Array.isArray(result.proposals) ? result.proposals : []
      return El('div', { className: 'kb-stack' },
        El('div', { className: 'kb-card' },
          El(CardHead, { title: '反馈与诊断', icon: 'message', tip: '反馈是问题线索，智能体会结合查询、回答和引用生成修复提案。' }),
          El('div', { className: 'kb-form-row' },
            El('span', { className: 'kb-hint' }, '待处理 ', El('b', null, data && data.open !== undefined ? data.open : '–'),
              ' 条 · 已处理 ', El('b', null, data && data.total !== undefined ? Math.max(0, data.total - data.open) : '–'), ' 条'),
            El('select', { className: 'kb-select', style: { width: 'auto' }, value: fbStatus, onChange: (e) => setFbStatus(e.target.value) },
              El('option', { value: 'open' }, '待处理'),
              El('option', { value: 'reviewed' }, '已处理'),
              El('option', { value: 'all' }, '全部')),
            El('span', { className: 'kb-spacer' }),
            El('button', {
              className: 'kb-btn primary big',
              title: '「快速诊断」按问题类型规则聚类，只确定方向；让 AI 助手“诊断知识库负反馈”可获得结合检索证据的智能诊断。',
              disabled: running || !rows.length,
              onClick: diagnose,
            }, running ? '诊断中…' : '快速诊断')),
          El(ErrorBox, { text: err }),
          result ? El('div', { className: 'kb-status-banner ' + (made.length ? 'ok' : 'warn'), style: { marginTop: 10 } },
            El('span', { className: 'kb-status-meta', style: { flex: 1 } }, made.length
              ? '诊断完成：分析了 ' + (result.feedback_count || 0) + ' 条反馈，生成 ' + made.length + ' 张提案，等待你确认。'
              : '诊断完成：本次没有生成提案（反馈可能已被处理，或问题需要人工核对）。'),
            made.length ? El('button', { className: 'kb-btn primary', onClick: () => setSub('proposals') }, '查看提案') : null) : null,
          rows.length
            ? El('div', { className: 'kb-rows', style: { marginTop: 10 } }, rows.slice(0, 20).map((r) => {
                const refs = Array.isArray(r.references) ? r.references : []
                return El('div', { key: r.feedback_id, className: 'kb-row' },
                  El('div', { className: 'fb-head' },
                    El('span', { className: 'kb-chip warn' }, issueTypeLabel(r.issue_type)),
                    El('span', { className: 't', title: r.query || r.note }, r.query || r.note || '未填写问题'),
                    El('span', { className: 'kb-row-actions' },
                      El('button', { className: 'kb-btn linky', title: '修正问题类型或说明', onClick: () => setEditing(r) }, '编辑'),
                      El('button', { className: 'kb-btn linky danger-text', title: '删除这条反馈', onClick: () => removeFeedback(r.feedback_id) }, '删除')),
                    El('span', { className: 'ts' }, fmtTs(r.created_at))),
                  r.query && r.note ? El('div', { className: 'fb-note', title: r.note }, '备注：' + r.note) : null,
                  r.answer ? El('div', { className: 'fb-answer', title: r.answer }, '回答：' + r.answer) : null,
                  refs.length ? El('div', { className: 'fb-refs' },
                    refs.slice(0, 5).map((ref, i) => {
                      const file = (ref && ref.file) || ''
                      return El('span', { key: i, className: 'kb-chip', title: file }, file.split('/').pop() || '未命名文件')
                    }),
                    refs.length > 5 ? El('span', { className: 'kb-chip' }, '+' + (refs.length - 5)) : null) : null)
              }))
            : El(Empty, null, '暂无待处理负反馈')),
        El('div', { className: 'kb-card' },
          El(CardHead, { title: '使用方式', icon: 'help' }),
          El('div', { className: 'kb-hint' }, '在回答下方点击“反馈此回答”，选择问题类型并提交；诊断后到“修复提案”审批。')),
        editing ? El(FeedbackEditModal, {
          feedback: editing,
          onClose: () => setEditing(null),
          onSaved: () => setEditing(null),
        }) : null)
    }

    /** 反馈编辑弹窗：修正问题类型 / 说明（提交时的分类错误或不完整描述）。 */
    function FeedbackEditModal(props) {
      const f = props.feedback
      const [issueType, setIssueType] = React.useState(f.issue_type || 'other')
      const [note, setNote] = React.useState(f.note || '')
      const [err, setErr] = React.useState('')
      const [saving, setSaving] = React.useState(false)
      function save() {
        if (saving) return
        setSaving(true); setErr('')
        apiPatch('/kb/feedback/' + encodeURIComponent(f.feedback_id), { issue_type: issueType, note: note.trim() })
          .then(() => { setSaving(false); props.onSaved() })
          .catch((e) => { setSaving(false); setErr(e.message) })
      }
      return El('div', { className: 'kb-modal-backdrop', onClick: (e) => { if (e.target === e.currentTarget) props.onClose() } },
        El('div', { className: 'kb-modal' },
          El('h4', null, El('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 6 } }, icon('edit', 15), '编辑反馈'),
            El('button', { className: 'kb-btn linky', onClick: props.onClose }, '取消')),
          El('div', { className: 'kb-hint', style: { marginBottom: 10 } }, (f.query || '未关联查询') + ' · ' + fmtTs(f.created_at)),
          El('label', { className: 'kb-hint' }, '问题类型'),
          El('select', { className: 'kb-select', value: issueType, onChange: (e) => setIssueType(e.target.value) },
            Object.keys(ISSUE_TYPE_LABEL).map((k) => El('option', { key: k, value: k }, ISSUE_TYPE_LABEL[k]))),
          El('label', { className: 'kb-hint', style: { marginTop: 8 } }, '问题说明'),
          El('textarea', { className: 'kb-textarea', rows: 4, value: note, onChange: (e) => setNote(e.target.value), placeholder: '补充这条反馈的具体问题（诊断时的关键依据）' }),
          El(ErrorBox, { text: err }),
          El('div', { className: 'kb-form-row', style: { marginTop: 14, marginBottom: 0 } },
            El('span', { className: 'kb-spacer' }),
            El('button', { className: 'kb-btn', onClick: props.onClose }, '取消'),
            El('button', { className: 'kb-btn primary', disabled: saving, onClick: save }, saving ? '保存中…' : '保存'))))
    }

    /** 提案变更参数是否齐全（与后端 approve 校验同规则）。 */
    function payloadReady(p) {
      const pl = p.payload || {}
      if (p.action === 'add_text') return !!(pl.title && pl.text && (p.evidence || []).length)
      if (p.action === 'edit_entity') return !!(pl.entity_name && pl.updates && typeof pl.updates === 'object')
      if (p.action === 'edit_relation') return !!(pl.src && pl.tgt && pl.updates && typeof pl.updates === 'object')
      return false
    }

    /** 提案编辑弹窗：「编辑后执行」回填变更参数（标题/正文、实体/关系描述）。 */
    function ProposalEditModal(props) {
      const p = props.proposal
      const [form, setForm] = React.useState(function () {
        if (!p) return {}
        const pl = p.payload || {}
        if (p.action === 'add_text') return { title: pl.title || (p.evidence && p.evidence[0] && p.evidence[0].query) || '', topic: pl.topic || '未分类', text: pl.text || '' }
        if (p.action === 'edit_entity') return { entity_name: pl.entity_name || '', description: (pl.updates && pl.updates.description) || '' }
        return { src: pl.src || '', tgt: pl.tgt || '', description: (pl.updates && pl.updates.description) || '' }
      })
      // add_text 双模式：填写文本 / 上传文档（上传走与「文档管理」一致的文件入库通道）
      const [mode, setMode] = React.useState('text')
      const [file, setFile] = React.useState(null)
      React.useEffect(function () {
        if (!p) return
        const onKey = (e) => { if (e.key === 'Escape') props.onClose() }
        document.addEventListener('keydown', onKey)
        return function () { document.removeEventListener('keydown', onKey) }
      }, [p])
      if (!p) return null
      const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
      const titles = { add_text: '补充知识内容', edit_entity: '修正实体描述', edit_relation: '修正关系描述' }
      let payload = null
      if (p.action === 'add_text') {
        payload = mode === 'upload'
          ? { via: 'upload', topic: (form.topic || '未分类').trim() || '未分类' }
          : { title: form.title.trim(), topic: form.topic.trim() || '未分类', text: form.text }
      }
      else if (p.action === 'edit_entity') payload = { entity_name: form.entity_name.trim(), updates: { description: form.description } }
      else payload = { src: form.src.trim(), tgt: form.tgt.trim(), updates: { description: form.description } }
      const filled = p.action === 'add_text' ? (mode === 'upload' ? file : (payload.title && payload.text))
        : p.action === 'edit_entity' ? (payload.entity_name && form.description.trim())
          : (payload.src && payload.tgt && form.description.trim())
      return El('div', { className: 'kb-modal-backdrop', onClick: (e) => { if (e.target === e.currentTarget) props.onClose() } },
        El('div', { className: 'kb-modal' },
          El('h4', null, El('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 6 } }, icon('edit', 15), titles[p.action] || '补充提案参数'),
            El('button', { className: 'kb-btn linky', onClick: props.onClose }, '取消')),
          El('div', { className: 'kb-hint', style: { marginBottom: 10 } }, '快速诊断只确定问题方向，具体内容由你补充后入库。'),
          p.action === 'add_text' ? [
            El('div', { key: 'seg', className: 'kb-seg', style: { marginBottom: 12 } },
              El('button', { className: mode === 'text' ? 'active' : '', onClick: () => setMode('text') }, '填写文本'),
              El('button', { className: mode === 'upload' ? 'active' : '', onClick: () => setMode('upload') }, '上传文档')),
            mode === 'upload' ? [
              El('div', { key: 'pick', className: 'kb-form-row' },
                El('label', { className: 'kb-btn', style: { cursor: 'pointer', display: 'inline-flex' }, title: '选择要入库的文档' },
                  icon('file', 12), '选择文件',
                  El('input', { type: 'file', style: { display: 'none' }, onChange: (e) => { setFile(e.target.files && e.target.files[0] || null); e.target.value = '' } })),
                file ? El('span', { className: 'kb-upload-row', style: { flex: 1, marginTop: 0 } },
                  El('span', { style: { flex: 1, wordBreak: 'break-all' } }, file.name + '（' + (file.size / 1048576).toFixed(1) + ' MB）'),
                  El('button', { className: 'kb-btn linky', onClick: () => setFile(null) }, '移除'))
                  : El('span', { className: 'kb-hint' }, '尚未选择文件')),
              El('label', { key: 'top', className: 'kb-hint', style: { marginTop: 8 } }, '主题'),
              El('select', { key: 'sel', className: 'kb-select', value: form.topic || '未分类', onChange: set('topic') },
                TOPICS.map((t) => El('option', { key: t, value: t }, t))),
              El('div', { key: 'h', className: 'kb-hint', style: { marginTop: 8 } }, '与「文档管理」上传一致：自动排队解析并抽取知识，完成后即可检索。支持 Word / Excel / PPT / Markdown / 文本，单个 ≤ 100MB。'),
            ] : [
              El('label', { key: 't', className: 'kb-hint' }, '标题'),
              El('input', { key: 'ti', className: 'kb-input', value: form.title, onChange: set('title'), placeholder: '例如：差旅费管理办法（2025版）要点' }),
              El('label', { key: 'to', className: 'kb-hint', style: { marginTop: 8 } }, '主题'),
              El('select', { key: 'top2', className: 'kb-select', value: form.topic || '未分类', onChange: set('topic') },
                TOPICS.map((t) => El('option', { key: t, value: t }, t))),
              El('label', { key: 'x', className: 'kb-hint', style: { marginTop: 8 } }, '正文（将作为正式知识入库）'),
              El('textarea', { key: 'te', className: 'kb-textarea', rows: 8, value: form.text, onChange: set('text'), placeholder: '粘贴权威原文或经确认的内容' }),
            ],
          ] : p.action === 'edit_entity' ? [
            El('label', { key: 'n', className: 'kb-hint' }, '实体名称'),
            El('input', { key: 'ni', className: 'kb-input', value: form.entity_name, onChange: set('entity_name'), placeholder: '输入图谱中已存在的实体名' }),
            El('label', { key: 'd', className: 'kb-hint', style: { marginTop: 8 } }, '修正后的描述'),
            El('textarea', { key: 'de', className: 'kb-textarea', rows: 6, value: form.description, onChange: set('description'), placeholder: '输入正确的实体描述' }),
          ] : [
            El('label', { key: 's', className: 'kb-hint' }, '源实体'),
            El('input', { key: 'si', className: 'kb-input', value: form.src, onChange: set('src') }),
            El('label', { key: 't2', className: 'kb-hint', style: { marginTop: 8 } }, '目标实体'),
            El('input', { key: 'ti2', className: 'kb-input', value: form.tgt, onChange: set('tgt') }),
            El('label', { key: 'd2', className: 'kb-hint', style: { marginTop: 8 } }, '修正后的关系描述'),
            El('textarea', { key: 'de2', className: 'kb-textarea', rows: 6, value: form.description, onChange: set('description'), placeholder: '输入正确的关系描述' }),
          ],
          El('div', { className: 'kb-form-row', style: { marginTop: 14, marginBottom: 0 } },
            El('span', { className: 'kb-spacer' }),
            El('button', { className: 'kb-btn', onClick: props.onClose }, '取消'),
            El('button', { className: 'kb-btn primary', disabled: !filled, onClick: () => props.onSubmit(payload, file) }, '保存并执行'))))
    }

    function DiagnosisPane() {
      const [data, setData] = React.useState(null)
      const [err, setErr] = React.useState('')
      const [editing, setEditing] = React.useState(null)
      const [pFilter, setPFilter] = React.useState('')
      function load() {
        return apiGet('/kb/diagnoses?limit=20').then((d) => { setData(d); setErr('') }).catch((e) => setErr(e.message))
      }
      usePoll(load, 5000)
      const diagnoses = data && Array.isArray(data.diagnoses) ? data.diagnoses : []
      function decide(id, action, payload, file) {
        const path = '/kb/diagnoses/proposals/' + encodeURIComponent(id) + '/' + action
        // 上传文档模式：文件走原始字节体 + 查询参数；其余走 JSON payload
        const req = payload && payload.via === 'upload' && file
          ? apiUpload(path, { mode: 'file', filename: file.name, title: file.name, topic: payload.topic || '未分类' }, file)
          : apiPost(path, payload ? { payload: payload } : {})
        req.then(() => { setErr(''); setEditing(null); load() })
          .catch((e) => { setErr(e.message); load() })
      }
      function submitVerdict(id, verdict) {
        apiPost('/kb/diagnoses/proposals/' + encodeURIComponent(id) + '/verify', { verdict: verdict })
          .then(() => { setErr(''); load() })
          .catch((e) => setErr(e.message))
      }
      // 全量显示（含已拒绝/已完成的历史提案），筛选只影响视图；决策按钮按各自状态分支出现
      const all = diagnoses.flatMap((d) => (d.proposals || []).map((p) => ({ ...p, diagnosis_id: d.diagnosis_id, mode: d.mode, diag_created_at: d.created_at })))
      const proposals = pFilter ? all.filter((p) => p.status === pFilter) : all
      const decidable = (p) => p.status === 'awaiting_approval' || p.status === 'failed' || p.status === 'needs_manual_review'
      const advisory = (p) => ['reindex_document', 'adjust_chunking', 'adjust_retrieval', 'prompt_fix', 'manual_review', 'review_document', 'review_required'].includes(p.action)
      // 分组：recommend 标记的案例为「推荐处理」，其余为「全部候选」（规则快速诊断无标记，全部进候选）
      const recommended = proposals.filter((p) => p.recommend && (p.status === 'awaiting_approval' || p.status === 'needs_manual_review'))
      const recommendedIds = new Set(recommended.map((p) => p.proposal_id))
      const rest = proposals.filter((p) => !recommendedIds.has(p.proposal_id))

      function ProposalCard(p) {
        const verification = p.verification || null
        const userVerdict = verification && verification.user_verdict ? verification.user_verdict : null
        // 建议类动作的具体建议（模型经 payload.advice 分条提交，人工处置的依据）
        const adviceList = p.payload && p.payload.advice
          ? (Array.isArray(p.payload.advice) ? p.payload.advice : [p.payload.advice]).filter((a) => typeof a === 'string' && a.trim())
          : []
        // 关联反馈的问题原文（agent 证据 type=feedback；rules 证据无 type 均来自反馈）
        const srcQueries = [...new Set((p.evidence || []).map((e) => e && e.query ? String(e.query).trim() : '').filter(Boolean))]
        return El('div', { className: 'kb-card', key: p.proposal_id },
          El(CardHead, { title: p.title || '知识库优化提案', icon: 'bulb', right: El('span', { style: { display: 'inline-flex', gap: 6, alignItems: 'center' } },
            p.recommend ? El('span', { className: 'kb-chip accent' }, '推荐') : null,
            El('span', { className: 'kb-chip ' + diagStatusTone(p.status) }, DIAG_STATUS_LABEL[p.status] || p.status)) }),
          srcQueries.length ? El('div', { className: 'kb-hint', style: { marginBottom: 6 }, title: srcQueries.join('；') },
            '针对问题：' + srcQueries.slice(0, 2).join('；') + (srcQueries.length > 2 ? '（等 ' + srcQueries.length + ' 个问题）' : '')) : null,
          p.root_cause ? El('div', { style: { marginBottom: 8 } }, '根因：' + p.root_cause) : El('div', { style: { marginBottom: 8 } }, p.summary || '–'),
          El('div', { className: 'kb-hint' },
            (p.mode ? '来源：' + (p.mode === 'agent' ? '智能诊断' : '快速诊断') + ' · ' : '')
            + (p.cause_layer ? '问题层：' + causeLayerLabel(p.cause_layer) + ' · ' : '')
            + '类型：' + issueTypeLabel(p.issue_type)
            + ' · 建议：' + (DIAG_ACTION_LABEL[p.action] || p.action)
            + ' · 风险：' + (RISK_LABEL[p.risk] || '未知')
            + (p.confidence !== null && p.confidence !== undefined ? ' · 判断把握：' + confidenceLabel(p.confidence) : '')),
          adviceList.length ? El('div', { style: { marginTop: 8 } },
            El('div', { className: 'kb-hint', style: { marginBottom: 2 } }, '处置建议（需要你人工执行，本提案不会自动修改知识库）：'),
            El('ol', { style: { margin: 0, paddingLeft: 20, fontSize: '12.5px', lineHeight: 1.6, color: 'var(--dsw-alias-label-primary)' } },
              adviceList.map((a, i) => El('li', { key: i }, a.trim())))) : null,
          p.missing_information && p.missing_information.length ? El('div', { className: 'kb-hint', style: { marginTop: 6 } }, '待补充信息：' + p.missing_information.join('；')) : null,
          p.status === 'needs_manual_review' && p.validation && p.validation.errors && p.validation.errors.length
            ? El('div', { className: 'kb-err', style: { marginTop: 8 } }, '校验未通过：' + p.validation.errors.join('；')) : null,
          p.evidence && p.evidence.length ? El('div', { className: 'kb-hint', style: { marginTop: 8 } }, '证据：' + (p.evidence[0].note || p.evidence[0].query || '已关联反馈') + (p.evidence.length > 1 ? ' 等 ' + p.evidence.length + ' 条' : '')) : null,
          p.status === 'failed' && p.error ? El('div', { className: 'kb-err', style: { marginTop: 8 } }, '失败原因：' + p.error) : null,
          p.status === 'rejected' && p.rejected_reason ? El('div', { className: 'kb-hint', style: { marginTop: 8 } }, '拒绝原因：' + p.rejected_reason) : null,
          p.status === 'needs_manual_review' ? El('div', { className: 'kb-form-row', style: { marginTop: 12, marginBottom: 0 } },
            El('span', { className: 'kb-hint', style: { flex: 1 } }, advisory(p)
              ? '本提案不会自动修改知识库：请按上面的处置建议逐条人工执行（改文档到「文档管理」页操作），全部处理完后点「不采用」关闭此提案。'
              : '证据或参数不完整，请人工核对后处置。'),
            El('button', { className: 'kb-btn danger', onClick: () => decide(p.proposal_id, 'reject') }, '不采用')) : null,
          decidable(p) && p.status !== 'needs_manual_review' && ['add_text', 'edit_entity', 'edit_relation'].includes(p.action) ? El('div', { className: 'kb-form-row', style: { marginTop: 12, marginBottom: 0 } },
            payloadReady(p)
              ? El('button', { className: 'kb-btn primary', onClick: () => decide(p.proposal_id, 'approve') }, '批准并执行')
              : El('span', { className: 'kb-hint' }, '需要补充资料后才能执行'),
            El('button', { className: 'kb-btn ghost', onClick: () => setEditing(p) }, '编辑后执行'),
            El('button', { className: 'kb-btn danger', onClick: () => decide(p.proposal_id, 'reject') }, '拒绝')) : null,
          decidable(p) && p.status !== 'needs_manual_review' && !['add_text', 'edit_entity', 'edit_relation'].includes(p.action) ? El('div', { className: 'kb-hint', style: { marginTop: 10 } }, '该问题需要人工核对文档，暂不支持在线执行；确认无误后可拒绝此提案。') : null,
          (p.status === 'executing' || p.status === 'succeeded') && verification ? El('div', { className: 'kb-hint', style: { marginTop: 8 } },
            '复核：引用' + (verification.refs_changed ? '已变化' : '未变化') + ' · 回答' + (verification.answer_changed ? '已变化' : '未变化')) : null,
          userVerdict ? El('div', { className: 'kb-hint', style: { marginTop: 6 } }, '你的判定：' + verdictLabel(userVerdict.verdict) + (userVerdict.note ? '（' + userVerdict.note + '）' : '')) : null,
          (p.status === 'executing' || p.status === 'succeeded') ? El('div', { className: 'kb-form-row', style: { marginTop: 10, marginBottom: 0, flexWrap: 'wrap', gap: 6 } },
            El('button', { className: 'kb-btn', onClick: () => apiPost('/kb/diagnoses/proposals/' + encodeURIComponent(p.proposal_id) + '/verify', {}).then(() => load()).catch((e) => setErr(e.message)) }, '复核原问题'),
            !userVerdict ? [
              El('button', { key: 'v1', className: 'kb-btn ghost', onClick: () => submitVerdict(p.proposal_id, 'resolved') }, '已解决'),
              El('button', { key: 'v2', className: 'kb-btn ghost', onClick: () => submitVerdict(p.proposal_id, 'partial') }, '部分解决'),
              El('button', { key: 'v3', className: 'kb-btn ghost', onClick: () => submitVerdict(p.proposal_id, 'unresolved') }, '仍有问题'),
              El('button', { key: 'v4', className: 'kb-btn ghost', onClick: () => submitVerdict(p.proposal_id, 'uncertain') }, '无法判断'),
            ] : null) : null)
      }

      return El('div', { className: 'kb-stack' },
        El(ErrorBox, { text: err }),
        all.length ? El('div', { className: 'kb-form-row' },
          El('span', { className: 'kb-hint' }, '共 ', El('b', null, all.length), ' 张提案'),
          El('select', { className: 'kb-select', style: { width: 'auto' }, value: pFilter, onChange: (e) => setPFilter(e.target.value) },
            El('option', { value: '' }, '全部状态'),
            El('option', { value: 'awaiting_approval' }, '待你确认'),
            El('option', { value: 'needs_manual_review' }, '需人工核对'),
            El('option', { value: 'executing' }, '执行中'),
            El('option', { value: 'succeeded' }, '已完成'),
            El('option', { value: 'failed' }, '执行失败'),
            El('option', { value: 'rejected' }, '已拒绝'))) : null,
        proposals.length ? [
          recommended.length ? [El('div', { key: 'rec-h', className: 'kb-hint', style: { margin: '2px 0 -4px' } }, '推荐处理（高频且证据充分）'), ...recommended.map(ProposalCard)] : null,
          rest.length ? [recommended.length ? El('div', { key: 'rest-h', className: 'kb-hint', style: { margin: '2px 0 -4px' } }, '全部候选') : null, ...rest.map(ProposalCard)] : null,
        ] : El('div', { className: 'kb-card' }, El(Empty, null, all.length
          ? '当前筛选下没有提案，切换「全部状态」查看历史。'
          : '暂无诊断提案。智能诊断：在 AI 助手对话中说“诊断知识库负反馈”；快速诊断：在“反馈与诊断”页点击开始诊断。')),
        // 条件挂载：editing 有值才挂载弹窗，保证 useState 初始化器在提案就位后运行
        // （若常驻挂载，初始化器只在 editing=null 的首渲染执行一次，form 恒为空对象 → 打开即崩）
        editing ? El(ProposalEditModal, {
          proposal: editing,
          onClose: () => setEditing(null),
          onSubmit: (payload, file) => decide(editing.proposal_id, 'approve', payload, file),
        }) : null)
    }

    // ---- 知识库健康体检 ----

    /**
     * 健康体检子页：一键触发 kb_analyze 同款四类健康分析（源冲突 / 失败文档 /
     * 重复实体候选 / 检索缺口三分类），只读不修改知识库；结果落盘并展示明细。
     * 轮询 /kb/analysis/status 跟进异步体检进度。
     */
    function HealthPane(props) {
      const [data, setData] = React.useState(null)
      const [err, setErr] = React.useState('')
      const [starting, setStarting] = React.useState(false)
      const go = props.go || function () {}
      usePoll(() => apiGet('/kb/analysis/status').then((d) => { setData(d); setErr('') }).catch((e) => setErr(e.message)), 3000)

      function runNow() {
        if (starting) return
        const run = data && data.run ? data.run : null
        if (run && run.running) return
        setStarting(true)
        apiPost('/kb/analysis/run', { gap_max_probes: 8 }).then(() => setStarting(false)).catch((e) => { setStarting(false); setErr(e.message) })
      }

      const run = data && data.run ? data.run : null
      const running = !!(run && run.running)
      const latest = data && data.latest ? data.latest : null
      const history = data && Array.isArray(data.history) ? data.history : []
      const sections = latest && latest.sections ? latest.sections : {}
      const conflicts = sections.source_conflicts || null
      const failedDocs = sections.failed_docs || null
      const dupEntities = sections.dup_entities || null
      const gaps = sections.gaps || null
      const failedList = failedDocs && Array.isArray(failedDocs.failed) ? failedDocs.failed : []
      const conflictItems = conflicts && Array.isArray(conflicts.items) ? conflicts.items : []
      const dupItems = dupEntities && Array.isArray(dupEntities.items) ? dupEntities.items : []
      const gapItems = gaps && Array.isArray(gaps.items) ? gaps.items : []

      return El('div', { className: 'kb-stack' },
        El('div', { className: 'kb-card' },
          El(CardHead, {
            title: '知识库健康体检', icon: 'shield',
            tip: '扫描四类健康问题：源冲突（同一文档多版本并存）、失败文档、重复实体候选、检索缺口（零命中查询重探分诊）。全程只读，不修改知识库。',
          }),
          El('div', { className: 'kb-form-row' },
            El('button', { className: 'kb-btn primary big', disabled: running || starting, onClick: runNow },
              icon('refresh', 13), running ? '体检中…' : (starting ? '启动中…' : '开始体检')),
            El('span', { className: 'kb-hint' }, '零命中查询逐条重探约需 10-30 秒，完成后自动刷新'),
            El('span', { className: 'kb-spacer' }),
            latest ? El('span', { className: 'kb-hint' }, '上次体检 ' + fmtTs(latest.generated_at)) : null),
          run && run.error ? El('div', { className: 'kb-err', style: { marginTop: 8 } }, '体检失败：' + run.error) : null,
          El(ErrorBox, { text: err }),
          latest ? El('div', { className: 'kb-metrics-grid', style: { marginTop: 12 } },
            El('div', { className: 'kb-metric-card' }, El('div', { className: 'kb-metric-label' }, '源冲突'), El('div', { className: 'kb-metric-num' }, conflicts ? conflicts.total : '–'), El('div', { className: 'kb-metric-sub' }, '同一来源多版本并存')),
            El('div', { className: 'kb-metric-card' }, El('div', { className: 'kb-metric-label' }, '失败文档'), El('div', { className: 'kb-metric-num' }, failedDocs ? failedList.length : '–'), El('div', { className: 'kb-metric-sub' }, '解析或入库失败')),
            El('div', { className: 'kb-metric-card' }, El('div', { className: 'kb-metric-label' }, '重复实体候选'), El('div', { className: 'kb-metric-num' }, dupEntities ? (dupEntities.candidates ?? '–') : '–'), El('div', { className: 'kb-metric-sub' }, dupEntities && dupEntities.configured ? '按名称变体聚类' : '未配置 KB_RAG_STORAGE，跳过')),
            El('div', { className: 'kb-metric-card' }, El('div', { className: 'kb-metric-label' }, '零命中查询'), El('div', { className: 'kb-metric-num' }, gaps ? gaps.zero_ref_total : '–'), El('div', { className: 'kb-metric-sub' }, gaps ? ('重探 ' + gaps.probed + ' 条 · ' + JSON.stringify(gaps.by_class)) : '')),
            El('div', { className: 'kb-metric-card' }, El('div', { className: 'kb-metric-label' }, '引擎抽取状态'), El('div', { className: 'kb-metric-num', style: { fontSize: 16 } }, failedDocs && failedDocs.engine_status_counts ? (failedDocs.engine_status_counts.processed ?? '–') : '–'), El('div', { className: 'kb-metric-sub' }, '引擎已处理文档数')))
            : El(Empty, null, '还没有体检记录，点击「开始体检」生成第一份报告。')),

        latest ? El('div', { className: 'kb-card' },
          El(CardHead, { title: '体检明细', icon: 'list', tip: '四类问题的明细清单；失败文档到「文档管理」重试，重复实体到「实体检索」合并。' }),

          conflictItems.length ? [El('div', { key: 'c-h', className: 'kb-eyebrow' }, '源冲突（' + conflicts.total + '）'),
            El('div', { key: 'c-l', className: 'kb-hint' }, conflictItems.slice(0, 8).map((c) => c.source + '（候选 ' + (c.candidates ?? '≥2') + '）').join('、'))] : El('div', { className: 'kb-hint' }, '源冲突：无'),

          failedList.length ? [El('div', { key: 'f-h', className: 'kb-eyebrow', style: { marginTop: 10 } }, '失败文档（' + failedList.length + '）'),
            failedList.slice(0, 5).map(function (d, i) {
              return El('div', { key: 'f' + i, className: 'kb-hint', title: d.reason || '' }, '· ' + (d.title || d.id) + (d.reason ? '（' + String(d.reason).slice(0, 60) + '）' : ''))
            }),
            El('div', { key: 'f-go', style: { marginTop: 4 } }, El('button', { className: 'kb-btn linky', onClick: () => go('docs', 'docs') }, '到文档管理处理 →'))]
            : El('div', { className: 'kb-hint', style: { marginTop: 10 } }, '失败文档：无'),

          dupItems.length ? [El('div', { key: 'd-h', className: 'kb-eyebrow', style: { marginTop: 10 } }, '重复实体候选（' + dupEntities.candidates + ' 组）'),
            El('div', { key: 'd-l', className: 'kb-rows' }, dupItems.slice(0, 6).map(function (d, i) {
              return El('div', { key: 'd' + i, className: 'kb-row', style: { padding: '6px 10px' }, title: d.names.join(' ≈ ') },
                El('span', { className: 't' }, d.names.slice(0, 3).join(' ≈ ') + (d.names.length > 3 ? ' 等 ' + d.count + ' 个' : '')))
            })),
            El('div', { key: 'd-go', style: { marginTop: 4 } }, El('button', { className: 'kb-btn linky', onClick: () => go('docs', 'graph') }, '到实体检索合并处理 →'))]
            : El('div', { className: 'kb-hint', style: { marginTop: 10 } }, '重复实体候选：无' + (dupEntities && !dupEntities.configured ? '（' + dupEntities.note + '）' : '')),

          gapItems.length ? [El('div', { key: 'g-h', className: 'kb-eyebrow', style: { marginTop: 10 } }, '检索缺口（重探 ' + gaps.probed + ' 条）'),
            El('table', { key: 'g-t', className: 'kb-table', style: { marginTop: 4 } },
              El('thead', null, El('tr', null, El('th', null, '类别'), El('th', null, '查询'), El('th', null, '处置建议'))),
              El('tbody', null, gapItems.map(function (g, i) {
                return El('tr', { key: 'g' + i },
                  El('td', null, El('span', { className: 'kb-chip', title: g.class }, GAP_LABEL[g.class] || g.class)),
                  El('td', { style: { fontSize: 12 }, title: g.query }, (g.query || '').slice(0, 36)),
                  El('td', { style: { fontSize: 12 } }, g.suggested || ''))
              })))]
            : El('div', { className: 'kb-hint', style: { marginTop: 10 } }, '检索缺口：无零命中查询'),

          history.length > 1 ? El('div', { key: 'hist', style: { marginTop: 12, display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' } },
            El('span', { className: 'kb-hint' }, '历史体检：'),
            history.slice(1).map(function (h, i) {
              return El('span', { key: 'h' + i, className: 'kb-chip' }, fmtTs(h.generated_at).slice(5, 16))
            })) : null) : null)
    }

    function ExecutionPane(props) {
      const [data, setData] = React.useState(null)
      const [eFilter, setEFilter] = React.useState('')
      const setSub = props.onSubChange || function () {}
      usePoll(() => apiGet('/kb/diagnoses?limit=20').then(setData).catch(() => {}), 5000)
      // 全量显示（含已拒绝/待确认——完整历史）；每行带针对问题与根因，与修复提案页一一对应
      const rows = data && Array.isArray(data.diagnoses) ? data.diagnoses.flatMap((d) => (d.proposals || []).map((p) => ({ ...p, diagnosis_id: d.diagnosis_id, mode: d.mode, diag_created_at: d.created_at }))) : []
      const shown = eFilter ? rows.filter((p) => p.status === eFilter) : rows
      const filterSelect = rows.length ? El('span', { style: { display: 'inline-flex', gap: 8, alignItems: 'center' } },
        El('span', { className: 'kb-hint' }, '共 ' + rows.length + ' 条'),
        El('select', { className: 'kb-select', style: { width: 'auto' }, value: eFilter, onChange: (e) => setEFilter(e.target.value) },
          El('option', { value: '' }, '全部状态'),
          El('option', { value: 'awaiting_approval' }, '待你确认'),
          El('option', { value: 'needs_manual_review' }, '需人工核对'),
          El('option', { value: 'executing' }, '执行中'),
          El('option', { value: 'succeeded' }, '已完成'),
          El('option', { value: 'failed' }, '执行失败'),
          El('option', { value: 'rejected' }, '已拒绝'))) : null
      return El('div', { className: 'kb-card' }, El(CardHead, { title: '执行记录', icon: 'clock', tip: '全部提案的处理状态，与「修复提案」页一一对应；点击「查看提案详情」可跳转。', right: filterSelect }), shown.length ? El('div', { className: 'kb-rows' }, shown.map((p) => {
        const srcQueries = [...new Set((p.evidence || []).map((e) => e && e.query ? String(e.query).trim() : '').filter(Boolean))]
        return El('div', { key: p.proposal_id, className: 'kb-row' },
          El('div', { className: 'fb-head' },
            El('span', { className: 'kb-chip' }, DIAG_ACTION_LABEL[p.action] || '修复'),
            El('span', { className: 't', title: p.title || '' }, p.title || '知识库优化提案'),
            p.verification && p.verification.user_verdict ? El('span', { className: 'kb-chip ' + (p.verification.user_verdict.verdict === 'resolved' ? 'ok' : p.verification.user_verdict.verdict === 'unresolved' ? 'failed' : '') }, verdictLabel(p.verification.user_verdict.verdict)) : null,
            El('span', { className: 'kb-chip ' + diagStatusTone(p.status) }, DIAG_STATUS_LABEL[p.status] || p.status),
            El('span', { className: 'ts' }, fmtTs(p.updated_at || p.diag_created_at || ''))),
          srcQueries.length ? El('div', { className: 'fb-sub', title: srcQueries.join('；') },
            '针对问题：' + srcQueries.slice(0, 2).join('；') + (srcQueries.length > 2 ? '（等 ' + srcQueries.length + ' 个问题）' : '')) : null,
          p.root_cause ? El('div', { className: 'fb-sub', title: p.root_cause }, '根因：' + p.root_cause) : null,
          El('div', { style: { marginTop: 4 } },
            El('button', { className: 'kb-btn linky', onClick: () => setSub('proposals') }, '查看提案详情 →')))
      })) : El(Empty, null, rows.length ? '当前筛选下没有记录，切换「全部状态」查看。' : '暂无执行记录'))
    }

    function AutoTab(props) {
      const sub = props.sub || 'overview'
      const setSub = props.onSubChange || function () {}
      const pills = [
        ['overview', '诊断总览'],
        ['feedback', '反馈与诊断'],
        ['proposals', '修复提案'],
        ['execution', '执行记录'],
      ]
      return El('div', { className: 'kb-stack' },
        El('div', { className: 'kb-seg' },
          pills.map(([id, label]) => El('button', {
            key: id, className: sub === id ? 'active' : '', onClick: () => setSub(id),
          }, label))),
        sub === 'overview' ? El(OverviewPane, { setSub: setSub, openView: props.openView })
          : sub === 'feedback' ? El(FeedbackPane, { onSubChange: setSub })
          : sub === 'proposals' ? El(DiagnosisPane)
          : sub === 'execution' ? El(ExecutionPane, { onSubChange: setSub })
            : El(DiagnosisPane))
    }

    // ---- 操作审计 ----

    function AuditPane() {
      const [items, setItems] = React.useState(null)
      const [group, setGroup] = React.useState('')
      const [page, setPage] = React.useState(1)
      const [open, setOpen] = React.useState(null)
      const [err, setErr] = React.useState('')

      React.useEffect(function () {
        let alive = true
        const qs = new URLSearchParams({ page: String(page), page_size: '50' })
        const filter = AUDIT_FILTERS.find((f) => f.id === group)
        if (filter && filter.actions) qs.set('actions', filter.actions.join(','))
        apiGet('/kb/audit?' + qs.toString())
          .then((d) => { if (alive) setItems(d) })
          .catch((e) => { if (alive) setErr(e.message) })
        return function () { alive = false }
      }, [group, page])

      const total = items ? items.total : 0
      const pages = Math.max(1, Math.ceil(total / 50))
      const rows = items && items.items ? items.items : []

      return El('div', { className: 'kb-card' },
        El(CardHead, {
          title: '操作审计', icon: 'list',
          tip: '知识库的每一次变动都记录在此：谁、在什么时候、做了什么。点击任意一条可查看技术编号等细节。',
        }),
        El('div', { className: 'kb-seg' },
          AUDIT_FILTERS.map((f) => El('button', {
            key: f.id, className: group === f.id ? 'active' : '',
            onClick: () => { setGroup(f.id); setPage(1); setOpen(null) },
          }, f.label))),
        El('div', { className: 'kb-form-row' },
          El('span', { className: 'kb-hint' }, '共 ' + total + ' 条记录'),
          El('span', { className: 'kb-spacer' }),
          El('button', { className: 'kb-btn', disabled: page <= 1, onClick: () => { setPage((p) => p - 1); setOpen(null) } }, '‹'),
          El('span', { className: 'kb-hint' }, page + ' / ' + pages),
          El('button', { className: 'kb-btn', disabled: page >= pages, onClick: () => { setPage((p) => p + 1); setOpen(null) } }, '›')),
        El(ErrorBox, { text: err }),
        El('table', { className: 'kb-table' },
          El('thead', null,
            El('tr', null,
              El('th', { style: { width: 110 } }, '时间'),
              El('th', null, '记录'))),
          El('tbody', null,
            rows.length === 0 ? El('tr', null, El('td', { colSpan: 2 }, El(Empty, null, '暂无记录'))) :
              foldAuditRows(rows).map(function (entry, i) {
                const key = entry.kind === 'group' ? 'grp:' + i + ':' + entry.items[0].ts : 'one:' + i
                const isOpen = open === key
                const ts = entry.kind === 'group' ? entry.items[0].ts : entry.item.ts
                let iconName, tone, actor, line, note, noteTone, tech
                if (entry.kind === 'group') {
                  const g = entry.items
                  const first = describeAudit(g[0])
                  const totalDocs = g.reduce((n, x) => n + ((x.detail && x.detail.count) || 0), 0)
                  iconName = first.icon; tone = ''; actor = first.actor
                  line = '登记引擎中已有文档 ' + totalDocs + ' 篇'
                    + (g.length > 1 ? '（同一次扫描分 ' + g.length + ' 批登记）' : '')
                  note = first.note; noteTone = ''
                  tech = [
                    El('div', { key: 'a', className: 'kb-tech-row' }, El('b', null, '操作者：'), El('code', null, String(g[0].actor || '–'))),
                    El('div', { key: 't', className: 'kb-tech-row' }, El('b', null, '操作类型：'), El('code', null, 'registry_adopted × ' + g.length)),
                    El('div', { key: 'b' }, El('b', null, '批次明细：'), El('pre', { className: 'kb-audit-json' },
                      JSON.stringify(g.map((x) => ({ ts: x.ts, target: x.target, detail: x.detail })), null, 2))),
                  ]
                } else {
                  const a = entry.item
                  const inf = describeAudit(a)
                  iconName = inf.icon; tone = inf.tone; actor = inf.actor
                  line = inf.line; note = inf.note; noteTone = inf.noteTone
                  tech = [
                    El('div', { key: 'a', className: 'kb-tech-row' }, El('b', null, '操作者：'), El('code', null, String(a.actor || '–'))),
                    El('div', { key: 't', className: 'kb-tech-row' }, El('b', null, '操作类型：'), El('code', null, String(a.action || '–'))),
                    El('div', { key: 'o', className: 'kb-tech-row' }, El('b', null, '对象编号：'), El('code', null, String(a.target || '–'))),
                    El('div', { key: 'd' }, El('b', null, '明细：'), El('pre', { className: 'kb-audit-json' }, JSON.stringify(a.detail || {}, null, 2))),
                  ]
                }
                const head = El('tr', {
                  key, className: 'kb-audit-row',
                  onClick: () => setOpen(isOpen ? null : key),
                },
                  El('td', { className: 'kb-audit-time', title: fmtTs(ts) }, fmtAuditTime(ts)),
                  El('td', null,
                    El('div', { className: 'kb-audit-main' },
                      icon(iconName, 14),
                      El('div', { className: 'kb-audit-body' },
                        El('div', { className: 'kb-audit-line' },
                          El('span', { className: 'kb-chip' + (tone ? ' ' + tone : '') }, actor),
                          El('span', { className: 'kb-audit-text' }, line),
                          El('span', { className: 'kb-audit-more' }, isOpen ? '收起 ▴' : '详情 ▾')),
                        note
                          ? El('div', { className: 'kb-audit-note' + (noteTone ? ' ' + noteTone : '') }, note)
                          : null))))
                if (!isOpen) return [head]
                const detail = El('tr', { key: key + ':tech' },
                  El('td', null),
                  El('td', null, El('div', { className: 'kb-audit-tech' }, tech)))
                return [head, detail]
              }))))
    }

    // ---------------------------------------------------------------- 使用说明（弹窗）

    function KbHelpModal(props) {
      const [data, setData] = React.useState(null)
      const [sel, setSel] = React.useState('manual')
      const [err, setErr] = React.useState('')

      React.useEffect(function () {
        let alive = true
        apiGet('/kb/docs')
          .then(function (d) { if (alive) setData(d) })
          .catch(function (e) { if (alive) setErr(e.message) })
        return function () { alive = false }
      }, [])

      React.useEffect(function () {
        if (!props.open) return
        const onKey = (e) => { if (e.key === 'Escape') props.onClose() }
        document.addEventListener('keydown', onKey)
        return function () { document.removeEventListener('keydown', onKey) }
      }, [props.open])

      if (!props.open) return null

      const docs = data && Array.isArray(data.docs) ? data.docs : []
      const current = docs.find(function (d) { return d.id === sel }) || docs[0] || null

      return El('div', {
        className: 'kb-modal-backdrop',
        onClick: (e) => { if (e.target === e.currentTarget) props.onClose() },
      },
        El('div', { className: 'kb-modal' },
          El('h4', null,
            El('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 6 } }, icon('help', 15), '使用说明'),
            El('button', { className: 'kb-btn linky', onClick: props.onClose }, '关闭')),
          El(ErrorBox, { text: err }),
          El('div', { className: 'kb-seg' },
            docs.map((d) => El('button', {
              key: d.id, className: current && d.id === current.id ? 'active' : '', onClick: () => setSel(d.id),
            }, d.title))),
          current
            ? (current.content === null
                ? El('div', { className: 'kb-err' }, '文档内容缺失：' + current.file)
                : El('div', { className: 'kb-md', style: { maxHeight: '56vh', overflowY: 'auto', padding: '4px 2px' } }, mdToNodes(current.content)))
            : El(Empty, null, '加载中…')))
    }

    // ---------------------------------------------------------------- 工作台视图

    /**
     * 消费一次定向到本视图的焦点请求：宿主 openView 会切换一级 tab 并投递
     * { view, focus }，本视图借它落到具体子页后立即确认，避免重挂载时重复消费。
     */
    function useViewFocus(props, selfId, onFocus) {
      const vr = props && props.viewRequest
      React.useEffect(function () {
        if (!vr || vr.view !== selfId) return
        if (vr.focus) onFocus(vr.focus)
        if (props && props.completeViewRequest) props.completeViewRequest()
      }, [vr])
    }

    /** 工作台外壳：标题行（标题 + 引擎状态 + 使用说明）。一级导航由宿主 tab 栏承担，不再有内部 tab。 */
    function KbShell(props) {
      const [helpOpen, setHelpOpen] = React.useState(false)
      const [health, setHealth] = React.useState(null)

      usePoll(() => apiGet('/kb/health').then((d) => setHealth(d)).catch((e) => setHealth({ ok: false, error: e.message })), 30000)

      return El('div', { className: 'kb-root' },
        El('div', { className: 'kb-topbar' },
          El('span', { className: 'kb-title' }, props.title),
          El('span', { className: 'kb-dot ' + (health && health.ok ? 'ok' : health && health.ok === false ? 'bad' : 'warn'), title: health && health.ok ? '引擎正常' : '引擎异常' }),
          El('span', { className: 'kb-hint' }, health && health.ok
            ? (health.stats ? health.stats.documents_total : '–') + ' 篇文档'
            : (health && health.ok === false ? '引擎不可达' : '连接中…')),
          El('span', { className: 'kb-spacer' }),
          El('button', { className: 'kb-btn', onClick: () => setHelpOpen(true) }, icon('help', 13), '使用说明')),
        El(KbHelpModal, { open: helpOpen, onClose: () => setHelpOpen(false) }),
        El('div', { className: 'kb-content' }, props.children))
    }

    /** 总览视图：知识库运营总览（资产/检索信号/变更/健康）。 */
    function KbHomeView(props) {
      const openView = props && props.openView
      function go(tabId, subId) {
        if (openView) openView('knowledge-' + tabId, subId || '')
      }
      return El(KbShell, { title: '知识库运营' }, El(OpsPane, { go: go }))
    }

    /** 文档与图谱管理视图：子页 = 文档列表 / 添加文档 / 图谱管理。 */
    function KbDocsView(props) {
      const [sub, setSub] = React.useState('docs')
      useViewFocus(props, 'knowledge-docs', setSub)
      return El(KbShell, { title: '文档与图谱管理' }, El(DocsTab, { sub: sub, onSubChange: setSub }))
    }

    /** 反馈诊断视图：子页 = 诊断总览 / 反馈与诊断 / 修复提案 / 执行记录。 */
    function KbAutoView(props) {
      const [sub, setSub] = React.useState('overview')
      useViewFocus(props, 'knowledge-auto', setSub)
      return El(KbShell, { title: '反馈与诊断' }, El(AutoTab, { sub: sub, onSubChange: setSub, openView: props && props.openView }))
    }

    /** 健康体检视图：一键触发四类健康分析（只读），独立一级入口。 */
    function KbHealthView(props) {
      const openView = props && props.openView
      function go(tabId, subId) {
        if (openView) openView('knowledge-' + tabId, subId || '')
      }
      return El(KbShell, { title: '知识库健康体检' }, El(HealthPane, { go: go }))
    }

    // ---------------------------------------------------------------- 会话反哺

    /**
     * 从会话快照提取一条回答的对话上下文（用户问题 / 回答正文 / 知识库引用 / 查询 id）。
     * assistant-actions 槽位只携带 messageId/sessionId，正文需从聊天快照读取。
     * 节点形状对齐宿主 legacy 投影：user/assistant/tool-result 均为顶层记录，
     * 工具结果（kind 'tool-result'）由 'tool-call' 视图节点折叠而来。
     * 引用与查询 id 从 lightrag_query 工具卡文本解析，格式由本插件 output.render 约定
     * （「引用：a、b」行 + 「查询 id：q-xxx」行）。查询 id 取问答区间内第一次检索，
     * 用于服务端把反馈关联到 query_log 的检索快照。
     */
    function readChatContext(snapshot, messageId) {
      const empty = { query: '', answer: '', references: [], query_id: null }
      if (!snapshot || !snapshot.legacy || !Array.isArray(snapshot.legacy.nodes)) return empty
      let at = -1
      for (let i = 0; i < snapshot.legacy.nodes.length; i++) {
        const n = snapshot.legacy.nodes[i]
        if (n && n.kind === 'assistant' && n.messageId === messageId) { at = i; break }
      }
      if (at < 0) return empty
      const node = snapshot.legacy.nodes[at]
      const answer = (node.blocks || [])
        .filter((b) => b && b.kind === 'text').map((b) => b.text || '').join('')
      let query = ''
      let userSeq = 0
      for (let i = at - 1; i >= 0; i--) {
        const n = snapshot.legacy.nodes[i]
        if (n && n.kind === 'user') {
          query = (n.content || []).filter((b) => b && b.type === 'text').map((b) => b.text || '').join('')
          userSeq = n.seq || 0
          break
        }
      }
      const refs = []
      let queryId = null
      for (let i = 0; i < at; i++) {
        const n = snapshot.legacy.nodes[i]
        if (!n || n.kind !== 'tool-result' || !n.call) continue
        // lightrag_query（问答）与 lightrag_query_data（检索探测）的卡片都参与反馈关联
        if (n.call.name !== 'lightrag_query' && n.call.name !== 'lightrag_query_data') continue
        if (userSeq && (n.seq || 0) <= userSeq) continue
        for (const b of n.content || []) {
          if (!b || b.type !== 'text') continue
          for (const line of String(b.text || '').split('\n')) {
            const m = line.match(/^引用：(.+)$/)
            if (m) {
              for (const f of m[1].split('、')) {
                const file = f.trim()
                if (file && !refs.includes(file)) refs.push(file)
              }
            }
            const q = line.match(/^查询 id：(\S+)$/)
            if (q && !queryId) queryId = q[1].trim()
          }
        }
      }
      return { query, answer, references: refs.slice(0, 20), query_id: queryId }
    }

    function KbSaveAction(props) {
      const [open, setOpen] = React.useState(false)
      const [feedbackOpen, setFeedbackOpen] = React.useState(false)
      const [issueType, setIssueType] = React.useState('missing_content')
      const [feedbackNote, setFeedbackNote] = React.useState('')
      const [title, setTitle] = React.useState('')
      const [body, setBody] = React.useState('')
      const [topic, setTopic] = React.useState('未分类')
      const [state, setState] = React.useState('idle')
      const [err, setErr] = React.useState('')
      // 渲染期订阅聊天快照（框架 hook），提交反馈时从最近一次渲染的快照读对话上下文
      const chat = typeof props.useChat === 'function' ? props.useChat((s) => s) : null

      React.useEffect(function () {
        if (!open) return
        const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
        document.addEventListener('keydown', onKey)
        return function () { document.removeEventListener('keydown', onKey) }
      }, [open])

      if (state === 'done') {
        return El('button', { className: 'kb-save-done', title: '此回答已存入知识库' }, icon('check', 12), '已存入')
      }

      function submit() {
        if (!title.trim() || !body.trim()) { setErr('请填写标题和正文'); return }
        setState('saving')
        setErr('')
        apiPost('/kb/conversations', {
          session_id: props.sessionId || '',
          message_id: props.messageId || '',
          title: title.trim(),
          body: body.trim(),
          topic,
          kb: 'company',
        }).then(() => {
          setState('done')
        }).catch((e) => {
          setState('idle')
          setErr(e.message)
        })
      }

      function submitFeedback() {
        if (!feedbackNote.trim()) { setErr('请补充问题说明'); return }
        setState('saving'); setErr('')
        const chatInfo = readChatContext(chat, props.messageId)
        apiPost('/kb/feedback', {
          rating: 'negative',
          issue_type: issueType,
          note: feedbackNote.trim(),
          query_id: chatInfo.query_id || props.queryId || null,
          session_id: props.sessionId || null,
          message_id: props.messageId || null,
          query: chatInfo.query,
          answer: chatInfo.answer,
          references: chatInfo.references.map((f) => ({ file: f })),
        })
          .then(() => { setFeedbackOpen(false); setFeedbackNote(''); setState('idle') })
          .catch((e) => { setState('idle'); setErr(e.message) })
      }

      return El('div', { className: 'kb-save-wrap' },
        El('button', { className: 'kb-btn', onClick: () => setOpen(true) }, icon('plus', 12), '存入知识库'),
        El('button', { className: 'kb-btn', onClick: () => setFeedbackOpen(true) }, icon('message', 12), '反馈此回答'),
        open ? El('div', {
          className: 'kb-modal-backdrop',
          onClick: (e) => { if (e.target === e.currentTarget) setOpen(false) },
        },
          El('div', { className: 'kb-modal' },
            El('h4', null, '存入知识库'),
            El('p', { className: 'kb-hint', style: { margin: '0 0 12px' } }, '沉淀为知识库条目，供后续检索引用。'),
            El('div', { className: 'kb-form-row' },
              El('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '标题（必填）', value: title, onChange: (e) => setTitle(e.target.value) }),
              El('select', { className: 'kb-select', value: topic, onChange: (e) => setTopic(e.target.value) },
                TOPICS.map((t) => El('option', { key: t, value: t }, t)))),
            El('textarea', { className: 'kb-textarea', placeholder: '正文（必填；建议保留结论，略去过程性内容）', value: body, onChange: (e) => setBody(e.target.value) }),
            El('div', { className: 'kb-form-row', style: { marginTop: 10, marginBottom: 0 } },
              El('button', { className: 'kb-btn primary big', disabled: state === 'saving', onClick: submit }, state === 'saving' ? '保存中…' : '保存'),
              El('button', { className: 'kb-btn', onClick: () => setOpen(false) }, '取消'),
            err ? El('span', { className: 'kb-err' }, err) : null))) : null,
        feedbackOpen ? El('div', { className: 'kb-modal-backdrop', onClick: (e) => { if (e.target === e.currentTarget) setFeedbackOpen(false) } },
          El('div', { className: 'kb-modal' },
            El('h4', null, '反馈此回答'),
            El('p', { className: 'kb-hint' }, '反馈只用于诊断知识库问题，提交后不会自动修改内容。'),
            El('select', { className: 'kb-select', value: issueType, onChange: (e) => setIssueType(e.target.value) },
              [['missing_content', '内容缺失'], ['wrong_source', '引用不准确'], ['incomplete_citation', '引用不完整'], ['wrong_entity', '实体不准确'], ['wrong_relation', '关系不准确'], ['outdated_content', '内容过期'], ['answer_style', '回答方式']].map((x) => El('option', { key: x[0], value: x[0] }, x[1]))),
            El('textarea', { className: 'kb-textarea', placeholder: '请说明哪里有问题（必填）', value: feedbackNote, onChange: (e) => setFeedbackNote(e.target.value) }),
            El('div', { className: 'kb-form-row', style: { marginBottom: 0 } },
              El('button', { className: 'kb-btn primary big', disabled: state === 'saving', onClick: submitFeedback }, state === 'saving' ? '提交中…' : '提交反馈'),
              El('button', { className: 'kb-btn', onClick: () => setFeedbackOpen(false) }, '取消'),
              err ? El('span', { className: 'kb-err' }, err) : null))) : null)
    }

    // ---------------------------------------------------------------- 新对话 Hero 标志

    /**
     * 新对话页的品牌标志（conversation.hero.brand.mark 槽位，替代宿主默认鲸鱼）：
     * 知识图谱意象——中心知识核 + 卫星节点与连线，呼应"知核"品牌与图谱能力。
     * 单色 currentColor，接受宿主 owner props（size/className），保持原几何占位。
     */
    function KnowledgeMark(props) {
      const size = props && props.size ? props.size : 34
      return El('svg', {
        width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
        'aria-hidden': 'true', className: props && props.className ? props.className : undefined,
      },
        El('path', { d: 'M10.1 10.6 6.2 7.5M13.9 10.6 17.8 7.5M12 15.3v4.4', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' }),
        El('circle', { cx: '12', cy: '12', r: '3.4', fill: 'currentColor' }),
        El('circle', { cx: '4.6', cy: '6', r: '1.7', fill: 'currentColor' }),
        El('circle', { cx: '19.4', cy: '6', r: '1.7', fill: 'currentColor' }),
        El('circle', { cx: '12', cy: '21.2', r: '1.7', fill: 'currentColor' }))
    }

    // ---------------------------------------------------------------- 健康徽章

    function KbHealthBadge() {
      const [health, setHealth] = React.useState(null)
      usePoll(() => apiGet('/kb/health').then((d) => setHealth(d)).catch((e) => setHealth({ ok: false, error: e.message })), 30000)
      const dot = health === null ? 'warn' : health.ok ? 'ok' : 'bad'
      const label = health === null ? '知识库连接中…'
        : health.ok ? '知识库正常 · ' + (health.stats ? health.stats.documents_total : '–') + ' 篇文档'
        : '知识库不可达'
      return El('span', { className: 'kb-hl', title: label },
        El('span', { className: 'kb-dot ' + dot }),
        El('span', { style: { fontSize: 12, color: 'var(--dsw-alias-label-secondary)' } }, '知识库'))
    }

    // ---------------------------------------------------------------- apply

    function apply(ctx) {
      const slots = ctx.slots;
      const disposeStyles = injectStyles();
      ctx.effect(function () { return disposeStyles; });
      try { localStorage.removeItem('dsh.conversation.contentWidth'); } catch (e) { /* 只读存储环境忽略 */ }

      // 一级工作台视图：总览 / 文档与图谱管理 / 反馈与诊断 / 健康体检，
      // 与宿主「对话」「轨迹」同级（order 5-7，排在对话默认位之后、轨迹 10 之前）。
      // 跨视图跳转经 owner prop openView(view, focus) 携带目标子页。
      [
        ['knowledge-home', 5, '总览', KbHomeView],
        ['knowledge-docs', 6, '文档与图谱管理', KbDocsView],
        ['knowledge-auto', 7, '反馈与诊断', KbAutoView],
        ['knowledge-health', 8, '健康体检', KbHealthView],
      ].forEach(function (row) {
        const id = row[0], order = row[1], label = row[2], comp = row[3];
        slots.inject('conversation.view', function () {
          return slots.register(
            { name: 'conversation.view', id: id, order: order, label: label },
            function (props) { return El(comp, props || {}) },
          );
        });
      });

      slots.inject('conversation.chat.assistant-actions', function () {
        return slots.register(
          { name: 'conversation.chat.assistant-actions', id: 'kb-save', order: 20, label: '存入知识库' },
          function (props) { return El(KbSaveAction, props || {}); },
        );
      });

      slots.inject('conversation.session.header.utilities', function () {
        return slots.register(
          { name: 'conversation.session.header.utilities', id: 'kb-health', order: 10, label: '知识库健康' },
          function () { return El(KbHealthBadge); },
        );
      });

      // 新对话 Hero 品牌标志：知识图谱意象取代宿主默认鲸鱼（single 槽，注册即替换 fallback）
      slots.inject('conversation.hero.brand.mark', function () {
        return slots.register(
          { name: 'conversation.hero.brand.mark', id: 'kb-hero-mark', order: 0, label: '知核标志' },
          function (props) { return El(KnowledgeMark, props || {}); },
        );
      });

      // 左上角品牌名：以知识底座品牌「知核」取代外壳默认的本地构建标签
      // （sidebar.brand.name 为 single 槽，ownerProps 为空，占位者自带内容与宽度）
      slots.inject('sidebar.brand.name', function () {
        return slots.register(
          { name: 'sidebar.brand.name', id: 'kb-brand', order: 0, label: '知核' },
          function () {
            return El('span', { style: { fontSize: 14, fontWeight: 600, color: 'var(--dsw-alias-label-primary)', whiteSpace: 'nowrap' } }, '知核');
          },
        );
      });

      // 左上角品牌标记：移除外壳默认的鱼形标记（展开行与收起轨道共用此槽，占位者保留等宽空白）
      slots.inject('sidebar.brand.mark', function () {
        return slots.register(
          { name: 'sidebar.brand.mark', id: 'kb-brand-mark', order: 0, label: '知核品牌标记（隐藏默认鱼形）' },
          function (props) {
            const size = props && typeof props.size === 'number' ? props.size : 0;
            return El('span', { style: { display: 'inline-block', width: size + 'px', height: size + 'px' } });
          },
        );
      });
    }

    exports.apply = apply;
    exports.inject = ["slots"];
    return module.exports;
  }
});
