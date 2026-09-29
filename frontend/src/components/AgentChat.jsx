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
} from "../lib/api";
import { Markdown } from "../lib/markdown";

const ParticleStage = React.lazy(() => import("./ParticleStage"));

const kbAgent = agents[0];

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

/** 时间线条目用的结果摘要：首段非空文本，截 64 字。 */
function resultSummary(text, isError) {
  const line =
    String(text || "")
      .split("\n")
      .map((s) => s.trim())
      .find(Boolean) || "";
  const short = line.length > 64 ? `${line.slice(0, 63)}…` : line;
  if (isError) return `失败${short ? `：${short}` : ""}`;
  return short || "返回空结果";
}

/** 尝试把工具结果文本解析为 JSON（dsh-knowledge 工具结果多为 JSON）。 */
function resultJsonOf(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** 工具的中文名与图标语义。 */
const TOOL_LABELS = {
  lightrag_query_data: "知识检索",
  kb_ingest: "文档入库",
  kb_update: "知识更新",
  kb_status: "健康状态",
  kb_analyze: "知识库体检",
  kb_report: "运营报告",
  kb_graph_search: "图谱检索",
  kb_feedback_inbox: "反馈收件箱",
  kb_feedback_context: "反馈上下文",
  kb_diagnosis_submit: "诊断提交",
};

function toolLabel(name) {
  return TOOL_LABELS[name] || name;
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

function ToolCard({ card }) {
  const [open, setOpen] = useState(false);
  const label = toolLabel(card.name);
  const running = card.status === "running";
  const json = card.resultJson;

  return (
    <article className={`chat-tool-card is-${card.status}${open ? " is-open" : ""}`}>
      <button className="chat-tool-head" type="button" onClick={() => setOpen((v) => !v)}>
        <span className="chat-tool-spin" aria-hidden="true">
          {running ? <React.Fragment><i /><i /><i /></React.Fragment> : <CheckCircle size={14} weight="fill" />}
        </span>
        <strong>{label}</strong>
        <span className="chat-tool-brief">{toolBrief(card)}</span>
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

      {open ? (
        <div className="chat-tool-body">
          {card.argsText ? <pre className="chat-tool-io">{card.argsText}</pre> : null}
          {card.resultText ? <pre className="chat-tool-io">{card.resultText.slice(0, 2400)}</pre> : null}
        </div>
      ) : null}

      {card.status === "error" && card.resultText ? (
        <p className="chat-tool-error">{card.resultText.slice(0, 300)}</p>
      ) : null}
    </article>
  );
}

function toolBrief(card) {
  const args = card.args || {};
  if (card.name === "lightrag_query_data") return args.query ? String(args.query).slice(0, 26) : "检索知识库";
  if (card.name === "kb_ingest") return args.kind === "file" ? `入库：${args.title || args.file_path || ""}`.slice(0, 30) : `入库：${args.title || "文本"}`;
  if (card.name === "kb_update") return `更新：${args.action || ""}${args.entity_name ? " · " + args.entity_name : ""}`.slice(0, 30);
  if (card.name === "kb_graph_search") return args.label || args.query || "图谱检索";
  if (card.name === "kb_status") return "知识库健康";
  if (card.name === "kb_analyze") return "健康分析";
  if (card.name === "kb_report") return `近 ${args.days || 7} 天运营`;
  return card.status === "running" ? "执行中…" : card.status === "error" ? "执行失败" : "已完成";
}

/* ---------------------------------------------------------------- 审批卡 */

function ApprovalCard({ card, onDecide }) {
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

function AssistantMessage({ message, onFeedback, onGrow, pending = false, activityText = "" }) {
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState(null);

  const fullText = message.content || "";

  /** 打字机渐显：新回答整段到达后逐字展开（历史/错误消息 instant 直出）。 */
  const [shown, setShown] = useState(() => (message.instant ? fullText.length : 0));
  const timerRef = useRef(null);
  useEffect(() => {
    if (message.instant || pending) return undefined;
    let cancelled = false;
    let current = 0;
    const total = fullText.length;
    const tick = () => {
      if (cancelled) return;
      current = Math.min(total, current + Math.max(2, Math.ceil((total - current) / 90)));
      setShown(current);
      if (current < total) {
        timerRef.current = window.setTimeout(tick, 16);
      }
    };
    timerRef.current = window.setTimeout(tick, 16);
    return () => {
      cancelled = true;
      window.clearTimeout(timerRef.current);
    };
    // 仅挂载时启动一次：整条消息的 content 到达后不会再变。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => () => window.clearTimeout(timerRef.current), []);
  const growing = shown < fullText.length;
  useEffect(() => {
    if (growing) onGrow?.();
  }, [shown, growing, onGrow]);

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
        await navigator.share({ title: "知识库助手回答", text: fullText });
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
          <strong>知识库助手</strong>
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
                <span>检索证据与执行过程实时可见</span>
              </div>
            </div>
          ) : (
            <Markdown className={growing ? "is-growing" : ""}>{fullText.slice(0, shown)}</Markdown>
          )}
        </div>
        {!pending && fullText && !growing ? (
          <div className="chat-message-actions" aria-label="消息操作">
            <button
              type="button"
              aria-label={copied ? "回答已复制" : "复制回答"}
              title={copied ? "已复制" : "复制回答"}
              onClick={copyAnswer}
            >
              <Copy size={15} />
            </button>
            <button
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
            </button>
            <button type="button" aria-label="分享回答" title="分享回答" onClick={shareAnswer}>
              <ShareNetwork size={15} />
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
}

function UserMessage({ message }) {
  return (
    <article className="chat-message-row is-user">
      <div className="chat-message-stack">
        <div className="chat-message-meta">
          <strong>你</strong>
          <time>{message.time}</time>
        </div>
        <div className="chat-user-content">{message.content}</div>
      </div>
      <span className="chat-user-avatar" aria-hidden="true">
        <UserCircle size={26} weight="duotone" />
      </span>
    </article>
  );
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

function TimelineDrawer({ open, onClose, timeline, activity }) {
  const finished = activity !== "working";
  const progress = Math.min(95, timeline.length * 12);

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
          <span>{finished ? "本轮执行已完成" : "正在执行"}</span>
          <strong>{timeline.length ? `${timeline.length} 项操作` : "等待新任务"}</strong>
          <div className="planner-progress" role="progressbar" aria-label="执行进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow={progress}>
            <i style={{ width: `${progress}%` }} />
          </div>
        </div>
      </section>

      <ol className="chat-timeline" aria-label="执行时间线">
        {timeline.length ? (
          timeline.map((item) => (
            <li key={item.id} className={`chat-timeline-item is-${item.kind} is-${item.status || "info"}`}>
              <span className="chat-timeline-dot" aria-hidden="true" />
              <div className="chat-timeline-body">
                <strong>{item.title}</strong>
                {item.detail ? <p className="chat-timeline-detail">{item.detail}</p> : null}
              </div>
            </li>
          ))
        ) : (
          <li className="chat-timeline-item is-empty">发送消息后，这里会实时展示工具调用与审批过程。</li>
        )}
      </ol>

      <footer className="planner-footer">
        <span className={`planner-live is-${activity}`} aria-hidden="true" />
        <span>{finished ? "等待下一条消息" : "工具调用与审批实时同步"}</span>
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

  const activity = isThinking ? "working" : attachment ? "reading" : "waiting";
  const activityLabel = isThinking ? activityText || "正在执行" : attachment ? "附件已准备" : "在线，可以开始";

  const quickPrompts = [
    "知识库里有哪些关于报销的制度？",
    "做一次知识库体检，看看有什么问题",
    "知识库当前健康状态如何？",
    "帮我看看「报销」相关的知识图谱",
  ];

  const visibleHistory = useMemo(() => {
    const query = historyQuery.trim().toLowerCase();
    return query ? sessions.filter((item) => item.title.toLowerCase().includes(query)) : sessions;
  }, [sessions, historyQuery]);

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
    document.title = "知识库助手 | 对话工作台";
    return () => {
      document.title = previousTitle;
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isThinking]);

  /** 打字机展开期间的跟随滚动（auto 平滑无效化，避免高频 smooth 抖动）。 */
  const scrollDuringTyping = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, []);

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

  useEffect(() => () => abortRef.current?.(), []);

  const timelineIdRef = useRef(0);
  const timelineCallRef = useRef(new Map());
  const timelineApprovalRef = useRef(new Map());

  /** 追加一条过程项（tool/approval/error），返回条目 id 供后续更新状态。 */
  const pushTimelineItem = useCallback((item) => {
    const id = `tl-${++timelineIdRef.current}`;
    setTimeline((items) => [...items.slice(-80), { id, time: clockTime(), ...item }]);
    return id;
  }, []);

  /** 审批决定：用 callId 匹配审批桥的 pending 记录再提交。 */
  const handleDecide = useCallback(async (card, decision) => {
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
      setActivityText("正在推理");
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
      let args = {};
      try {
        args = JSON.parse(data.arguments || "{}");
      } catch { /* 模型产生的 arguments 解析失败按空对象展示 */ }
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
      setActivityText(`正在调用 ${toolLabel(data.name)}`);
      const argsDetail = args.query
        ? String(args.query).slice(0, 32)
        : args.action
          ? String(args.action)
          : "";
      const tlId = pushTimelineItem({
        kind: "tool",
        title: `${toolLabel(data.name)}${argsDetail ? `：${argsDetail}` : ""}`,
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
            ? { ...m, status: isError ? "error" : "done", resultText: text, resultJson: json }
            : m,
        ),
      );
      const tlId = callId ? timelineCallRef.current.get(callId) : null;
      if (tlId) {
        setTimeline((items) =>
          items.map((it) =>
            it.id === tlId ? { ...it, status: isError ? "error" : "done", detail: resultSummary(text, isError) } : it,
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
    pendingUserTextRef.current = null;
    currentQueryIdRef.current = null;
  }, []);

  const sendMessage = (preset) => {
    const typedContent = (typeof preset === "string" ? preset : draft).trim();
    if (!typedContent && !attachment) return;
    if (isThinking) return;

    const content = typedContent || `请处理附件：${attachment.name}`;
    const timestamp = Date.now();

    currentUserTextRef.current = content;
    pendingUserTextRef.current = content;
    currentQueryIdRef.current = null;
    sessionSeqRef.current += 1;

    setMessages((items) => [
      ...items,
      { id: `user-${timestamp}`, role: "user", time: clockTime(), content },
    ]);
    setDraft("");
    setAttachment(null);
    setIsThinking(true);
    setTimeline([]);
    timelineCallRef.current.clear();
    timelineApprovalRef.current.clear();

    const attachmentPayload = attachment
      ? [{ name: attachment.name, data: attachment.data }]
      : undefined;

    abortRef.current = streamChat(
      { sessionId, message: content, attachments: attachmentPayload },
      {
        onStart: (id) => {
          setSessionId(id);
          setSessions(upsertSession(id, content));
        },
        onRenamed: ({ from, to }) => {
          setSessionId(to);
          setSessions(renameSession(from, to));
          setMessages((items) => [
            ...items,
            {
              id: `renamed-${to}`,
              role: "assistant",
              time: clockTime(),
              content: "服务已重启，本会话已迁移到新会话继续。之前的上下文不会自动延续，如需引用请重新说明。",
            },
          ]);
        },
        onNotification: handleNotification,
        onDone: () => resetTurnState(),
        onError: (message) => {
          resetTurnState();
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
        },
      },
    );
  };

  const stopResponse = () => {
    abortRef.current?.();
    resetTurnState();
    setMessages((items) => [
      ...items,
      {
        id: `stopped-${Date.now()}`,
        role: "assistant",
        time: clockTime(),
        content: "已停止接收本轮输出。服务端的执行会自然结束，你可以继续提问。",
      },
    ]);
  };

  const startNewChat = () => {
    stopResponseSilently();
    setSessionId(null);
    setMessages([]);
    setTimeline([]);
    timelineCallRef.current.clear();
    timelineApprovalRef.current.clear();
    setHistoryOpen(false);
  };

  const stopResponseSilently = () => {
    abortRef.current?.();
    resetTurnState();
  };

  const resumeSession = async (item) => {
    stopResponseSilently();
    setSessionId(item.sessionId);
    setMessages([]);
    setTimeline([]);
    setHistoryOpen(false);
    const events = await fetchChatHistory(item.sessionId);
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
    setMessages(
      events.map((e) => {
        const time = typeof e.time === "number" ? wallTime(e.time) : clockTime();
        switch (e.kind) {
          case "user":
            return { id: `h-u-${e.seq}`, role: "user", time, content: e.text };
          case "assistant":
            return { id: `h-a-${e.seq}`, role: "assistant", time, content: e.text, instant: true };
          case "thinking":
            return { id: `h-t-${e.seq}`, role: "thinking", time, content: e.text };
          case "tool": {
            let args = {};
            try {
              args = JSON.parse(e.argsText || "{}");
            } catch {
              /* 历史 arguments 解析失败按空对象展示 */
            }
            return {
              id: `h-tool-${e.seq}`,
              role: "tool",
              callId: e.callId,
              name: e.name,
              args,
              argsText: e.argsText,
              status: e.status || "done",
              resultText: e.resultText || "",
              resultJson: null,
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
      }).filter(Boolean),
    );
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

  const readAttachment = (file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setAttachment({ name: file.name, data: String(reader.result || "").split(",")[1] || "" });
    reader.readAsDataURL(file);
  };

  return (
    <main className={`chat-page${isThinking ? " is-working" : ""}`}>
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
            <a className="chat-home-link" href="/" aria-label="返回知识库助手首页">
              <span className="chat-home-arrow" aria-hidden="true">
                <ArrowLeft size={16} weight="bold" />
              </span>
              <BrandMark />
              <span className="chat-home-copy">
                <strong>知识库助手</strong>
                <small>返回门户</small>
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
            <button className="is-placeholder" type="button" disabled>
              <span className="chat-sidebar-tool-icon" aria-hidden="true">
                <Books size={18} weight="duotone" />
              </span>
              <span>
                <strong>知识资料</strong>
                <small>在对话中上传</small>
              </span>
            </button>
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
                <h1>{kbAgent.name}</h1>
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
                <ParticleStage shape={kbAgent.shape} />
              </React.Suspense>
            </div>
            {!messages.length ? (
              <section className="chat-welcome" aria-labelledby="chat-welcome-title">
                <RobotAvatar activity={activity} hero />
                <p className="chat-welcome-label">{kbAgent.role}</p>
                <h2 id="chat-welcome-title">今天想了解或整理什么？</h2>
                <p>可以直接提问知识内容、上传文档入库、编辑知识图谱，或让我做一次知识库体检。</p>
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
                {messages.map((message) => {
                  if (message.role === "user") return <UserMessage key={message.id} message={message} />;
                  if (message.role === "thinking") return <ThinkingCard key={message.id} message={message} />;
                  if (message.role === "tool") return <ToolCard key={message.id} card={message} />;
                  if (message.role === "approval") {
                    return <ApprovalCard key={message.id} card={message} onDecide={handleDecide} />;
                  }
                  return (
                    <AssistantMessage
                      key={message.id}
                      message={message}
                      onFeedback={handleFeedback}
                      onGrow={scrollDuringTyping}
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
                onChange={(event) => readAttachment(event.target.files?.[0])}
              />
              {attachment ? (
                <div className="chat-attachment-chip">
                  <span className="chat-attachment-icon" aria-hidden="true">
                    <FileText size={15} weight="duotone" />
                  </span>
                  <span>{attachment.name}</span>
                  <button type="button" aria-label={`移除 ${attachment.name}`} onClick={() => setAttachment(null)}>
                    <X size={13} />
                  </button>
                </div>
              ) : null}
              <div className="chat-composer-controls">
                <button
                  className={`chat-composer-tool is-add${attachment ? " is-active" : ""}`}
                  type="button"
                  aria-label="添加附件"
                  title="添加附件（在对话中入库）"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Plus size={16} weight="bold" />
                </button>
                <textarea
                  ref={composerInputRef}
                  rows={1}
                  value={draft}
                  aria-label="输入你的问题"
                  placeholder="提问知识内容，或描述治理任务（上传/编辑/体检）…"
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={handleKeyDown}
                />
                <button
                  className={`chat-send-button${isThinking ? " is-stopping" : ""}`}
                  type="button"
                  disabled={!isThinking && !draft.trim() && !attachment}
                  aria-label={isThinking ? "停止接收" : "发送消息"}
                  title={isThinking ? "停止接收" : "发送消息"}
                  onClick={isThinking ? stopResponse : () => sendMessage()}
                >
                  {isThinking ? <StopCircle size={16} weight="fill" /> : <ArrowUp size={15} weight="bold" />}
                </button>
              </div>
            </div>
            <p>回答依据知识库证据生成；写操作都会先向你请求批准。</p>
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
              <p>{kbAgent.name}</p>
              <span>在对话里直接描述目标，我会选择合适的能力完成。</span>
            </div>
            <div className="chat-capability-list">
              {kbAgent.capabilities.map(([title, body], index) => (
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
              <span>写操作（入库/替换/退役/图谱变更）都会先请求你的批准。</span>
              <button type="button" onClick={() => setCapabilityOpen(false)}>
                开始对话
                <ArrowUp size={14} weight="bold" aria-hidden="true" />
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </main>
  );
}
