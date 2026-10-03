// A development-only fixture. Every /api request is mocked before the real chat UI mounts.
// Use an isolated browser context; no model, SDK or backend session is touched.
import React from "react";
import { createRoot } from "react-dom/client";
import AgentChat from "../src/components/AgentChat";
import "../src/styles.css";

const encoder = new TextEncoder();
const pendingStreams = new Map();
const records = [];
let pendingCancel = null;
let sequence = 0;
const frame = (event, data) => encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
function emit(controller, event, data) { try { controller.enqueue(frame(event, data)); } catch { /* Explicit frontend detach closes its reader. */ } }
function finishCancel(fail = false) {
  if (!pendingCancel) return;
  const { body, resolve } = pendingCancel;
  pendingCancel = null;
  if (!fail) pendingStreams.delete(body.requestId);
  resolve(fail ? json({ ok: false, error: "模拟：SDK 尚未空闲" }, 503) : json({ ok: true, cancelled: true, requestId: body.requestId, sessionId: body.sessionId || `qa-${body.requestId}` }));
}
window.__chatInputQa = {
  records,
  finishCancel,
  finishAnswer() {
    const task = [...pendingStreams.values()].at(-1);
    if (!task) return;
    emit(task.controller, "notification", { method: "session.event", params: { event: { type: "assistant/message", seq: ++sequence, data: { message: { content: [{ type: "text", text: "已结合你的问题解读上传图片。\n\n这是隔离 UI 验证，末尾文字应立即完整显示。" }] } } } } });
    emit(task.controller, "done", { sessionId: task.sessionId });
    try { task.controller.close(); } catch { /* Detached. */ }
    pendingStreams.delete(task.requestId);
  },
};
const memoryStorage = new Map();
Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: key => memoryStorage.get(key) || null, setItem: (key, value) => memoryStorage.set(key, value), removeItem: key => memoryStorage.delete(key) } });
window.fetch = async (url, options = {}) => {
  const path = String(url);
  if (path === "/api/chat/stream") {
    const body = JSON.parse(options.body);
    records.push({ path, requestId: body.requestId, sessionId: body.sessionId || null, message: body.message,
      attachments: body.attachments?.map(({ data, ...metadata }) => ({ ...metadata, base64Bytes: data.length })) || [] });
    const sessionId = body.sessionId || `qa-${body.requestId}`;
    return new Response(new ReadableStream({ start(controller) {
      pendingStreams.set(body.requestId, { requestId: body.requestId, sessionId, controller });
      emit(controller, "start", { requestId: body.requestId, sessionId });
      if (body.attachments?.some(item => item.kind === "image")) emit(controller, "phase", { message: "正在解读上传图片" });
      else emit(controller, "notification", { method: "session.event", params: { event: { type: "tool/call", seq: ++sequence, data: { callId: `qa-call-${sequence}`, name: "bash", arguments: JSON.stringify({ command: "python mock_analysis.py", description: "计算 PSD 并保存数值结果" }) } } } });
    } }));
  }
  if (path === "/api/chat/cancel") {
    const body = JSON.parse(options.body); records.push({ path, ...body });
    return new Promise(resolve => { pendingCancel = { body, resolve }; });
  }
  if (path.startsWith("/api/chat/history")) return json({ events: [] });
  if (path === "/api/approvals/pending") return json({ pending: [] });
  throw new Error(`QA fixture blocked an unexpected API request: ${path}`);
};

createRoot(document.getElementById("qa-controls")).render(<div style={{ position: "fixed", top: 4, right: 10, zIndex: 1000, display: "flex", gap: 6, padding: 6, background: "#fff", border: "1px solid #ccd5df", fontSize: 11 }}>
  <span>隔离 QA · 全部 API 为 mock</span>
  <button onClick={() => window.__chatInputQa.finishAnswer()}>完成模拟回答</button>
  <button onClick={() => finishCancel()}>确认模拟停止</button>
  <button onClick={() => finishCancel(true)}>模拟取消失败</button>
</div>);
createRoot(document.getElementById("root")).render(<AgentChat />);
