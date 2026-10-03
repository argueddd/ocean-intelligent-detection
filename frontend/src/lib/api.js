/**
 * 适配层客户端：SSE 聊天、审批决定、kb 反馈，以及 localStorage 会话列表。
 * 适配层地址走 vite 代理（/api → 127.0.0.1:3088）。
 */

// Keep this module importable by the offline SSE contracts outside Vite.
export const IS_HARNESS_MODE = import.meta.env?.VITE_AGENT_MODE === "harness";
const SESSIONS_KEY = IS_HARNESS_MODE ? "ocean-harness-sessions" : "rag-kb-sessions";

export async function fetchArtifact(path, signal) {
  const response = await fetch(`/api/artifacts?${new URLSearchParams({ path })}`, { signal });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || `无法打开产物（HTTP ${response.status}）`);
  return data;
}

export async function fetchArtifactText(url, signal) {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`无法读取内容（HTTP ${response.status}）`);
  const text = await response.text();
  if (text.length > 2 * 1024 * 1024) throw new Error("文件较大，请下载后查看。");
  return text;
}

/** ---------------------------------------------------------------- 会话列表（localStorage） */

export function loadSessions() {
  try {
    const raw = JSON.parse(localStorage.getItem(SESSIONS_KEY) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

function saveSessions(list) {
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(list.slice(0, 50)));
}

/** 记录/刷新一个会话（title 取首条用户消息）。 */
export function upsertSession(sessionId, title) {
  const list = loadSessions().filter((s) => s.sessionId !== sessionId);
  const existing = loadSessions().find((s) => s.sessionId === sessionId);
  list.unshift({
    sessionId,
    title: title || existing?.title || "新对话",
    time: Date.now(),
  });
  saveSessions(list);
  return list;
}

export function removeSession(sessionId) {
  saveSessions(loadSessions().filter((s) => s.sessionId !== sessionId));
  return loadSessions();
}

/** 服务端会话迁移后，把本地会话表里的旧 id 原地改成新 id（保留标题与时间）。 */
export function renameSession(fromId, toId) {
  const list = loadSessions();
  const hit = list.find((s) => s.sessionId === fromId);
  if (!hit) return upsertSession(toId, "新对话");
  return saveSessions([
    ...list.filter((s) => s.sessionId !== fromId && s.sessionId !== toId),
    { ...hit, sessionId: toId },
  ]) || loadSessions();
}

/** ---------------------------------------------------------------- SSE 聊天 */

export function createChatRequestId() {
  return globalThis.crypto?.randomUUID?.() || "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const value = Math.floor(Math.random() * 16);
    return (char === "x" ? value : (value & 3) | 8).toString(16);
  });
}

export async function cancelChat({ requestId, sessionId }) {
  const response = await fetch("/api/chat/cancel", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ requestId, ...(sessionId ? { sessionId } : {}) }),
  });
  let data;
  try { data = await response.json(); } catch { /* Server may return a plain HTTP error. */ }
  if (!response.ok || data?.ok !== true) throw new Error(data?.error || `取消未确认（HTTP ${response.status}）`);
  return data;
}

/**
 * 发送一条消息并消费 SSE 流。
 * @param {object} opts - { requestId?, sessionId?, message, attachments? }
 * @param {object} handlers - { onStart, onPhase, onNotification, onRenamed, onDone, onCancelled, onError }
 * @returns {Function} 断开显示的函数；.cancel() 同时请求取消并等到服务端确认空闲。
 */
