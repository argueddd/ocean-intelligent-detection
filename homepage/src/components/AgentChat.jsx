import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowUp,
  Books,
  CaretDown,
  CaretRight,
  CheckCircle,
  CirclesThreePlus,
  ClockCounterClockwise,
  Copy,
  DotsThree,
  FileText,
  MagnifyingGlass,
  Microphone,
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

const ParticleStage = React.lazy(() => import("./ParticleStage"));

const starterHistory = [
  { id: "current", title: "投诉工单高频问题分析", time: "刚刚", active: true },
  { id: "history-1", title: "重点客户数据核验", time: "昨天" },
  { id: "history-2", title: "网络异常处置建议", time: "周五" },
  { id: "history-3", title: "经营周报提纲整理", time: "周三" },
];

const starterMessages = [
  {
    id: "user-1",
    role: "user",
    time: "10:32",
    content: "帮我检查昨天投诉工单里的高频问题，并给出处理建议。",
  },
  {
    id: "assistant-1",
    role: "assistant",
    time: "10:33",
    content:
      "我已经把任务拆成问题聚类、影响判断和处置建议三个部分。当前建议先确认工单数据范围，再由投诉分析能力完成归类，最后生成可执行的处置清单。",
    bullets: [
      "先按区域、问题类型和重复来电情况整理工单",
      "识别集中出现的问题，并关联网络告警和处理记录",
      "输出优先级、建议责任方和后续跟踪项",
    ],
    trace: ["理解任务", "读取工单", "归类问题", "组织建议"],
  },
];

const plannerBlueprint = [
  { id: "understand", title: "理解目标与约束", detail: "提取时间范围、分析目标和输出格式", depth: 0 },
  { id: "load", title: "读取投诉工单", detail: "载入昨日工单与关联处置记录", depth: 0 },
  { id: "cluster", title: "聚类高频问题", detail: "按区域、类型和重复来电归类", depth: 1 },
  { id: "signals", title: "关联网络告警", detail: "核对告警记录与历史处理结果", depth: 1 },
  { id: "recommend", title: "生成处置建议", detail: "整理优先级、责任方和跟踪项", depth: 0 },
  { id: "answer", title: "组织最终回答", detail: "形成可执行、可核验的任务清单", depth: 0 },
];

const plannerTree = [
  {
    id: "root",
    title: "投诉工单高频问题分析",
    detail: "从数据核验到处置建议",
    depth: 0,
    start: 0,
    end: 6,
    children: ["prepare", "analyze", "deliver"],
  },
  {
    id: "prepare",
    title: "准备分析范围",
    detail: "2 个步骤",
    depth: 1,
    parent: "root",
    start: 0,
    end: 2,
    children: ["understand", "load"],
  },
  { ...plannerBlueprint[0], depth: 2, parent: "prepare", step: 0 },
  { ...plannerBlueprint[1], depth: 2, parent: "prepare", step: 1 },
  {
    id: "analyze",
    title: "识别主要问题",
    detail: "2 个并行分析",
    depth: 1,
    parent: "root",
    start: 2,
    end: 4,
    children: ["cluster", "signals"],
  },
  { ...plannerBlueprint[2], depth: 2, parent: "analyze", step: 2 },
  { ...plannerBlueprint[3], depth: 2, parent: "analyze", step: 3 },
  {
    id: "deliver",
    title: "形成处理方案",
    detail: "2 个输出步骤",
    depth: 1,
    parent: "root",
    start: 4,
    end: 6,
    children: ["recommend", "answer"],
  },
  { ...plannerBlueprint[4], depth: 2, parent: "deliver", step: 4 },
  { ...plannerBlueprint[5], depth: 2, parent: "deliver", step: 5 },
];

const plannerParentIds = ["root", "prepare", "analyze", "deliver"];

