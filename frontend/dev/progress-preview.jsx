import React from "react";
import { createRoot } from "react-dom/client";
import { ToolCard, ToolGroup, TimelineDrawer } from "../src/components/AgentChat";
import { groupToolSteps, toolProgress, toolResultDetail } from "../src/lib/tool-progress";
import "../src/styles.css";

// Display fixtures only: this page never executes tools, uses models or touches chat history.
const make = (id, command, description, status, resultText = "") => ({ id, role: "tool", kind: "tool", name: "bash", args: { command, description }, argsText: JSON.stringify({ command, description }), status, resultText });
const cards = [
  make("locate1", "ls data", "定位输入数据", "done", "input.sio"),
  make("locate2", "ls .run", "定位已有分析结果", "done", "result.json"),
  make("inspect", ".venv/bin/python inspect_data.py execute --config analysis.json", "计算 PSD，观察能量集中的频率", "running"),
  make("partial", ".venv/bin/python inspect_data.py probe input.sio", "探查数据格式与采样条件", "partial", "采样率尚未确认\n[exit code: 2]"),
  make("failure", "python missing.py", "运行指定的处理脚本", "error", "No such file\n[exit code: 1]"),
  make("unknown", "custom_experiment --foo", "", "done", "custom output"),
];
const timeline = cards.map(card => ({ ...card, title: toolProgress(card).title, progress: toolProgress(card), detail: card.status === "running" ? "执行中" : toolResultDetail(card.resultText, card.status, card.name) }));
createRoot(document.getElementById("root")).render(<main className="chat-page" style={{ padding: 36, overflow: "auto" }}>
  <section style={{ maxWidth: 800 }}><h1>执行步骤隔离验证</h1><p>以下是明确标注的显示夹具，不执行命令、不调用模型、不读取会话。</p>
    <div style={{ display: "grid", gap: 12 }}>{groupToolSteps(cards).map(card => card.role === "tool-group" ? <ToolGroup key={card.id} group={card} /> : <ToolCard key={card.id} card={card} />)}</div>
  </section>
  <TimelineDrawer open onClose={() => {}} timeline={timeline} activity="working" />
</main>);
