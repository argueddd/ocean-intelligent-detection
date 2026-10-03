import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowLeft,
  ArrowUp,
  Books,
  Brain,
  CaretDown,
  CaretRight,
  CheckCircle,
  CirclesThreePlus,
  ClockCounterClockwise,
  Copy,
  FileText,
  MagnifyingGlass,
  Plus,
  ShareNetwork,
  StackSimple,
  StopCircle,
  ThumbsDown,
  ThumbsUp,
  Trash,
  UserCircle,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import assistantHead from "../assets/assistant-head.webp";
import { agents } from "../data/agents";
import {
  loadSessions,
  upsertSession,
  removeSession,
  streamChat,
  fetchChatHistory,
  fetchPendingApprovals,
  decideApproval,
  submitFeedback,
  renameSession,
  IS_HARNESS_MODE,
} from "../lib/api";
import { Markdown } from "../lib/markdown";
import { ArtifactProvider } from "./ArtifactPreview";
import { groupToolSteps, parseToolArguments, toolLabel, toolProgress, toolResultDetail, toolResultState, toolStatusLabel } from "../lib/tool-progress";
import { ATTACHMENT_ACCEPT, attachmentPayload, attachmentSizeLabel, clipboardImageFile, readChatAttachment } from "../lib/chat-attachments";
import { canSendChat, interruptPendingSteps } from "../lib/chat-turn-state";

const ParticleStage = React.lazy(() => import("./ParticleStage"));

const activeAgent = IS_HARNESS_MODE ? {
  name: "水下数据分析智能体",
  short: "水下数据分析智能体",
  role: "水声数据体检与分析",
  shape: agents[0].shape,
  capabilities: [
    ["数据体检", "探查字段、样本轴与元数据，检查有限值、通道统计和实际覆盖范围。"],
    ["Skill 调用", "根据任务选择已接入的 Skill，读取规则并执行其中的分析方法。"],
    ["代码执行", "运行可复现的 Python 分析，保存参数、数值结果与图像证据。"],
    ["视觉核验", "读取波形、PSD 与时频图，将可见图像特征与数值结果对照。"],
  ],
} : agents[0];

/* ---------------------------------------------------------------- 工具链路辅助 */

/** tool/result 的 message.content 里取纯文本；文本在 tool-result 块的内层 content。 */
function resultText(event) {
  const blocks = event?.message?.content;
  if (!Array.isArray(blocks)) return "";
  const out = [];
  for (const b of blocks) {
    if (!b) continue;
    if (b.type === "text" && typeof b.text === "string") {
      out.push(b.text);
      continue;
    }
    if (b.type === "tool-result" && Array.isArray(b.content)) {
      for (const ib of b.content) {
        if (ib && ib.type === "text" && typeof ib.text === "string") out.push(ib.text);
      }
    }
  }
  return out.join("\n");
}

/** 尝试把工具结果文本解析为 JSON（dsh-knowledge 工具结果多为 JSON）。 */
function resultJsonOf(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** 检索结果的引用文件列表（dedupe）。 */
function citedFiles(resultJson) {
  const files = new Set();
  const chunks = resultJson?.data?.chunks || resultJson?.chunks || [];
  for (const c of chunks) {
    for (const r of c?.references || c?.file_path ? [c.file_path, ...(c.references || [])] : c?.references || []) {
      if (typeof r === "string" && r.trim()) files.add(r.trim().split("/").pop());
    }
  }
  return [...files].slice(0, 8);
}

/* ---------------------------------------------------------------- 图谱布局（移植自 dsh-knowledge client） */

function layoutGraph(entities, relations, width, height) {
  const ids = entities.map((n) => n.id);
  const idx = {};
  ids.forEach((id, i) => { idx[id] = i });
  const pos = {};
  ids.forEach((id) => {
    pos[id] = { x: width / 2 + (Math.random() - 0.5) * 240, y: height / 2 + (Math.random() - 0.5) * 240 };
  });
  const edges = (relations || []).filter(
    (r) => idx[r.source] !== undefined && idx[r.target] !== undefined && r.source !== r.target,
  );
  const K = 140;
  for (let iter = 0; iter < 150; iter++) {
    const fx = new Array(ids.length).fill(0);
    const fy = new Array(ids.length).fill(0);
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        let dx = pos[ids[i]].x - pos[ids[j]].x;
        let dy = pos[ids[i]].y - pos[ids[j]].y;
        let d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        if (d > 800) d = 800;
        const f = (K * K) / d;
        const ux = dx / d;
        const uy = dy / d;
        fx[i] += ux * f; fy[i] += uy * f;
        fx[j] -= ux * f; fy[j] -= uy * f;
      }
    }
    for (const e of edges) {
      const a = idx[e.source];
      const b = idx[e.target];
      const dx = pos[e.source].x - pos[e.target].x;
      const dy = pos[e.source].y - pos[e.target].y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = (d * d) / K;
      const ux = dx / d;
      const uy = dy / d;
      fx[a] -= ux * f; fy[a] -= uy * f;
      fx[b] += ux * f; fy[b] += uy * f;
    }
    for (let i = 0; i < ids.length; i++) {
      const id = ids[i];
      fx[i] += (width / 2 - pos[id].x) * 0.008;
      fy[i] += (height / 2 - pos[id].y) * 0.008;
      pos[id].x += fx[i] * 0.05;
      pos[id].y += fy[i] * 0.05;
      pos[id].x = Math.max(30, Math.min(width - 30, pos[id].x));
      pos[id].y = Math.max(24, Math.min(height - 24, pos[id].y));
    }
  }
  return { pos, edges };
}

