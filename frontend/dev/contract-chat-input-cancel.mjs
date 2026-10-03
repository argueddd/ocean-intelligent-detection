import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { ATTACHMENT_ACCEPT, MAX_IMAGE_BYTES, attachmentMetadata, attachmentPayload, readChatAttachment } from "../src/lib/chat-attachments.js";
import { canSendChat, interruptPendingSteps } from "../src/lib/chat-turn-state.js";
import { cancelChat, createChatRequestId, streamChat } from "../src/lib/api.js";
import { toolResultState, toolStatusLabel } from "../src/lib/tool-progress.js";

let checks = 0;
async function check(name, fn) { await fn(); checks += 1; console.log(`PASS ${name}`); }
const encoder = new TextEncoder();
const nextTick = () => new Promise(resolve => setTimeout(resolve, 0));
const sse = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
const streamed = (source) => new Response(new ReadableStream({ start(controller) { controller.enqueue(encoder.encode(source)); controller.close(); } }));
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
async function withFetch(fetcher, fn) {
  const previous = globalThis.fetch;
  globalThis.fetch = fetcher;
  try { await fn(); } finally { globalThis.fetch = previous; }
}

await check("all four image formats have explicit MIME/kind, including empty OS MIME fallback", () => {
  for (const [extension, type] of [["png", "image/png"], ["jpg", "image/jpeg"], ["webp", "image/webp"], ["gif", "image/gif"]]) {
    assert.equal(attachmentMetadata({ name: `图像.${extension}`, type, size: 128 }).kind, "image");
    assert.equal(attachmentMetadata({ name: `图像.${extension}`, type: "", size: 128 }).mimeType, type);
    assert.match(ATTACHMENT_ACCEPT, new RegExp(type));
  }
});
await check("image size boundary, empty files and unsupported image formats fail before reading", () => {
  assert.equal(attachmentMetadata({ name: "a.png", type: "image/png", size: MAX_IMAGE_BYTES }).size, MAX_IMAGE_BYTES);
  assert.throws(() => attachmentMetadata({ name: "a.png", type: "image/png", size: MAX_IMAGE_BYTES + 1 }), /5 MiB/);
  assert.throws(() => attachmentMetadata({ name: "a.png", type: "image/png", size: 0 }), /为空/);
  for (const type of ["image/svg+xml", "image/tiff", "image/heic"])
    assert.throws(() => attachmentMetadata({ name: "a.image", type, size: 10 }), /PNG、JPEG、WEBP 或 GIF/);
});
await check("ordinary data and document attachments preserve the existing file upload path", () => {
  assert.deepEqual(attachmentMetadata({ name: "array.npz", type: "", size: 20 }), { name: "array.npz", mimeType: "application/octet-stream", kind: "file", size: 20 });
  assert.equal(attachmentMetadata({ name: "report.pdf", type: "application/pdf", size: 200 }).kind, "file");
});
const image = await readChatAttachment({ name: "频谱 图.png", type: "image/png", size: 5 }, () => ({ readAsDataURL() { this.result = "data:image/png;base64,aGVsbG8="; queueMicrotask(() => this.onload()); } }));
await check("reader creates one local image preview and wire payload excludes preview fields", () => {
  assert.equal(image.previewUrl, "data:image/png;base64,aGVsbG8=");
  assert.deepEqual(attachmentPayload(image), [{ name: "频谱 图.png", data: "aGVsbG8=", mimeType: "image/png", kind: "image", size: 5 }]);
  assert.equal(attachmentPayload(null), undefined);
});
await check("FileReader errors, abort, malformed data and synchronous failure are actionable", async () => {
  const file = { name: "a.png", type: "image/png", size: 5 };
  for (const action of [reader => reader.onerror(), reader => reader.onabort(), reader => { reader.result = "bad"; reader.onload(); }])
    await assert.rejects(readChatAttachment(file, () => ({ readAsDataURL() { queueMicrotask(() => action(this)); } })), /读取|取消/);
  await assert.rejects(readChatAttachment(file, () => ({ readAsDataURL() { throw new Error("disk"); } })), /读取附件失败/);
});
await check("send stays locked during execution, attachment read and cancellation failure or pending ACK", () => {
  assert.equal(canSendChat({ hasContent: true }), true);
  assert.equal(canSendChat({ hasAttachment: true }), true);
  assert.equal(canSendChat({}), false);
  for (const state of [{ isThinking: true }, { attachmentReading: true }, { cancellationState: "pending" }, { cancellationState: "failed" }])
    assert.equal(canSendChat({ hasContent: true, ...state }), false);
});
await check("cancellation never changes completed, failed, partial or approval records into success", () => {
  const records = ["running", "done", "error", "partial"].map(status => ({ role: "tool", id: status, name: "bash", status }));
  records.push({ role: "approval", id: "approval", status: "pending" });
  const pending = interruptPendingSteps(records, "cancelling");
  const failedStop = interruptPendingSteps(pending, "stop-unconfirmed");
  assert.equal(toolStatusLabel(failedStop[0]), "停止未确认");
  const stopped = interruptPendingSteps(interruptPendingSteps(failedStop, "cancelling"), "interrupted");
  assert.deepEqual(stopped.map(item => item.status), ["interrupted", "done", "error", "partial", "pending"]);
  assert.equal(records[0].status, "running");
  assert.equal(toolResultState(stopped[0], ""), "interrupted");
  assert.equal(toolStatusLabel(pending[0]), "正在停止");
  assert.equal(toolStatusLabel(stopped[0]), "已中断");
});
await check("new request IDs are UUID shaped and distinct", () => {
  const ids = Array.from({ length: 20 }, createChatRequestId);
  assert.equal(new Set(ids).size, 20);
  ids.forEach(id => assert.match(id, /^[a-f\d]{8}-[a-f\d]{4}-4[a-f\d]{3}-[89ab][a-f\d]{3}-[a-f\d]{12}$/i));
});
await check("text question and image metadata reach one stream request; phase is delivered", async () => {
  const received = [], phases = [], finished = deferred();
  await withFetch(async (url, opts) => {
    assert.equal(url, "/api/chat/stream"); received.push(JSON.parse(opts.body));
    return streamed(sse("start", { sessionId: "same-session" }) + sse("phase", { message: "正在解读上传图片" }) + sse("done", { finalResponse: "曲线" }));
  }, async () => {
    streamChat({ message: "请解释这张PSD图", attachments: attachmentPayload(image) }, { onPhase: event => phases.push(event.message), onDone: finished.resolve, onError: msg => { throw new Error(msg); } });
    await finished.promise;
  });
  assert.equal(received[0].message, "请解释这张PSD图"); assert.equal(received[0].attachments[0].kind, "image");
  assert.equal(received[0].attachments[0].data, image.data); assert.equal(typeof received[0].requestId, "string");
  assert.deepEqual(phases, ["正在解读上传图片"]);
});
await check("early stop uses the same request token before a session exists and waits for ACK", async () => {
  const received = [], ack = deferred(); let signal; let calls = 0;
  await withFetch((url, opts) => {
    received.push([url, JSON.parse(opts.body)]);
    if (url === "/api/chat/cancel") { calls += 1; return ack.promise; }
    signal = opts.signal;
    return new Promise((_, reject) => signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }));
  }, async () => {
    const handle = streamChat({ message: "先看图" }, { onError() { throw new Error("stale error"); }, onDone() { throw new Error("stale done"); } });
    let settled = false;
    const cancellation = handle.cancel(); cancellation.then(() => { settled = true; });
    assert.equal(handle.cancel(), cancellation); assert.equal(calls, 1); assert.equal(signal.aborted, true);
    await nextTick(); assert.equal(settled, false);
    ack.resolve(json({ ok: true, cancelled: true, sessionId: "created-session" }));
    assert.equal((await cancellation).sessionId, "created-session");
  });
  assert.equal(received[0][1].requestId, received[1][1].requestId); assert.equal(received[1][1].sessionId, undefined);
});
await check("late SSE cannot deliver a new answer or done after a stop", async () => {
  let handle; const started = deferred(), events = []; let streamSignal;
  await withFetch(async (url, opts) => {
    if (url === "/api/chat/cancel") return json({ ok: true, cancelled: true, sessionId: "same-session" });
    streamSignal = opts.signal;
    return streamed(sse("start", { sessionId: "same-session" }) + sse("notification", { text: "late" }) + sse("done", {}));
  }, async () => {
    handle = streamChat({ message: "分析" }, {
      onStart: () => { events.push("start"); handle.cancel().then(started.resolve); },
      onNotification: () => events.push("late answer"), onDone: () => events.push("done"), onError: () => events.push("error"),
    });
    await started.promise; await nextTick(); assert.equal(streamSignal.aborted, true);
  });
  assert.deepEqual(events, ["start"]);
});
await check("a new question after cancel retains session ID and gets a fresh request token", async () => {
  const received = [], firstStart = deferred(), followupDone = deferred();
  await withFetch(async (url, opts) => {
    const body = JSON.parse(opts.body); received.push([url, body]);
    if (url === "/api/chat/cancel") return json({ ok: true, cancelled: true, sessionId: "same-session" });
    if (body.message === "下一问") return streamed(sse("start", { sessionId: body.sessionId }) + sse("done", {}));
    return new Response(new ReadableStream({ start(controller) { controller.enqueue(encoder.encode(sse("start", { sessionId: "same-session" }))); } }));
  }, async () => {
    const first = streamChat({ message: "第一问" }, { onStart: firstStart.resolve });
    const sessionId = await firstStart.promise; await first.cancel();
    streamChat({ sessionId, message: "下一问" }, { onDone: followupDone.resolve });
    await followupDone.promise;
  });
  const [first, cancel, next] = received.map(entry => entry[1]);
  assert.equal(cancel.sessionId, "same-session"); assert.equal(next.sessionId, "same-session");
  assert.equal(cancel.requestId, first.requestId); assert.notEqual(next.requestId, first.requestId);
});
await check("cancel failure is explicit and a retry reuses the same token", async () => {
  let attempts = 0; const received = [];
  await withFetch(async (url, opts) => {
    if (url === "/api/chat/stream") return new Response(new ReadableStream({}));
    received.push(JSON.parse(opts.body)); attempts += 1;
    return attempts === 1 ? json({ ok: false, error: "SDK 尚未空闲" }, 503) : json({ ok: true, cancelled: true, sessionId: "s" });
  }, async () => {
    const handle = streamChat({ sessionId: "s", message: "任务" }, {});
    await assert.rejects(handle.cancel(), /SDK 尚未空闲/);
    await handle.cancel();
  });
  assert.equal(attempts, 2); assert.deepEqual(received[0], received[1]);
});
await check("cancellation follows the canonical session ID after server migration", async () => {
  const renamed = deferred(); let cancelBody;
  await withFetch(async (url, options) => {
    if (url === "/api/chat/cancel") { cancelBody = JSON.parse(options.body); return json({ ok: true, cancelled: true, sessionId: "new-session" }); }
    return new Response(new ReadableStream({ start(controller) {
      controller.enqueue(encoder.encode(sse("start", { sessionId: "old-session" }) + sse("renamed", { from: "old-session", to: "new-session" })));
    } }));
  }, async () => {
    const handle = streamChat({ sessionId: "old-session", message: "继续" }, { onRenamed: renamed.resolve });
    await renamed.promise; await handle.cancel();
    assert.equal(cancelBody.sessionId, "new-session"); assert.equal(cancelBody.requestId, handle.requestId);
  });
});
await check("cancel acknowledgement and HTTP errors are not conflated", async () => {
  await withFetch(async () => json({ ok: true, cancelled: false, sessionId: "s" }), async () => assert.equal((await cancelChat({ requestId: "r", sessionId: "s" })).cancelled, false));
  await withFetch(async () => new Response("upstream down", { status: 502 }), async () => assert.rejects(cancelChat({ requestId: "r" }), /HTTP 502/));
});
await check("server cancelled is a terminal state, without a false EOF error or stale answer", async () => {
  const terminal = deferred(), events = [];
  await withFetch(async () => streamed(sse("start", { sessionId: "s" }) + sse("cancelled", { sessionId: "s" }) + sse("notification", { text: "late" })), async () => {
    streamChat({ sessionId: "s", message: "任务" }, {
      onCancelled: event => { events.push(["cancelled", event.sessionId]); terminal.resolve(); },
      onError: msg => events.push(["error", msg]), onNotification: () => events.push(["notification"]),
    });
    await terminal.promise; await nextTick();
  });
  assert.deepEqual(events, [["cancelled", "s"]]);
});