function currentAgentFromLocation() {
  const id = new URLSearchParams(window.location.search).get("agent");
  return agents.find((agent) => agent.id === id) || agents[8];
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

function AssistantMessage({
  message,
  activity = "waiting",
  pending = false,
  onOpenPlanner,
  plannerStep = plannerBlueprint.length,
}) {
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState(null);

  const copyAnswer = async () => {
    const text = [message.content, ...(message.bullets || [])].filter(Boolean).join("\n");
    try {
      await navigator.clipboard?.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };

  const shareAnswer = async () => {
    const text = [message.content, ...(message.bullets || [])].filter(Boolean).join("\n");
    try {
      if (navigator.share) {
        await navigator.share({ title: "智能体回答", text });
        return;
      }
      await navigator.clipboard?.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };

  return (
    <article className={`chat-message-row is-assistant${pending ? " is-pending" : ""}`}>
      <RobotAvatar activity={activity} compact />
      <div className="chat-message-stack">
        <div className="chat-message-meta">
          <strong>智能助手</strong>
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
                <strong>{plannerBlueprint[Math.min(plannerStep, plannerBlueprint.length - 1)].title}</strong>
                <span>Planner 正在推进任务树</span>
              </div>
            </div>
          ) : (
            <>
              <p>{message.content}</p>
              {message.bullets?.length ? (
                <ul>
                  {message.bullets.map((item) => (
                    <li key={item}>
                      <CheckCircle size={17} weight="fill" aria-hidden="true" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
              {message.trace?.length ? (
                <div className="chat-runtime" aria-label="任务处理过程">
                  {message.trace.map((item, index) => (
                    <React.Fragment key={item}>
                      <span>
                        <i aria-hidden="true" />
                        {item}
                      </span>
                      {index < message.trace.length - 1 ? <CaretRight size={12} aria-hidden="true" /> : null}
                    </React.Fragment>
                  ))}
                  <button type="button" onClick={onOpenPlanner}>
                    <PlannerNatureGlyph type="tree" />
                    查看计划
                  </button>
                </div>
              ) : null}
            </>
          )}
        </div>
        {!pending ? (
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
              onClick={() => setFeedback(feedback === "up" ? null : "up")}
            >
              <ThumbsUp size={15} />
            </button>
            <button
              className={feedback === "down" ? "is-active" : ""}
              type="button"
              aria-label="回答需改进"
              aria-pressed={feedback === "down"}
              title="回答需改进"
              onClick={() => setFeedback(feedback === "down" ? null : "down")}
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

function PlannerNatureGlyph({ type = "sprout" }) {
  const glyphs = {
    tree: (
      <>
        <path className="planner-glyph-line planner-tree-trunk" d="M12 20V10.2m0 4.2-4-3.2m4 1.1 4.5-4" />
        <path className="planner-glyph-fill planner-tree-crown planner-tree-crown-left" d="M3.8 10.2C3.8 6.8 6.2 4.4 9.4 4.4c1.1-2 4.1-2.2 5.5-.4 3.2-.2 5.5 2.1 5.5 5 0 3.1-2.4 5.3-5.4 5.3H8.9c-3 0-5.1-1.6-5.1-4.1Z" />
        <path className="planner-glyph-line planner-tree-ground" d="M7.2 20.1h9.6" />
        <circle className="planner-glyph-result planner-tree-fruit" cx="8.2" cy="8.5" r="1.15" />
        <circle className="planner-glyph-result planner-tree-fruit" cx="15.8" cy="7.1" r="1.15" />
        <circle className="planner-glyph-result planner-tree-fruit" cx="13.9" cy="11.2" r="1" />
      </>
    ),
    branch: (
      <>
        <path
          className="planner-glyph-line planner-branch-stem"
          d="M3.2 21 11.8 12.6 21 3.2M8.5 15.8 4.4 12m8.7-.7-3.2-4.5m6.1 1.8 4.7-.5"
        />
        <path
          className="planner-glyph-fill planner-branch-leaf is-lower"
          d="M4.8 12.4C2.3 12.8.8 11.3.9 8.9c2.5-.3 4.2 1 3.9 3.5Z"
        />
        <path
          className="planner-glyph-fill planner-branch-leaf is-middle"
          d="M10.1 7.2C8 6.6 7.3 4.8 8.2 2.9c2.2.6 3 2.3 1.9 4.3Z"
        />
        <path
          className="planner-glyph-fill planner-branch-leaf is-upper"
          d="M20.1 8.2c.2-2.5 1.8-3.9 4.1-3.5-.2 2.5-1.7 4-4.1 3.5Z"
        />
        <path
          className="planner-glyph-fill planner-branch-leaf is-tip"
          d="M20.2 4.2c-.2-2 1-3.5 3-3.7.3 2-1 3.6-3 3.7Z"
        />
        <circle className="planner-glyph-result planner-branch-bloom" cx="11.8" cy="12.6" r="1.3" />
      </>
    ),
    seed: (
      <>
        <path className="planner-glyph-fill planner-seed-shell" d="M17.3 6.6c2.2 2.8.7 7.8-3.4 10.4-3.8 2.4-7.7 1-7.9-2.7-.2-3.2 3.7-7.2 8.3-8.2 1.3-.3 2.3-.1 3 .5Z" />
        <path className="planner-glyph-line planner-seed-line" d="M8.3 16.3c2.3-2.6 4.6-4.7 7.8-7" />
      </>
    ),
    sprout: (
      <>
        <path className="planner-glyph-line planner-leaf-stem" d="M11.8 20c-.1-4.8.8-8.9 4.5-12.6" />
        <path
          className="planner-glyph-fill planner-leaf planner-leaf-left"
          d="M11.5 13.8C7.2 14.2 4.1 11.5 4 7.2c4.4-.6 7.6 2.1 7.5 6.6Z"
        />
        <path
          className="planner-glyph-fill planner-leaf planner-leaf-right"
          d="M12.9 10.7c.4-3.8 3.3-6.3 7.1-6.1.1 3.9-2.8 6.6-7.1 6.1Z"
        />
        <circle className="planner-leaf-bud" cx="11.8" cy="19.7" r="1.15" />
      </>
    ),
    flower: (
      <>
        <path className="planner-glyph-line planner-flower-stem" d="M12 13v7m0-3.4c-1.7-1.1-3.2-1.2-4.5-.4" />
        <ellipse className="planner-flower-petal" cx="12" cy="7.4" rx="2.45" ry="3.45" />
        <ellipse className="planner-flower-petal" cx="15.5" cy="10.8" rx="3.45" ry="2.45" />
        <ellipse className="planner-flower-petal" cx="12" cy="14.1" rx="2.45" ry="3.45" />
        <ellipse className="planner-flower-petal" cx="8.5" cy="10.8" rx="3.45" ry="2.45" />
        <circle className="planner-flower-center" cx="12" cy="10.8" r="2" />
      </>
    ),
    fruit: (
      <>
        <path className="planner-glyph-line planner-fruit-stem" d="M12 8V4.5" />
        <path className="planner-fruit-leaf" d="M12.1 6.5c1-2.1 2.8-3 5.1-2.5-.7 2.2-2.5 3.1-5.1 2.5Z" />
        <path className="planner-fruit-body" d="M12 8.2c-3.2-2-6.7-.1-6.5 4.5.2 4.3 3 7.3 6.5 7.3s6.3-3 6.5-7.3c.2-4.6-3.3-6.5-6.5-4.5Z" />
      </>
    ),
  };

  return (
    <svg
      className={`planner-leaf-glyph planner-nature-glyph is-${type}`}
      viewBox="0 0 24 24"
      fill="none"
      role="presentation"
    >
      {glyphs[type] || glyphs.sprout}
    </svg>
  );
}

function plannerNodeGlyph(node, status) {
  if (node.id === "root") return "tree";
  if (node.children?.length) return "branch";
  if (status === "active") return "sprout";
  if (status === "done") return node.id === "recommend" || node.id === "answer" ? "fruit" : "flower";
  return "seed";
}

function PlannerDrawer({ open, onClose, step, activity }) {
  const finished = step >= plannerBlueprint.length;
  const idle = activity !== "working" && step === 0;
  const currentStep = Math.min(step + 1, plannerBlueprint.length);
  const progress = Math.round((Math.min(step, plannerBlueprint.length) / plannerBlueprint.length) * 100);
  const [expanded, setExpanded] = useState(() =>
    new Set(finished ? plannerParentIds : ["root"]),
  );
  const [selectedNode, setSelectedNode] = useState(null);

  useLayoutEffect(() => {
    if (idle) {
      setExpanded(new Set(["root"]));
      return;
    }

    if (finished) {
      setExpanded(new Set(plannerParentIds));
      return;
    }

    const activePhase = step < 2 ? "prepare" : step < 4 ? "analyze" : "deliver";
    setExpanded(new Set(["root", activePhase]));
  }, [finished, idle, step]);

  const nodeStatus = (node) => {
    if (idle) return "pending";
    if (typeof node.step === "number") {
      if (node.step < step) return "done";
      if (!finished && node.step === step) return "active";
      return "pending";
    }
    if (finished || step >= node.end) return "done";
    if (step >= node.start && step < node.end) return "active";
    return "pending";
  };

  const isVisible = (node) => {
    let parentId = node.parent;
    while (parentId) {
      if (!expanded.has(parentId)) return false;
      parentId = plannerTree.find((candidate) => candidate.id === parentId)?.parent;
    }
    return true;
  };

  const summaryLabel = idle
    ? "等待生成执行计划"
    : finished
      ? "本轮计划已完成"
      : `当前执行 ${currentStep} / ${plannerBlueprint.length}`;
  const summaryTitle = idle
    ? "输入任务后逐层展开"
    : finished
      ? "所有步骤已完成"
      : plannerBlueprint[Math.min(step, plannerBlueprint.length - 1)].title;

  return (
    <aside
      className={`chat-planner-drawer${open ? " is-open" : ""}`}
      aria-label="任务执行计划"
      aria-hidden={!open}
    >
      <header className="planner-heading">
        <div className="planner-heading-main">
          <span className="planner-heading-emblem" aria-hidden="true">
            <PlannerNatureGlyph type="tree" />
          </span>
          <div className="planner-heading-copy">
            <span>PLANNER</span>
            <h2>执行计划</h2>
          </div>
        </div>
        <button type="button" aria-label="收起执行计划" title="收起" onClick={onClose}>
          <X size={18} />
        </button>
      </header>

      <section className={`planner-overview is-${activity}`} aria-label="计划执行概览">
        <span className={`planner-summary-mark is-${idle ? "idle" : finished ? "done" : "active"}`} aria-hidden="true">
          <PlannerNatureGlyph type={idle ? "seed" : finished ? "fruit" : "sprout"} />
        </span>
        <div className="planner-overview-copy">
          <span>{summaryLabel}</span>
          <strong>{summaryTitle}</strong>
          <div
            className="planner-progress"
            role="progressbar"
            aria-label="计划完成进度"
            aria-valuemin="0"
            aria-valuemax="100"
            aria-valuenow={progress}
          >
            <i style={{ width: `${progress}%` }} />
          </div>
        </div>
      </section>

      <ol className="planner-tree" aria-label="任务树">
        {plannerTree.filter(isVisible).map((node, index) => {
          const status = nodeStatus(node);
          const hasChildren = Boolean(node.children?.length);
          const isExpanded = hasChildren && expanded.has(node.id);
          const glyphType = plannerNodeGlyph(node, status);
          const statusLabel = status === "done" ? "完成" : status === "active" ? "执行中" : "等待";
          const completedChildren = hasChildren
            ? Math.min(Math.max(step - node.start, 0), node.end - node.start)
            : 0;
          return (
            <li
              className={`planner-tree-item is-${status} is-depth-${node.depth}${node.id === "root" ? " is-root" : ""}${selectedNode === node.id ? " is-selected" : ""}`}
              key={node.id}
              style={{ "--planner-order": index, "--tree-depth": node.depth }}
            >
              <button
                className="planner-tree-row"
                type="button"
                aria-expanded={hasChildren ? isExpanded : undefined}
                onClick={() => {
                  if (hasChildren) {
                    setExpanded((current) => {
                      const next = new Set(current);
                      if (next.has(node.id)) next.delete(node.id);
                      else next.add(node.id);
                      return next;
                    });
                  } else {
                    setSelectedNode((current) => (current === node.id ? null : node.id));
                  }
                }}
              >
                <span
                  className={`planner-disclosure${hasChildren ? " has-children" : ""}${isExpanded ? " is-expanded" : ""}`}
                  aria-hidden="true"
                >
                  {hasChildren ? <CaretRight size={13} weight="bold" /> : null}
                </span>
                <span
                  className={`planner-node-mark is-glyph is-glyph-${glyphType}${hasChildren ? " is-branch" : ""}`}
                  aria-hidden="true"
                >
                  <PlannerNatureGlyph type={glyphType} />
                </span>
                <span className="planner-node-copy">
                  <strong>{node.title}</strong>
                  <small>{node.detail}</small>
                </span>
                <span className="planner-node-meta">
                  {hasChildren ? `${completedChildren}/${node.end - node.start}` : statusLabel}
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      <footer className="planner-footer">
        <span className={`planner-live is-${activity}`} aria-hidden="true" />
        <span>{idle ? "等待新任务" : finished ? "计划已完成 · 同步本轮回答" : "当前分支随执行更新"}</span>
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

export default function AgentChat() {
  const activeAgent = useMemo(currentAgentFromLocation, []);
  const [history, setHistory] = useState(starterHistory);
  const [messages, setMessages] = useState(starterMessages);
  const [draft, setDraft] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [attachment, setAttachment] = useState(null);
  const [isThinking, setIsThinking] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [plannerOpen, setPlannerOpen] = useState(false);
  const [capabilityOpen, setCapabilityOpen] = useState(false);
  const [composerExpanded, setComposerExpanded] = useState(false);
  const [voiceActive, setVoiceActive] = useState(false);
  const [plannerStep, setPlannerStep] = useState(plannerBlueprint.length);
  const messagesEndRef = useRef(null);
  const responseTimerRef = useRef(null);
  const plannerTimerRef = useRef(null);
  const fileInputRef = useRef(null);
  const composerInputRef = useRef(null);

  const activity = isThinking ? "working" : attachment ? "reading" : "waiting";
  const activityLabel = isThinking ? "正在执行计划" : attachment ? "附件已准备" : "在线，可以开始";

  const quickPrompts = useMemo(
    () => [
      `分析${activeAgent.capabilities[0][0]}并给出建议`,
      `整理${activeAgent.capabilities[1][0]}的关键结论`,
      `生成一份${activeAgent.role}任务清单`,
    ],
    [activeAgent],
  );

  const visibleHistory = useMemo(() => {
    const query = historyQuery.trim().toLowerCase();
    return query ? history.filter((item) => item.title.toLowerCase().includes(query)) : history;
  }, [history, historyQuery]);

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
    document.title = "智能体对话 | 智能体中枢";
    return () => {
      document.title = previousTitle;
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isThinking, plannerStep]);

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

  useEffect(
    () => () => {
      if (responseTimerRef.current) window.clearTimeout(responseTimerRef.current);
      if (plannerTimerRef.current) window.clearInterval(plannerTimerRef.current);
    },
    [],
  );

  const clearRunningTimers = () => {
    if (responseTimerRef.current) window.clearTimeout(responseTimerRef.current);
    if (plannerTimerRef.current) window.clearInterval(plannerTimerRef.current);
    responseTimerRef.current = null;
    plannerTimerRef.current = null;
  };

  const stopResponse = () => {
    clearRunningTimers();
    setIsThinking(false);
    setMessages((items) => [
      ...items,
      {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        time: clockTime(),
        content: "已停止生成。你可以补充范围、数据来源或期望的输出格式后继续。",
      },
    ]);
  };

  const sendMessage = (preset) => {
    const typedContent = (typeof preset === "string" ? preset : draft).trim();
    const content = typedContent || (attachment ? `请分析附件：${attachment}` : "");
    if (!content || isThinking) return;

    clearRunningTimers();
    const timestamp = Date.now();
    setMessages((items) => [
      ...items,
      { id: `user-${timestamp}`, role: "user", time: clockTime(), content },
    ]);
    setDraft("");
    setAttachment(null);
    setVoiceActive(false);
    setPlannerStep(0);
    setIsThinking(true);

    plannerTimerRef.current = window.setInterval(() => {
      setPlannerStep((current) => Math.min(current + 1, plannerBlueprint.length - 1));
    }, 620);

    responseTimerRef.current = window.setTimeout(() => {
      if (plannerTimerRef.current) window.clearInterval(plannerTimerRef.current);
      plannerTimerRef.current = null;
      setPlannerStep(plannerBlueprint.length);
      setMessages((items) => [
        ...items,
        {
          id: `assistant-${timestamp}`,
          role: "assistant",
          time: clockTime(),
          content: `我会把这个任务交给${activeAgent.name}处理。建议先明确数据范围和期望结果，再按下面的顺序推进。`,
          bullets: activeAgent.capabilities.slice(0, 3).map(([title, body]) => `${title}：${body}`),
          trace: ["理解任务", "调用能力", "生成结果"],
        },
      ]);
      setIsThinking(false);
      responseTimerRef.current = null;
    }, 3900);
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      sendMessage();
    }
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
            <a className="chat-home-link" href={`/?agent=${activeAgent.id}`} aria-label="返回智能体首页">
              <span className="chat-home-arrow" aria-hidden="true">
                <ArrowLeft size={16} weight="bold" />
              </span>
              <BrandMark />
              <span className="chat-home-copy">
                <strong>智能体首页</strong>
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
                <StackSimple size={18} weight="duotone" />
              </span>
              <span>
                <strong>任务模板</strong>
                <small>位置预留</small>
              </span>
            </button>
            <button className="is-placeholder" type="button" disabled>
              <span className="chat-sidebar-tool-icon" aria-hidden="true">
                <Books size={18} weight="duotone" />
              </span>
              <span>
                <strong>知识资料</strong>
                <small>位置预留</small>
              </span>
            </button>
          </nav>

          <div className="chat-history-heading">
            <span>历史对话</span>
            <small>{history.length} 项</small>
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
                className={item.active ? "is-active" : ""}
                type="button"
                key={item.id}
                onClick={() => {
                  setHistory((items) =>
                    items.map((candidate) => ({ ...candidate, active: candidate.id === item.id })),
                  );
                  setMessages(
                    item.id === "current"
                      ? starterMessages
                      : [
                          { id: `${item.id}-user`, role: "user", time: "历史", content: item.title },
                          {
                            id: `${item.id}-assistant`,
                            role: "assistant",
                            time: "历史",
                            content: `这是「${item.title}」的历史对话预览。当前原型已经保留消息结构，接入会话接口后会读取完整内容。`,
                            trace: ["载入会话", "恢复上下文", "等待继续"],
                          },
                        ],
                  );
                  setPlannerStep(plannerBlueprint.length);
                  setHistoryOpen(false);
                }}
              >
                <span className="chat-history-icon" aria-hidden="true">
                  <ClockCounterClockwise size={16} />
                </span>
                <span className="chat-history-copy">
                  <strong>{item.title}</strong>
                  <small>{item.time}</small>
                </span>
                <DotsThree size={18} weight="bold" aria-hidden="true" />
              </button>
            ))}
            {!visibleHistory.length ? <p className="chat-history-empty">没有找到相关对话。</p> : null}
          </nav>
          <div className="chat-history-footer">
            <span>
              <FileText size={16} weight="duotone" aria-hidden="true" />
              对话会自动保存
            </span>
            <button type="button" aria-label="清理历史对话" title="清理历史对话" onClick={() => setHistory([])}>
              <Trash size={16} />
            </button>
          </div>
        </aside>

        <section className="chat-main" aria-label="智能体对话内容">
          <header className="chat-agent-header">
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
                <h2 id="chat-welcome-title">今天想完成什么？</h2>
                <p>描述目标、资料和期望结果，我会组织合适的能力完成任务。</p>
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
                {messages.map((message) =>
                  message.role === "user" ? (
                    <UserMessage key={message.id} message={message} />
                  ) : (
                    <AssistantMessage
                      key={message.id}
                      message={message}
                      onOpenPlanner={() => setPlannerOpen(true)}
                    />
                  ),
                )}
                {isThinking ? (
                  <AssistantMessage
                    pending
                    activity="working"
                    plannerStep={plannerStep}
                    onOpenPlanner={() => setPlannerOpen(true)}
                    message={{ id: "pending", time: clockTime() }}
                  />
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
                onChange={(event) => setAttachment(event.target.files?.[0]?.name || null)}
              />
              {attachment ? (
                <div className="chat-attachment-chip">
                  <span className="chat-attachment-icon" aria-hidden="true">
                    <FileText size={15} weight="duotone" />
                  </span>
                  <span>{attachment}</span>
                  <button type="button" aria-label={`移除 ${attachment}`} onClick={() => setAttachment(null)}>
                    <X size={13} />
                  </button>
                </div>
              ) : null}
              <div className="chat-composer-controls">
                <button
                  className={`chat-composer-tool is-add${attachment ? " is-active" : ""}`}
                  type="button"
                  aria-label="添加附件"
                  title="添加附件"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Plus size={16} weight="bold" />
                </button>
                <textarea
                  ref={composerInputRef}
                  rows={1}
                  value={draft}
                  aria-label="输入你的问题"
                  placeholder={voiceActive ? "正在聆听…" : "描述任务，或粘贴资料与链接…"}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={handleKeyDown}
                />
                <button
                  className="chat-composer-route"
                  type="button"
                  aria-label="选择智能体能力"
                  onClick={() => setCapabilityOpen(true)}
                >
                  自动路由
                  <CaretDown size={11} weight="bold" aria-hidden="true" />
                </button>
                <button
                  className={`chat-composer-tool is-voice${voiceActive ? " is-listening" : ""}`}
                  type="button"
                  aria-label={voiceActive ? "停止语音输入" : "开始语音输入"}
                  aria-pressed={voiceActive}
                  title="语音输入"
                  onClick={() => setVoiceActive((current) => !current)}
                >
                  {voiceActive ? (
                    <span className="chat-voice-wave" aria-hidden="true">
                      <i />
                      <i />
                      <i />
                    </span>
                  ) : (
                    <Microphone size={16} weight="duotone" />
                  )}
                </button>
                <button
                  className={`chat-send-button${isThinking ? " is-stopping" : ""}`}
                  type="button"
                  disabled={!isThinking && !draft.trim() && !attachment}
                  aria-label={isThinking ? "停止生成" : "发送消息"}
                  title={isThinking ? "停止生成" : "发送消息"}
                  onClick={isThinking ? stopResponse : () => sendMessage()}
                >
                  {isThinking ? <StopCircle size={16} weight="fill" /> : <ArrowUp size={15} weight="bold" />}
                </button>
              </div>
            </div>
            <p>回答内容由智能体生成，请结合业务规则核验。</p>
          </footer>
        </section>

        <button
          className={`planner-edge-trigger${plannerOpen ? " is-hidden" : ""}${isThinking ? " is-live" : ""}`}
          type="button"
          aria-label="打开执行计划"
          aria-expanded={plannerOpen}
          onClick={() => setPlannerOpen(true)}
        >
          <PlannerNatureGlyph type="tree" />
          <span>计划</span>
          <i aria-hidden="true" />
        </button>

        <PlannerDrawer
          open={plannerOpen}
          onClose={() => setPlannerOpen(false)}
          step={plannerStep}
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
              <span>以下能力会根据任务意图自动参与路由与编排。</span>
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
              <span>直接在对话中描述目标，系统会自动选择并组合能力。</span>
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