/** 工具结果里的图谱卡：kb_graph_search 的 entities/relations 渲染为 SVG 关联网络。 */
function GraphCard({ entities, relations, truncated }) {
  const [selected, setSelected] = useState(null);
  const layout = useMemo(() => {
    if (!entities?.length) return null;
    return layoutGraph(entities, relations || [], 760, 380);
  }, [entities, relations]);

  if (!layout) return null;
  const sel = entities.find((n) => n.id === selected);

  return (
    <div className="kb-graph-wrap is-compact">
      <svg className="kb-graph-svg" viewBox="0 0 760 380" preserveAspectRatio="xMidYMid meet">
        {layout.edges.map((e, i) => {
          const a = layout.pos[e.source];
          const b = layout.pos[e.target];
          const mx = (a.x + b.x) / 2;
          const my = (a.y + b.y) / 2;
          const showLabel = (relations || []).length <= 24 && e.description;
          const labelText = e.description.length > 12 ? `${e.description.slice(0, 12)}…` : e.description;
          return (
            <g key={`e${i}`}>
              <line className="kb-edge" x1={a.x} y1={a.y} x2={b.x} y2={b.y} />
              <title>{`${e.source} → ${e.target}：${e.description || "（无描述）"}`}</title>
              {showLabel ? (
                <text className="kb-edge-label" x={mx} y={my - 4} textAnchor="middle">{labelText}</text>
              ) : null}
            </g>
          );
        })}
        {entities.map((n) => {
          const p = layout.pos[n.id];
          if (!p) return null;
          const label = n.id.length > 10 ? `${n.id.slice(0, 10)}…` : n.id;
          return (
            <g
              key={n.id}
              className={`kb-node${selected === n.id ? " sel" : ""}`}
              onClick={() => setSelected(selected === n.id ? null : n.id)}
            >
              <circle cx={p.x} cy={p.y} r={6} />
              <text x={p.x} y={p.y + 18} textAnchor="middle">{label}</text>
            </g>
          );
        })}
      </svg>
      <div className="kb-graph-meta">
        <span>{entities.length} 实体 · {(relations || []).length} 关系{truncated ? "（已截断）" : ""}</span>
        {sel ? (
          <span className="kb-graph-detail">
            <strong>{sel.id}</strong>
            {sel.type ? <em>{sel.type}</em> : null}
            <p>{sel.description ? sel.description.slice(0, 240) : "（此实体暂无描述）"}</p>
          </span>
        ) : (
          <span className="kb-graph-detail is-hint">点击节点查看实体描述</span>
        )}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- 思考卡 */

/** 模型思考（reasoning 块）：默认收起，点击展开全文，形态对齐 dsh-web 的「思考 ·」行。 */
function ThinkingCard({ message }) {
  const [open, setOpen] = useState(false);
  const firstLine =
    String(message.content || "")
      .split("\n")
      .map((s) => s.trim())
      .find(Boolean) || "思考中";
  const brief = firstLine.length > 46 ? `${firstLine.slice(0, 45)}…` : firstLine;

  return (
    <div className="chat-message is-thinking-msg">
      <button
        type="button"
        className={`chat-think${open ? " is-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="chat-think-head">
          <Brain size={14} weight="duotone" aria-hidden="true" />
          <em>思考</em>
          <span className="chat-think-brief">{brief}</span>
          <CaretDown size={13} weight="bold" aria-hidden="true" />
        </span>
        {open ? <span className="chat-think-body">{message.content}</span> : null}
      </button>
    </div>
  );
}

/* ---------------------------------------------------------------- 工具卡 */

export function ToolDebugDetails({ card }) {
  const args = parseToolArguments(card.args || card.argsText);
  return <div className="chat-tool-body">
    <p className="chat-tool-debug-label">工具：{card.name || "未知"}</p>
    {args.command ? <><p className="chat-tool-debug-label">原始命令</p><pre className="chat-tool-io">{args.command}</pre></> : null}
    {card.argsText ? args.command ? <details className="chat-tool-raw-arguments"><summary>查看全部输入参数</summary><pre className="chat-tool-io">{card.argsText}</pre></details>
      : <><p className="chat-tool-debug-label">输入参数</p><pre className="chat-tool-io">{card.argsText}</pre></> : null}
    {card.resultText ? <><p className="chat-tool-debug-label">返回结果</p><pre className="chat-tool-io">{card.resultText}</pre></> : null}
  </div>;
}

export function ToolCard({ card, initialOpen = false }) {
  const [open, setOpen] = useState(initialOpen);
  const progress = toolProgress(card);
  const running = ["running", "cancelling"].includes(card.status);
  const incomplete = ["error", "partial", "interrupted", "stop-unconfirmed"].includes(card.status);
  const json = card.resultJson;

  return (
    <article className={`chat-tool-card is-${card.status}${open ? " is-open" : ""}`}>
      <button className="chat-tool-head" type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="chat-tool-spin" aria-hidden="true">
          {running ? <React.Fragment><i /><i /><i /></React.Fragment> : incomplete ? <WarningCircle size={15} weight="fill" /> : <CheckCircle size={14} weight="fill" />}
        </span>
        <span className="chat-tool-copy"><strong>{progress.title}</strong><small>{progress.label}</small></span>
        <span className="chat-tool-state">{toolStatusLabel(card)}</span>
        <CaretDown size={13} weight="bold" aria-hidden="true" className={open ? "is-down" : ""} />
      </button>

      {card.name === "kb_graph_search" && card.status === "done" && json?.entities?.length ? (
        <GraphCard entities={json.entities} relations={json.relations} truncated={json.is_truncated} />
      ) : null}

      {card.name === "lightrag_query_data" && card.status === "done" ? (
        <div className="chat-tool-facts">
          {json?.query_id ? <span className="chat-tool-fact">查询 id：{json.query_id}</span> : null}
          {json?.mode ? <span className="chat-tool-fact">模式：{json.mode}</span> : null}
          {typeof json?.data?.chunks?.length === "number" ? (
            <span className="chat-tool-fact">chunks：{json.data.chunks.length}</span>
          ) : null}
          {citedFiles(json).length ? (
            <span className="chat-tool-fact is-files">引用：{citedFiles(json).join("、")}</span>
          ) : null}
        </div>
      ) : null}

      {card.name === "kb_analyze" && card.status === "done" && json?.summary ? (
        <div className="chat-tool-facts">
          <span className="chat-tool-fact">源冲突：{json.summary.conflicts ?? "–"}</span>
          <span className="chat-tool-fact">失败文档：{json.summary.failed_docs ?? "–"}</span>
          <span className="chat-tool-fact">重复实体候选：{json.summary.dup_candidates ?? "–"}</span>
          <span className="chat-tool-fact">零命中查询：{json.summary.gap_items ?? "–"}</span>
        </div>
      ) : null}

      {card.name === "kb_status" && card.status === "done" && json?.engine ? (
        <div className="chat-tool-facts">
          <span className="chat-tool-fact">引擎：{json.engine.status}</span>
          <span className="chat-tool-fact">管道：{json.engine.pipeline_busy ? "忙碌" : "空闲"}</span>
          {typeof json?.stats?.active === "number" ? (
            <span className="chat-tool-fact">生效文档：{json.stats.active}</span>
          ) : null}
        </div>
      ) : null}

      {open ? <ToolDebugDetails card={card} /> : null}

      {incomplete ? <p className={`chat-tool-notice is-${card.status}`}>{toolResultDetail(card.resultText, card.status, card.name)}</p> : null}
    </article>
  );
}

export function ToolGroup({ group, initialOpen = false }) {
  const [open, setOpen] = useState(initialOpen);
  return <article className={`chat-tool-group${open ? " is-open" : ""}`}>
    <button type="button" className="chat-tool-head" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <span className="chat-tool-spin" aria-hidden="true"><StackSimple size={15} /></span>
      <span className="chat-tool-copy"><strong>{group.progress.groupTitle}</strong><small>连续执行记录 · 保留每次详情</small></span>
      <span className="chat-tool-state">{group.cards.length} 步</span>
      <CaretDown size={13} weight="bold" aria-hidden="true" className={open ? "is-down" : ""} />
    </button>
    {open ? <div className="chat-tool-group-items">{group.cards.map(card => <ToolCard key={card.id} card={card} />)}</div> : null}
  </article>;
}

/* ---------------------------------------------------------------- 审批卡 */

export function ApprovalCard({ card, onDecide }) {
  const [busy, setBusy] = useState(false);
  const decided = card.status !== "pending";

  const decide = async (decision) => {
    setBusy(true);
    try {
      await onDecide(card, decision);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className={`chat-approval-card is-${card.status}`}>
      <div className="chat-approval-head">
        <span className="chat-approval-badge" aria-hidden="true">
          <CheckCircle size={14} weight="fill" />
        </span>
        <div>
          <strong>{decided ? (card.status === "allowed" ? "已批准" : "已拒绝") : "需要你的批准"}</strong>
          <small>{toolLabel(card.toolName)} 请求执行写操作</small>
        </div>
      </div>
      {card.reason ? <p className="chat-approval-reason">{card.reason.slice(0, 400)}</p> : null}
      {!decided ? (
        <div className="chat-approval-actions">
          <button type="button" className="is-allow" disabled={busy} onClick={() => decide("allowed-once")}>
            {busy ? "提交中…" : "批准执行"}
          </button>
          <button type="button" className="is-deny" disabled={busy} onClick={() => decide("rejected")}>
            拒绝
          </button>
        </div>
      ) : null}
    </article>
  );
}

/* ---------------------------------------------------------------- 消息气泡 */

function RobotAvatar({ activity = "waiting", compact = false, hero = false }) {
  return (
    <span
      className={`robot-avatar is-${activity}${compact ? " is-compact" : ""}${hero ? " is-hero" : ""}`}
      aria-hidden="true"
    >
      <span className="robot-avatar-orbit" />
      <span className="robot-avatar-orbit is-inner" />
      <span className="robot-avatar-portrait">
        <img src={assistantHead} alt="" />
        <span className="robot-avatar-eyelids">
          <i />
          <i />
        </span>
      </span>
      <span className="robot-avatar-scan" />
    </span>
  );
}

export function AssistantMessage({ message, onFeedback, pending = false, activityText = "" }) {
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState(null);

  const fullText = message.content || "";

  const copyAnswer = async () => {
    try {
      await navigator.clipboard?.writeText(fullText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };

  const shareAnswer = async () => {
    try {
      if (navigator.share) {
        await navigator.share({ title: `${activeAgent.short || "知识库助手"}回答`, text: fullText });
        return;
      }
      await navigator.clipboard?.writeText(fullText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };

  const rate = (value) => {
    const next = feedback === value ? null : value;
    setFeedback(next);
    if (next) onFeedback?.(message, next);
  };

  return (
    <article className={`chat-message-row is-assistant${pending ? " is-pending" : ""}`}>
      <RobotAvatar activity={pending ? "working" : "waiting"} compact />
      <div className="chat-message-stack">
        <div className="chat-message-meta">
          <strong>{activeAgent.short || "知识库助手"}</strong>
          <time>{message.time}</time>
        </div>
        <div className="chat-assistant-content">
          {pending ? (
            <div className="chat-thinking" role="status" aria-live="polite">
              <span className="chat-thinking-bars" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              <div>
                <strong>{activityText || "正在思考"}</strong>
                <span>{IS_HARNESS_MODE ? "数据分析与工具执行过程实时可见" : "检索证据与执行过程实时可见"}</span>
              </div>
            </div>
          ) : (
            <Markdown>{fullText}</Markdown>
          )}
        </div>
        {!pending && fullText ? (
          <div className="chat-message-actions" aria-label="消息操作">
            <button
              type="button"
              aria-label={copied ? "回答已复制" : "复制回答"}
              title={copied ? "已复制" : "复制回答"}
              onClick={copyAnswer}
            >
              <Copy size={15} />
            </button>
            {onFeedback ? <><button
              className={feedback === "up" ? "is-active" : ""}
              type="button"
              aria-label="回答有帮助"
              aria-pressed={feedback === "up"}
              title="回答有帮助"
              onClick={() => rate("up")}
            >
              <ThumbsUp size={15} />
            </button>
            <button
              className={feedback === "down" ? "is-active" : ""}
              type="button"
              aria-label="回答需改进"
              aria-pressed={feedback === "down"}
              title="回答需改进"
              onClick={() => rate("down")}
            >
              <ThumbsDown size={15} />
            </button></> : null}
            <button type="button" aria-label="分享回答" title="分享回答" onClick={shareAnswer}>
              <ShareNetwork size={15} />
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
}

export function UserMessage({ message }) {
  return (
    <article className="chat-message-row is-user">
      <div className="chat-message-stack">
        <div className="chat-message-meta">
          <strong>你</strong>
          <time>{message.time}</time>
        </div>
        <div className="chat-user-content">{message.content}</div>
        {message.attachment?.kind === "image" && message.attachment.previewUrl ? (
          <figure className="chat-user-image">
            <img src={message.attachment.previewUrl} alt={`上传图片：${message.attachment.name}`} />
            <figcaption>{message.attachment.name}</figcaption>
          </figure>
        ) : null}
      </div>
      <span className="chat-user-avatar" aria-hidden="true">
        <UserCircle size={26} weight="duotone" />
      </span>
    </article>
  );
}

export function AttachmentChip({ attachment, onRemove }) {
  return <div className={`chat-attachment-chip${attachment.kind === "image" ? " is-image" : ""}`}>
    {attachment.kind === "image" ? <img className="chat-attachment-preview" src={attachment.previewUrl} alt={`待发送图片：${attachment.name}`} /> :
      <span className="chat-attachment-icon" aria-hidden="true"><FileText size={15} weight="duotone" /></span>}
    <span className="chat-attachment-copy"><strong>{attachment.name}</strong><small>{attachment.kind === "image" ? "图片 · " : "附件 · "}{attachmentSizeLabel(attachment.size)}</small></span>
    <button type="button" aria-label={`移除 ${attachment.name}`} onClick={onRemove}><X size={13} /></button>
  </div>;
}

export function ChatSendButton({ isThinking, cancellationState, attachmentReading, hasContent, hasAttachment, onSend, onStop }) {
  const label = cancellationState === "pending" ? "正在停止" : cancellationState === "failed" ? "重试停止" : isThinking ? "停止回答" : "发送消息";
  const stopping = isThinking || cancellationState !== "idle";
  const disabled = cancellationState === "pending" || (!stopping && !canSendChat({ attachmentReading, hasContent, hasAttachment }));
  return <button className={`chat-send-button${stopping ? " is-stopping" : ""}`} type="button" disabled={disabled}
    aria-label={label} title={label} onClick={stopping ? onStop : onSend}>
    {stopping ? <StopCircle size={16} weight="fill" /> : <ArrowUp size={15} weight="bold" />}
  </button>;
}

/* ---------------------------------------------------------------- 执行过程抽屉 */

function PlannerNatureGlyph({ type = "sprout" }) {
  const glyphs = {
    tree: (
      <>
        <path className="planner-glyph-line planner-tree-trunk" d="M12 20.5v-4.7M7 20.5h10" />
        <path className="planner-glyph-fill planner-tree-crown planner-tree-crown-left" d="M3.8 10.2C3.8 6.8 6.2 4.4 9.4 4.4c1.1-2 4.1-2.2 5.5-.4 3.2-.2 5.5 2.1 5.5 5 0 3.1-2.4 5.3-5.4 5.3H8.9c-3 0-5.1-1.6-5.1-4.1Z" />
        <path className="planner-glyph-line planner-tree-ground" d="M7.2 20.1h9.6" />
        <circle className="planner-glyph-result planner-tree-fruit" cx="8.2" cy="8.5" r="1.15" />
        <circle className="planner-glyph-result planner-tree-fruit" cx="15.8" cy="7.1" r="1.15" />
        <circle className="planner-glyph-result planner-tree-fruit" cx="13.9" cy="11.2" r="1" />
      </>
    ),
    sprout: (
      <>
        <path className="planner-glyph-line planner-leaf-stem" d="M11.8 20c-.1-4.8.8-8.9 4.5-12.6" />
        <path className="planner-glyph-fill planner-leaf planner-leaf-left" d="M11.5 13.8C7.2 14.2 4.1 11.5 4 7.2c4.4-.6 7.6 2.1 7.5 6.6Z" />
        <path className="planner-glyph-fill planner-leaf planner-leaf-right" d="M12.9 10.7c.4-3.8 3.3-6.3 7.1-6.1.1 3.9-2.8 6.6-7.1 6.1Z" />
        <circle className="planner-leaf-bud" cx="11.8" cy="19.7" r="1.15" />
      </>
    ),
  };
  return (
    <svg className={`planner-leaf-glyph planner-nature-glyph is-${type}`} viewBox="0 0 24 24" fill="none" role="presentation">
      {glyphs[type] || glyphs.sprout}
    </svg>
  );
}

export function TimelineDrawer({ open, onClose, timeline, activity }) {
  const finished = activity !== "working";
  const groups = groupToolSteps(timeline);
  const problems = timeline.filter(item => ["error", "partial", "rejected", "interrupted"].includes(item.status) || item.kind === "error").length;

  return (
    <aside
      className={`chat-planner-drawer${open ? " is-open" : ""}`}
      aria-label="执行过程"
      aria-hidden={!open}
    >
      <header className="planner-heading">
        <div className="planner-heading-main">
          <span className="planner-heading-emblem" aria-hidden="true">
            <PlannerNatureGlyph type="tree" />
          </span>
          <div className="planner-heading-copy">
            <span>TIMELINE</span>
            <h2>执行过程</h2>
          </div>
        </div>
        <button type="button" aria-label="收起执行过程" title="收起" onClick={onClose}>
          <X size={18} />
        </button>
      </header>

      <section className={`planner-overview is-${activity}`} aria-label="执行概览">
        <span className={`planner-summary-mark is-${finished ? "done" : "active"}`} aria-hidden="true">
          <PlannerNatureGlyph type={finished ? "tree" : "sprout"} />
        </span>
        <div className="planner-overview-copy">
          <span>{finished ? problems ? "执行已结束，包含未完成步骤" : "执行记录" : "任务进行中"}</span>
          <strong>{timeline.length ? `${timeline.length} 项操作` : "等待新任务"}</strong>
          <p className="planner-status-counts">{problems ? `${problems} 项未完成或被拒绝` : finished ? "可展开查看执行依据与详情" : "步骤随实际工具调用更新"}</p>
        </div>
      </section>

      <ol className="chat-timeline" aria-label="执行时间线">
        {timeline.length ? (
          groups.map((item) => (
            <li key={item.id} className={`chat-timeline-item is-${item.kind} is-${item.status || "info"}`}>
              <span className="chat-timeline-dot" aria-hidden="true" />
              <div className="chat-timeline-body">
                <strong>{item.role === "tool-group" ? item.progress.groupTitle : item.title}</strong>
                {item.kind === "tool" ? <>
                  <p className="chat-timeline-detail">{toolStatusLabel(item)}{item.detail ? ` · ${item.detail}` : ""}</p>
                  <details className="chat-timeline-debug"><summary>查看执行详情</summary><ToolDebugDetails card={item} /></details>
                </> : item.role === "tool-group" ? <>
                  <p className="chat-timeline-detail">连续 {item.cards.length} 步 · 保留全部执行记录</p>
                  <details className="chat-timeline-debug"><summary>查看每步详情</summary>{item.cards.map(step => <section key={step.id} className="chat-timeline-group-step"><strong>{step.title || toolProgress(step).title}</strong><p>{toolStatusLabel(step)} · {step.detail}</p><ToolDebugDetails card={step} /></section>)}</details>
                </> : item.detail ? <p className="chat-timeline-detail">{item.detail}</p> : null}
              </div>
            </li>
          ))
        ) : (
          <li className="chat-timeline-item is-empty">{IS_HARNESS_MODE ? "发送任务后，这里会实时展示 Skill、代码执行与视觉核验过程。" : "发送消息后，这里会实时展示工具调用与审批过程。"}</li>
        )}
      </ol>

      <footer className="planner-footer">
        <span className={`planner-live is-${activity}`} aria-hidden="true" />
        <span>{finished ? "等待下一条消息" : IS_HARNESS_MODE ? "工具调用与执行结果实时同步" : "工具调用与审批实时同步"}</span>
      </footer>
    </aside>
  );
}

function clockTime() {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date());
}

function BrandMark() {
  return (
    <span className="chat-brand-symbol" aria-hidden="true">
      <span />
      <span />
      <span />
      <i />
    </span>
  );
}

/* ---------------------------------------------------------------- 主组件 */

export default function AgentChat() {
  const [sessions, setSessions] = useState(loadSessions);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [attachment, setAttachment] = useState(null);
  const [attachmentReading, setAttachmentReading] = useState(false);
  const [attachmentError, setAttachmentError] = useState("");
  const [cancellationState, setCancellationState] = useState("idle");
  const [cancellationError, setCancellationError] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [plannerOpen, setPlannerOpen] = useState(false);
  const [capabilityOpen, setCapabilityOpen] = useState(false);
  const [composerExpanded, setComposerExpanded] = useState(false);
  const [timeline, setTimeline] = useState([]);
  const [activityText, setActivityText] = useState("");
  const messagesEndRef = useRef(null);
  const abortRef = useRef(null);
  const fileInputRef = useRef(null);
  const composerInputRef = useRef(null);
  const pendingUserTextRef = useRef(null);
  const currentQueryIdRef = useRef(null);
  const currentUserTextRef = useRef(null);
  const sessionSeqRef = useRef(0);
  const attachmentReadSeqRef = useRef(0);
  const cancellationRef = useRef(null);

  const activity = isThinking || cancellationState === "pending" ? "working" : attachment || attachmentReading ? "reading" : "waiting";
  const activityLabel = cancellationState === "pending" ? "正在停止本轮执行" : cancellationState === "failed" ? "停止尚未确认" : isThinking ? activityText || "正在执行" : attachmentReading ? "正在读取附件" : attachment ? "附件已准备" : "在线，可以开始";

  const quickPrompts = IS_HARNESS_MODE ? [
    "当前有哪些可用 Skills？分别能做什么？",
    "探查 .run/try-data/array.h5，列出数据体检所需确认的信息。",
    "检查 .run/try-data/unknown-fs.npy，不猜采样率，先做不依赖 Hz 的检查。",
    "读取 .run/try-data/reference-results，用视觉工具核对分析图与数值结果。",
  ] : [
    "知识库里有哪些关于报销的制度？",
    "做一次知识库体检，看看有什么问题",
    "知识库当前健康状态如何？",
    "帮我看看「报销」相关的知识图谱",
  ];

  const visibleHistory = useMemo(() => {
    const query = historyQuery.trim().toLowerCase();
    return query ? sessions.filter((item) => item.title.toLowerCase().includes(query)) : sessions;
  }, [sessions, historyQuery]);
  const visibleMessages = groupToolSteps(messages);

  useLayoutEffect(() => {
    document.documentElement.classList.add("chat-view");
    document.body.classList.add("chat-view");
    return () => {
      document.documentElement.classList.remove("chat-view");
      document.body.classList.remove("chat-view");
    };
  }, []);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = IS_HARNESS_MODE ? "水下数据分析智能体 | 对话工作台" : "知识库助手 | 对话工作台";
    return () => {
      document.title = previousTitle;
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isThinking]);

  useLayoutEffect(() => {
    const input = composerInputRef.current;
    if (!input) return;

    input.style.height = "0px";
    const contentHeight = input.scrollHeight;
    const nextHeight = Math.min(Math.max(contentHeight, 30), 96);
    input.style.height = `${nextHeight}px`;
    input.style.overflowY = contentHeight > 96 ? "auto" : "hidden";
    setComposerExpanded(draft.includes("\n") || nextHeight > 34);
  }, [draft]);

  useEffect(() => {
    const handleEscape = (event) => {
      if (event.key === "Escape") {
        setHistoryOpen(false);
        setPlannerOpen(false);
        setCapabilityOpen(false);
      }
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, []);

  useEffect(() => () => {
    sessionSeqRef.current += 1;
    attachmentReadSeqRef.current += 1;
    abortRef.current?.cancel().catch(() => {});
  }, []);

  const timelineIdRef = useRef(0);
  const timelineCallRef = useRef(new Map());
  const timelineApprovalRef = useRef(new Map());

  /** 追加一条过程项（tool/approval/error），返回条目 id 供后续更新状态。 */
  const pushTimelineItem = useCallback((item) => {
    const id = `tl-${++timelineIdRef.current}`;
    setTimeline((items) => [...items, { id, time: clockTime(), ...item }]);
    return id;
  }, []);

  /** 审批决定：用 callId 匹配审批桥的 pending 记录再提交。 */
  const handleDecide = useCallback(async (card, decision) => {
    if (IS_HARNESS_MODE) return;
    const pending = await fetchPendingApprovals();
    const match =
      pending.find((p) => p.callId && card.callId && p.callId === card.callId) ||
      pending.find((p) => p.toolName === card.toolName);
    if (!match) throw new Error("审批请求已失效");
    await decideApproval(match.id, decision);
    setMessages((items) =>
      items.map((m) => (m.role === "approval" && m.approvalKey === card.approvalKey ? { ...m, status: decision === "allowed-once" ? "allowed" : "rejected" } : m)),
    );
    const tlId = timelineApprovalRef.current.get(card.approvalKey);
    if (tlId) {
      setTimeline((items) =>
        items.map((it) => (it.id === tlId ? { ...it, status: decision === "allowed-once" ? "allowed" : "rejected" } : it)),
      );
    }
  }, []);

  /** 点赞/点踩：带本轮 query_id 落 feedback.jsonl。 */
  const handleFeedback = useCallback((message, rating) => {
    if (IS_HARNESS_MODE) return;
    submitFeedback({
      rating,
      ...(message.queryId ? { query_id: message.queryId } : {}),
      question: message.question || "",
      answer: (message.content || "").slice(0, 4000),
    }).catch(() => {
      // 反馈失败不打断对话；静默（按钮状态保留用户意图）
    });
  }, []);

  const handleNotification = useCallback((notification) => {
    if (notification.method === "session.status") {
      return;
    }
    const event = notification.params?.event;
    if (!event || typeof event.type !== "string") return;
    const data = event.data || {};

    if (event.type === "user/message" && data.source?.kind === "user") {
      if (pendingUserTextRef.current) pendingUserTextRef.current = null;
      return;
    }

    if (event.type === "step/start") {
      setActivityText("正在响应");
      return;
    }

    if (event.type === "assistant/message") {
      const blocks = data.message?.content || [];
      const reasoning = blocks
        .filter((b) => b && b.type === "reasoning" && typeof b.text === "string")
        .map((b) => b.text)
        .join("\n\n");
      const text = blocks
        .filter((b) => b && b.type === "text")
        .map((b) => b.text)
        .join("");
      if (reasoning) {
        setMessages((items) => [
          ...items,
          {
            id: `thinking-${event.seq}`,
            role: "thinking",
            time: clockTime(),
            content: reasoning,
          },
        ]);
      }
      if (!text) return;
      setMessages((items) => [
        ...items,
        {
          id: `assistant-${event.seq}`,
          role: "assistant",
          time: clockTime(),
          content: text,
          queryId: currentQueryIdRef.current,
          question: currentUserTextRef.current || "",
        },
      ]);
      return;
    }

    if (event.type === "tool/call") {
      const args = parseToolArguments(data.arguments);
      const progress = toolProgress({ name: data.name, args });
      setMessages((items) => [
        ...items,
        {
          id: `tool-${data.callId}`,
          role: "tool",
          callId: data.callId,
          name: data.name,
          args,
          argsText: typeof data.arguments === "string" ? data.arguments : JSON.stringify(args),
          status: "running",
          time: clockTime(),
        },
      ]);
      setActivityText(progress.activity);
      const tlId = pushTimelineItem({
        kind: "tool",
        title: progress.title,
        progress,
        name: data.name,
        args,
        argsText: typeof data.arguments === "string" ? data.arguments : JSON.stringify(args),
        status: "running",
      });
      if (data.callId) timelineCallRef.current.set(data.callId, tlId);
      return;
    }

    if (event.type === "tool/result") {
      const text = resultText(data);
      const block = data.message?.content?.find?.((b) => b?.type === "tool-result");
      const callId = block?.toolCallId;
      const json = resultJsonOf(text);
      if (callId && json?.query_id) currentQueryIdRef.current = json.query_id;
      const isError = Boolean(data.error || block?.isError);
      setMessages((items) =>
        items.map((m) =>
          m.role === "tool" && (!callId || m.callId === callId) && m.status === "running"
            ? { ...m, status: toolResultState(m, text, isError), resultText: text, resultJson: json }
            : m,
        ),
      );
      const tlId = callId ? timelineCallRef.current.get(callId) : null;
      if (tlId) {
        setTimeline((items) =>
          items.map((it) =>
            it.id === tlId ? { ...it, status: toolResultState(it, text, isError), resultText: text, detail: toolResultDetail(text, toolResultState(it, text, isError), it.name) } : it,
          ),
        );
      }
      return;
    }

    if (event.type === "approval/asked") {
      setMessages((items) => [
        ...items,
        {
          id: `approval-${event.seq}`,
          approvalKey: `approval-${event.seq}`,
          role: "approval",
          approvalId: data.id,
          toolName: data.toolName || "",
          callId: data.callId || "",
          reason: data.reason || "",
          status: "pending",
          time: clockTime(),
        },
      ]);
      const apTlId = pushTimelineItem({
        kind: "approval",
        title: `${toolLabel(data.toolName)} 请求审批`,
        detail: data.reason || "",
        status: "pending",
      });
      timelineApprovalRef.current.set(`approval-${event.seq}`, apTlId);
      return;
    }

    if (event.type === "approval/decided") {
      // 决定已由 handleDecide 或其他端写入；把最早仍 pending 的同名审批卡标记完成
      setMessages((items) => {
        const idx = items.findIndex((m) => m.role === "approval" && m.status === "pending");
        if (idx < 0) return items;
        const next = [...items];
        next[idx] = {
          ...next[idx],
          status: data.outcome === "allowed-once" ? "allowed" : "rejected",
        };
        return next;
      });
      setTimeline((items) => {
        const idx = items.findIndex((it) => it.kind === "approval" && it.status === "pending");
        if (idx < 0) return items;
        const next = [...items];
        next[idx] = { ...next[idx], status: data.outcome === "allowed-once" ? "allowed" : "rejected" };
        return next;
      });
      return;
    }

    if (event.type === "turn/end") {
      if (data.reason?.kind === "error") {
        const message = data.reason?.error?.message || "本轮执行失败";
        setMessages((items) => [
          ...items,
          {
            id: `turn-error-${event.seq}`,
            role: "assistant",
            time: clockTime(),
            content: `执行遇到问题：${message}`,
            instant: true,
          },
        ]);
        pushTimelineItem({ kind: "error", title: "本轮异常结束", detail: message });
      }
    }
  }, [pushTimelineItem]);

  const resetTurnState = useCallback(() => {
    setIsThinking(false);
    setActivityText("");
    abortRef.current = null;
    cancellationRef.current = null;
    setCancellationState("idle");
    setCancellationError("");
    pendingUserTextRef.current = null;
    currentQueryIdRef.current = null;
  }, []);

  const sendMessage = (preset) => {
    const typedContent = (typeof preset === "string" ? preset : draft).trim();
    if (abortRef.current || !canSendChat({ isThinking, cancellationState: cancellationRef.current?.state || cancellationState, attachmentReading, hasContent: Boolean(typedContent), hasAttachment: Boolean(attachment) })) return;

    const content = typedContent || (attachment.kind === "image" ? `请解读这张图片：${attachment.name}` : `请处理附件：${attachment.name}`);
    const timestamp = Date.now();

    currentUserTextRef.current = content;
    pendingUserTextRef.current = content;
    currentQueryIdRef.current = null;
    const turnSeq = ++sessionSeqRef.current;
    const current = () => turnSeq === sessionSeqRef.current;

    setMessages((items) => [
      ...items,
      { id: `user-${timestamp}`, role: "user", time: clockTime(), content,
        ...(attachment ? { attachment: { name: attachment.name, kind: attachment.kind, previewUrl: attachment.previewUrl } } : {}) },
    ]);
    setDraft("");
    setAttachment(null);
    setAttachmentError("");
    setIsThinking(true);
    setActivityText(attachment?.kind === "image" ? "正在上传图片" : "正在响应");
    setTimeline([]);
    timelineCallRef.current.clear();
    timelineApprovalRef.current.clear();

    abortRef.current = streamChat(
      { sessionId, message: content, attachments: attachmentPayload(attachment) },
      {
        onStart: (id) => {
          if (!current()) return;
          setSessionId(id);
          setSessions(upsertSession(id, content));
        },
        onPhase: ({ message }) => {
          if (current() && typeof message === "string") setActivityText(message);
        },
        onRenamed: ({ from, to }) => {
          if (!current()) return;
          setSessionId(to);
          setSessions(renameSession(from, to));
          setMessages((items) => [
            ...items,
            {
              id: `renamed-${to}`,
              role: "assistant",
              time: clockTime(),
              content: "服务已重启，已迁移会话继续处理当前问题。",
            },
          ]);
        },
        onNotification: (notification) => { if (current()) handleNotification(notification); },
        onDone: () => { if (current()) resetTurnState(); },
        onCancelled: () => {
          if (!current()) return;
          setMessages(items => [...interruptPendingSteps(items, "interrupted"), { id: `stopped-${timestamp}`, role: "assistant", time: clockTime(), content: "本轮执行已停止，可以在当前会话继续提问。", instant: true }]);
          setTimeline(items => interruptPendingSteps(items, "interrupted"));
          resetTurnState();
        },
        onError: (message) => {
          if (!current()) return;
          setMessages((items) => [
            ...items,
            {
              id: `error-${timestamp}`,
              role: "assistant",
              time: clockTime(),
              content: `执行遇到问题：${message}`,
              instant: true,
            },
          ]);
          // A broken stream can leave an SDK turn running. Wait for the same cancellation ACK.
          cancelCurrentTurn({ silent: true });
        },
      },
    );
  };

  const cancelCurrentTurn = async ({ silent = false } = {}) => {
    const handle = abortRef.current;
    if (!handle) return true;
    if (cancellationRef.current?.state === "pending") return cancellationRef.current.promise;
    const stopSeq = ++sessionSeqRef.current;
    const state = { state: "pending", promise: null };
    cancellationRef.current = state;
    setIsThinking(false); // Remove the live answer immediately; the server lock remains until ACK.
    setActivityText("");
    setCancellationState("pending");
    setCancellationError("");
    setMessages((items) => interruptPendingSteps(items, "cancelling"));
    setTimeline((items) => interruptPendingSteps(items, "cancelling"));
    state.promise = handle.cancel().then((result) => {
      if (stopSeq !== sessionSeqRef.current) return true;
      if (result.sessionId) {
        setSessionId(result.sessionId);
        setSessions(upsertSession(result.sessionId, currentUserTextRef.current));
      }
      setMessages((items) => {
        const stopped = interruptPendingSteps(items, "interrupted");
        return silent ? stopped : [...stopped, { id: `stopped-${Date.now()}`, role: "assistant", time: clockTime(), content: "本轮执行已停止，可以在当前会话继续提问。", instant: true }];
      });
      setTimeline((items) => interruptPendingSteps(items, "interrupted"));
      resetTurnState();
      return true;
    }).catch((error) => {
      if (stopSeq !== sessionSeqRef.current) return false;
      state.state = "failed";
      setCancellationState("failed");
      setCancellationError(error.message || "无法确认本轮执行已停止。");
      setMessages(items => interruptPendingSteps(items, "stop-unconfirmed"));
      setTimeline(items => interruptPendingSteps(items, "stop-unconfirmed"));
      return false;
    });
    return state.promise;
  };

  const startNewChat = async () => {
    if (!await stopResponseSilently()) return;
    sessionSeqRef.current += 1;
    setSessionId(null);
    setMessages([]);
    setTimeline([]);
    timelineCallRef.current.clear();
    timelineApprovalRef.current.clear();
    setHistoryOpen(false);
  };

  const stopResponseSilently = () => cancelCurrentTurn({ silent: true });

  const resumeSession = async (item) => {
    if (!await stopResponseSilently()) return;
    const historySeq = ++sessionSeqRef.current;
    setSessionId(item.sessionId);
    setMessages([]);
    setTimeline([]);
    setHistoryOpen(false);
    const events = await fetchChatHistory(item.sessionId);
    if (historySeq !== sessionSeqRef.current) return;
    if (!events.length) {
      setMessages([
        {
          id: `resumed-${item.sessionId}`,
          role: "assistant",
          time: clockTime(),
          content: `已切换到会话「${item.title}」，历史消息为空。继续提问即可开始。`,
          instant: true,
        },
      ]);
      return;
    }
    const wallTime = (ms) =>
      new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(ms));
    const restoredMessages = events.map((e) => {
        const time = typeof e.time === "number" ? wallTime(e.time) : clockTime();
        switch (e.kind) {
          case "user":
            return { id: `h-u-${e.seq}`, role: "user", time, content: e.text };
          case "assistant":
            return { id: `h-a-${e.seq}`, role: "assistant", time, content: e.text, instant: true };
          case "thinking":
            return { id: `h-t-${e.seq}`, role: "thinking", time, content: e.text };
          case "tool": {
            const args = parseToolArguments(e.argsText);
            return {
              id: `h-tool-${e.seq}`,
              role: "tool",
              callId: e.callId,
              name: e.name,
              args,
              argsText: e.argsText,
              status: e.status === "running" ? "running" : toolResultState({ name: e.name, args, status: e.status }, e.resultText),
              resultText: e.resultText || "",
              resultJson: resultJsonOf(e.resultText),
              time,
            };
          }
          case "approval":
            return {
              id: `h-ap-${e.seq}`,
              approvalKey: e.approvalKey,
              role: "approval",
              toolName: e.toolName,
              callId: e.callId || "",
              reason: e.reason || "",
              status: e.status || "rejected",
              time,
            };
          case "error":
            return { id: `h-e-${e.seq}`, role: "assistant", time, content: `执行遇到问题：${e.message}` };
          default:
            return null;
        }
      }).filter(Boolean);
    setMessages(restoredMessages);
    timelineCallRef.current.clear();
    timelineApprovalRef.current.clear();
    const restoredTimeline = restoredMessages.filter(message => ["tool", "approval"].includes(message.role)).map(message => {
      const id = `h-tl-${message.id}`;
      if (message.role === "approval") {
        timelineApprovalRef.current.set(message.approvalKey, id);
        return { ...message, id, kind: "approval", title: `${toolLabel(message.toolName)} 请求审批`, detail: message.reason };
      }
      timelineCallRef.current.set(message.callId, id);
      return { ...message, id, kind: "tool", progress: toolProgress(message), title: toolProgress(message).title, detail: message.status === "running" ? "此步骤尚未收到完成记录。" : toolResultDetail(message.resultText, message.status, message.name) };
    });
    setTimeline(restoredTimeline);
  };

  const deleteSession = (item) => {
    setSessions(removeSession(item.sessionId));
    if (item.sessionId === sessionId) startNewChat();
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      sendMessage();
    }
  };

  const removeAttachment = () => {
    attachmentReadSeqRef.current += 1;
    setAttachment(null);
    setAttachmentReading(false);
    setAttachmentError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const readAttachment = async (file) => {
    if (!file) return;
    const readSeq = ++attachmentReadSeqRef.current;
    setAttachment(null);
    setAttachmentError("");
    setAttachmentReading(true);
    try {
      const next = await readChatAttachment(file);
      if (readSeq === attachmentReadSeqRef.current) setAttachment(next);
    } catch (error) {
      if (readSeq === attachmentReadSeqRef.current) setAttachmentError(error.message);
    } finally {
      if (readSeq === attachmentReadSeqRef.current) setAttachmentReading(false);
    }
  };

  const handleComposerPaste = (event) => {
    try {
      const image = clipboardImageFile(event.clipboardData);
      if (!image) return; // Keep the browser's normal text paste, cursor and selection behavior.
      event.preventDefault();
      readAttachment(image);
    } catch (error) {
      event.preventDefault();
      setAttachmentError(error.message || "无法读取粘贴的图片，请重试。");
    }
  };

  return (
    <ArtifactProvider><main className={`chat-page${isThinking ? " is-working" : ""}`}>
      <div className="environment-image" aria-hidden="true" />
      <div className="grain" aria-hidden="true" />

      <div className="chat-workspace">
        <button
          className={`chat-drawer-backdrop${historyOpen || plannerOpen ? " is-visible" : ""}`}
          type="button"
          aria-label="关闭侧栏"
          onClick={() => {
            setHistoryOpen(false);
            setPlannerOpen(false);
          }}
        />

        <aside className={`chat-history${historyOpen ? " is-open" : ""}`} aria-label="历史对话">
          <div className="chat-sidebar-home">
            <a className="chat-home-link" href={IS_HARNESS_MODE ? "/chat" : "/"} aria-label={IS_HARNESS_MODE ? "水下数据分析工作台" : "返回知识库助手首页"}>
              <span className="chat-home-arrow" aria-hidden="true">
                <ArrowLeft size={16} weight="bold" />
              </span>
              <BrandMark />
              <span className="chat-home-copy">
                <strong>{IS_HARNESS_MODE ? "水下数据分析" : "知识库助手"}</strong>
                <small>{IS_HARNESS_MODE ? "分析工作台" : "返回门户"}</small>
              </span>
            </a>
            <button
              className="chat-panel-close"
              type="button"
              aria-label="关闭历史对话"
              onClick={() => setHistoryOpen(false)}
            >
              <X size={17} />
            </button>
          </div>

          <nav className="chat-sidebar-tools" aria-label="工作区入口">
            <button className="is-featured" type="button" onClick={startNewChat}>
              <span className="chat-sidebar-tool-icon" aria-hidden="true">
                <Plus size={18} weight="duotone" />
              </span>
              <span>
                <strong>新对话</strong>
                <small>开启全新会话</small>
              </span>
              <CaretRight size={15} weight="bold" aria-hidden="true" />
            </button>
            <button className="is-featured" type="button" onClick={() => setCapabilityOpen(true)}>
              <span className="chat-sidebar-tool-icon" aria-hidden="true">
                <CirclesThreePlus size={18} weight="duotone" />
              </span>
              <span>
                <strong>能力中心</strong>
                <small>查看可调用能力</small>
              </span>
              <CaretRight size={15} weight="bold" aria-hidden="true" />
            </button>
            {!IS_HARNESS_MODE ? <button className="is-placeholder" type="button" disabled>
              <span className="chat-sidebar-tool-icon" aria-hidden="true">
                <Books size={18} weight="duotone" />
              </span>
              <span>
                <strong>知识资料</strong>
                <small>在对话中上传</small>
              </span>
            </button> : null}
          </nav>

          <div className="chat-history-heading">
            <span>历史对话</span>
            <small>{sessions.length} 项</small>
          </div>
          <label className="chat-history-search">
            <MagnifyingGlass size={16} aria-hidden="true" />
            <span className="sr-only">搜索历史对话</span>
            <input
              type="search"
              placeholder="搜索对话"
              value={historyQuery}
              onChange={(event) => setHistoryQuery(event.target.value)}
            />
          </label>
          <nav className="chat-history-list" aria-label="最近的对话">
            {visibleHistory.map((item) => (
              <button
                className={item.sessionId === sessionId ? "is-active" : ""}
                type="button"
                key={item.sessionId}
                onClick={() => resumeSession(item)}
              >
                <span className="chat-history-icon" aria-hidden="true">
                  <ClockCounterClockwise size={16} />
                </span>
                <span className="chat-history-copy">
                  <strong>{item.title}</strong>
                  <small>{new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(item.time)}</small>
                </span>
                <Trash
                  size={15}
                  aria-hidden="true"
                  onClick={(event) => {
                    event.stopPropagation();
                    deleteSession(item);
                  }}
                />
              </button>
            ))}
            {!visibleHistory.length ? <p className="chat-history-empty">还没有历史对话。</p> : null}
          </nav>
          <div className="chat-history-footer">
            <span>
              <FileText size={16} weight="duotone" aria-hidden="true" />
              会话保存在本机
            </span>
            <button
              type="button"
              aria-label="清理历史对话"
              title="清理历史对话"
              onClick={() => {
                for (const item of sessions) removeSession(item.sessionId);
                setSessions([]);
                startNewChat();
              }}
            >
              <Trash size={16} />
            </button>
          </div>
        </aside>

        <section className="chat-main" aria-label="智能体对话内容">
          <header className="chat-agent-header">
            <button
              className="chat-mobile-menu"
              type="button"
              aria-label="打开历史对话"
              onClick={() => setHistoryOpen(true)}
            >
              <StackSimple size={18} weight="duotone" />
            </button>
            <div className="chat-agent-identity">
              <RobotAvatar activity={activity} />
              <div>
                <h1>{activeAgent.name}</h1>
                <div className={`chat-agent-status is-${activity}`} aria-live="polite">
                  <span aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </span>
                  {activityLabel}
                </div>
              </div>
            </div>
            <button
              className="chat-planner-shortcut"
              type="button"
              onClick={() => setPlannerOpen(true)}
            >
              执行过程
              <CaretRight size={13} weight="bold" aria-hidden="true" />
            </button>
          </header>

          <div className={`chat-messages${messages.length ? " has-messages" : ""}`}>
            <div className="chat-spatial-object" aria-hidden="true">
              <span className="chat-spatial-aura" />
              <React.Suspense fallback={<span className="chat-spatial-loading" />}>
                <ParticleStage shape={activeAgent.shape} />
              </React.Suspense>
            </div>
            {!messages.length ? (
              <section className="chat-welcome" aria-labelledby="chat-welcome-title">
                <RobotAvatar activity={activity} hero />
                <p className="chat-welcome-label">{activeAgent.role}</p>
                <h2 id="chat-welcome-title">{IS_HARNESS_MODE ? "今天想分析哪份水声数据？" : "今天想了解或整理什么？"}</h2>
                <p>{IS_HARNESS_MODE ? "上传数据或提供项目内路径，我会先确认数据特点，再调用 Skill、执行分析并核对结果。" : "可以直接提问知识内容、上传文档入库、编辑知识图谱，或让我做一次知识库体检。"}</p>
                <div className="chat-starter-grid" aria-label="快捷提问">
                  {quickPrompts.map((prompt) => (
                    <button type="button" key={prompt} onClick={() => sendMessage(prompt)}>
                      <span>{prompt}</span>
                      <ArrowUp size={15} weight="bold" aria-hidden="true" />
                    </button>
                  ))}
                </div>
              </section>
            ) : (
              <div className="chat-thread">
                <div className="chat-date-separator">
                  <span>今天</span>
                </div>
                {visibleMessages.map((message) => {
                  if (message.role === "user") return <UserMessage key={message.id} message={message} />;
                  if (message.role === "thinking") return <ThinkingCard key={message.id} message={message} />;
                  if (message.role === "tool") return <ToolCard key={message.id} card={message} />;
                  if (message.role === "tool-group") return <ToolGroup key={message.id} group={message} />;
                  if (message.role === "approval") {
                    return IS_HARNESS_MODE ? null : <ApprovalCard key={message.id} card={message} onDecide={handleDecide} />;
                  }
                  return (
                    <AssistantMessage
                      key={message.id}
                      message={message}
                      onFeedback={IS_HARNESS_MODE ? undefined : handleFeedback}
                    />
                  );
                })}
                {isThinking ? (
                  <AssistantMessage pending activityText={activityText} message={{ id: "pending", time: clockTime() }} />
                ) : null}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          <footer className="chat-composer-shell">
            <div
              className={`chat-composer${composerExpanded ? " is-expanded" : ""}${
                attachment ? " has-attachment" : ""
              }`}
            >
              <input
                ref={fileInputRef}
                className="chat-file-input"
                type="file"
                accept={ATTACHMENT_ACCEPT}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = ""; // Selecting the same file after removal must fire change again.
                  readAttachment(file);
                }}
              />
              {attachment ? <AttachmentChip attachment={attachment} onRemove={removeAttachment} /> : null}
              {attachmentReading ? <p className="chat-composer-notice" role="status">正在读取附件… <button type="button" onClick={removeAttachment}>取消</button></p> : null}
              {attachmentError ? <p className="chat-composer-notice is-error" role="alert">{attachmentError}</p> : null}
              {cancellationState !== "idle" ? <p className={`chat-composer-notice${cancellationState === "failed" ? " is-error" : ""}`} role={cancellationState === "failed" ? "alert" : "status"}>
                {cancellationState === "pending" ? "正在停止本轮执行，确认后即可在当前会话继续。" : `${cancellationError} 请点击“重试停止”，确认前暂不能发送。`}
              </p> : null}
              <div className="chat-composer-controls">
                <button
                  className={`chat-composer-tool is-add${attachment ? " is-active" : ""}`}
                  type="button"
                  aria-label="添加附件"
                  title={IS_HARNESS_MODE ? "添加数据附件或分析图像" : "添加附件（在对话中入库）"}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Plus size={16} weight="bold" />
                </button>
                <textarea
                  ref={composerInputRef}
                  rows={1}
                  value={draft}
                  aria-label="输入你的问题"
                  placeholder={IS_HARNESS_MODE ? "输入问题，可直接粘贴截图或上传数据…" : "输入问题，可粘贴图片或上传附件…"}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={handleKeyDown}
                  onPaste={handleComposerPaste}
                />
                <ChatSendButton isThinking={isThinking} cancellationState={cancellationState} attachmentReading={attachmentReading}
                  hasContent={Boolean(draft.trim())} hasAttachment={Boolean(attachment)} onSend={() => sendMessage()} onStop={() => cancelCurrentTurn()} />
              </div>
            </div>
            <p>{IS_HARNESS_MODE ? "根据数据与执行证据回答；缺失或冲突的元数据会明确提示。" : "回答依据知识库证据生成；写操作都会先向你请求批准。"}</p>
          </footer>
        </section>

        <button
          className={`planner-edge-trigger${plannerOpen ? " is-hidden" : ""}${isThinking ? " is-live" : ""}`}
          type="button"
          aria-label="打开执行过程"
          aria-expanded={plannerOpen}
          onClick={() => setPlannerOpen(true)}
        >
          <PlannerNatureGlyph type="tree" />
          <span>过程</span>
          <i aria-hidden="true" />
        </button>

        <TimelineDrawer
          open={plannerOpen}
          onClose={() => setPlannerOpen(false)}
          timeline={timeline}
          activity={activity}
        />
      </div>

      {capabilityOpen ? (
        <div className="chat-capability-layer">
          <button
            className="chat-capability-backdrop"
            type="button"
            aria-label="关闭能力中心"
            onClick={() => setCapabilityOpen(false)}
          />
          <section
            className="chat-capability-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="capability-dialog-title"
          >
            <header>
              <span className="chat-capability-emblem" aria-hidden="true">
                <CirclesThreePlus size={22} weight="duotone" />
              </span>
              <div>
                <span>当前智能体</span>
                <h2 id="capability-dialog-title">能力中心</h2>
              </div>
              <button type="button" aria-label="关闭能力中心" onClick={() => setCapabilityOpen(false)}>
                <X size={18} />
              </button>
            </header>
            <div className="chat-capability-intro">
              <p>{activeAgent.name}</p>
              <span>在对话里直接描述目标，我会选择合适的能力完成。</span>
            </div>
            <div className="chat-capability-list">
              {activeAgent.capabilities.map(([title, body], index) => (
                <article key={title}>
                  <span className="chat-capability-index">{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <strong>{title}</strong>
                    <p>{body}</p>
                  </div>
                  <span className="chat-capability-status">
                    <i aria-hidden="true" />
                    可用
                  </span>
                </article>
              ))}
            </div>
            <footer>
              <span>{IS_HARNESS_MODE ? "先确认输入与分析范围，再执行并保留结果证据。" : "写操作（入库/替换/退役/图谱变更）都会先请求你的批准。"}</span>
              <button type="button" onClick={() => setCapabilityOpen(false)}>
                开始对话
                <ArrowUp size={14} weight="bold" aria-hidden="true" />
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </main></ArtifactProvider>
  );
}