const server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), server: { middlewareMode: true, hmr: false }, appType: "custom" });
try {
  const { AttachmentChip, ChatSendButton, UserMessage, AssistantMessage, ToolCard } = await server.ssrLoadModule("/src/components/AgentChat.jsx");
  const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));
  await check("selected image has a thumbnail, size and accessible removal control", () => {
    const html = render(AttachmentChip, { attachment: image, onRemove() {} });
    assert.match(html, /<img[^>]+src="data:image\/png;base64,/); assert.match(html, /待发送图片：频谱 图.png/);
    assert.match(html, /移除 频谱 图.png/); assert.match(html, /图片 · /);
  });
  await check("ordinary attachment remains a file chip without an image", () => {
    const html = render(AttachmentChip, { attachment: { name: "array.npz", kind: "file", size: 100 }, onRemove() {} });
    assert.doesNotMatch(html, /<img/); assert.match(html, /array.npz/); assert.match(html, /移除 array.npz/);
  });
  await check("user bubble displays its image beside the exact text question", () => {
    const html = render(UserMessage, { message: { time: "12:00", content: "这个峰有什么意义？", attachment: image } });
    assert.match(html, /这个峰有什么意义？/); assert.match(html, /上传图片：频谱 图.png/); assert.match(html, /<figcaption>频谱 图.png<\/figcaption>/);
  });
  await check("complete Markdown links and images display immediately without a typing timer", () => {
    const html = render(AssistantMessage, { message: { time: "12:00", content: "完整结论。\n\n[报告](.run/a/report.md)\n\n![PSD](.run/a/psd.png)\n\n末尾证据。" } });
    assert.match(html, /完整结论/); assert.match(html, /末尾证据/); assert.match(html, /data-artifact-path="\.run\/a\/report.md"/);
    assert.match(html, /data-artifact-path="\.run\/a\/psd.png"/); assert.match(html, /复制回答/); assert.doesNotMatch(html, /is-growing/);
  });
  await check("cancel pending disables send; failure offers retry; same-session ACK unlocks send", () => {
    const base = { isThinking: false, attachmentReading: false, hasContent: true, hasAttachment: false, onSend() {}, onStop() {} };
    const pending = render(ChatSendButton, { ...base, cancellationState: "pending" }); assert.match(pending, /disabled=""/); assert.match(pending, /aria-label="正在停止"/);
    const failed = render(ChatSendButton, { ...base, cancellationState: "failed" }); assert.doesNotMatch(failed, /disabled=/); assert.match(failed, /aria-label="重试停止"/);
    const idle = render(ChatSendButton, { ...base, cancellationState: "idle" }); assert.doesNotMatch(idle, /disabled=/); assert.match(idle, /aria-label="发送消息"/);
    const running = render(ChatSendButton, { ...base, isThinking: true, cancellationState: "idle" }); assert.doesNotMatch(running, /disabled=/); assert.match(running, /aria-label="停止回答"/);
  });
  await check("send remains disabled while FileReader is busy", () => {
    const html = render(ChatSendButton, { isThinking: false, cancellationState: "idle", attachmentReading: true, hasContent: true, hasAttachment: false });
    assert.match(html, /disabled=""/);
  });
  await check("interrupted tools do not display a successful completion label", () => {
    const html = render(ToolCard, { card: { name: "bash", args: { description: "计算 PSD" }, status: "interrupted" } });
    assert.match(html, /已中断/); assert.match(html, /未取得完成结果/); assert.doesNotMatch(html, /执行完成/);
  });
  console.log(`${checks} chat input/cancellation contracts passed; all network calls mocked`);
} finally { await server.close(); }