export function streamChat({ requestId = createChatRequestId(), sessionId, message, attachments }, handlers) {
  const controller = new AbortController();
  let terminal = false;
  let currentSessionId = sessionId;
  let activeReader = null;
  let cancellation = null;
  const fail = (message) => {
    if (terminal || controller.signal.aborted) return;
    terminal = true;
    handlers.onError?.(message);
  };

  (async () => {
    let response
    try {
      response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          requestId,
          ...(sessionId ? { sessionId } : {}),
          message,
          ...(attachments && attachments.length ? { attachments } : {}),
        }),
        signal: controller.signal,
      });
    } catch (e) {
      fail("连接适配层失败：" + e.message);
      return;
    }

    if (!response.ok || !response.body) {
      let detail = "";
      try {
        detail = (await response.json())?.error || "";
      } catch { /* 非 JSON 响应 */ }
      fail(detail || `请求失败（HTTP ${response.status}）`);
      return;
    }

    const reader = response.body.getReader();
    activeReader = reader;
    const decoder = new TextDecoder();
    let buffer = "";

    const handleBlock = (block) => {
      if (terminal || controller.signal.aborted) return;
      const lines = block.split(/\r?\n/);
      const eventLine = lines.find((l) => l.startsWith("event:"));
      const dataLines = lines.filter((l) => l.startsWith("data:"));
      if (!eventLine || !dataLines.length) return;
      const event = eventLine.slice(6).trim();
      let data;
      try {
        data = JSON.parse(dataLines.map((l) => l.slice(5).trimStart()).join("\n"));
      } catch {
        return;
      }
      if (event === "start") {
        currentSessionId = data.sessionId;
        handlers.onStart?.(data.sessionId);
      }
      else if (event === "phase") handlers.onPhase?.(data);
      else if (event === "notification") handlers.onNotification?.(data);
      else if (event === "renamed") {
        currentSessionId = data.to;
        handlers.onRenamed?.(data);
      }
      else if (event === "done") {
        terminal = true;
        handlers.onDone?.(data);
      }
      else if (event === "cancelled") {
        terminal = true;
        handlers.onCancelled?.(data);
      }
      else if (event === "error") fail(data.message || "未知错误");
    };

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let separator;
        while ((separator = /\r?\n\r?\n/.exec(buffer))) {
          handleBlock(buffer.slice(0, separator.index).trim());
          buffer = buffer.slice(separator.index + separator[0].length);
        }
        if (terminal || controller.signal.aborted) break;
      }
      buffer += decoder.decode();
      if (buffer.trim()) handleBlock(buffer.trim());
      if (!terminal) fail("响应流已结束，但未收到完成状态；服务端可能仍在执行，请检查会话后再重试。");
    } catch (e) {
      fail("流中断：" + e.message);
    } finally {
      try { await reader.cancel(); } catch { /* 流已关闭 */ }
      reader.releaseLock();
      if (activeReader === reader) activeReader = null;
    }
  })();

  const detach = () => {
    terminal = true;
    controller.abort();
    activeReader?.cancel().catch(() => {});
  };
  detach.requestId = requestId;
  detach.cancel = () => {
    detach(); // Late SSE events must not change the UI while cancellation is pending.
    if (!cancellation) {
      cancellation = cancelChat({ requestId, sessionId: currentSessionId }).catch((error) => {
        cancellation = null; // A failed cancellation can be retried with the same request token.
        throw error;
      });
    }
    return cancellation;
  };
  return detach;
}

/** ---------------------------------------------------------------- 审批与反馈（转发适配层） */

/** 拉取会话历史（适配层读会话日志投影成展示事件）。失败返回空数组。 */
export async function fetchChatHistory(sessionId) {
  try {
    const res = await fetch(`/api/chat/history?sessionId=${encodeURIComponent(sessionId)}`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.events) ? data.events : [];
  } catch {
    return [];
  }
}

export async function fetchPendingApprovals() {
  if (IS_HARNESS_MODE) return [];
  const r = await fetch("/api/approvals/pending");
  if (!r.ok) return [];
  const data = await r.json();
  return Array.isArray(data.pending) ? data.pending : [];
}

export async function decideApproval(id, decision) {
  if (IS_HARNESS_MODE) throw new Error("当前分析模式未启用知识库审批接口");
  const r = await fetch(`/api/approvals/${encodeURIComponent(id)}/decision`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  if (!r.ok) throw new Error("审批提交失败（HTTP " + r.status + "）");
  return r.json();
}

/**
 * 提交回答反馈（点赞/点踩），按 query_id 关联检索证据。
 * dsh-knowledge 的 feedback 接口：rating 取 positive|negative；
 * 必须携带 query（问题文本）或 message_id；负反馈需 issue_type 或 note。
 * @param {object} body - { rating: 'up'|'down', query_id?, question?, answer?, note? }
 */
export async function submitFeedback(body) {
  if (IS_HARNESS_MODE) return { skipped: true };
  const rating = body.rating === "down" ? "negative" : "positive";
  const payload = {
    ...body,
    rating,
    query: body.question || "",
    issue_type: rating === "negative" && !body.note ? "other" : body.issue_type,
  };
  delete payload.question;
  const r = await fetch("/api/kb/feedback", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error("反馈提交失败（HTTP " + r.status + "）");
  return r.json();
}
