import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { clipboardImageFile, MAX_IMAGE_BYTES, attachmentPayload, readChatAttachment } from "../src/lib/chat-attachments.js";

export async function runClipboardUnitContracts() {
  let checks = 0;
  async function check(name, action) { await action(); checks += 1; console.log(`PASS ${name}`); }
  const file = (name = "截图", type = "image/png", content = new Uint8Array([1, 2, 3])) => new File([content], name, { type, lastModified: 123456 });
  const item = (value, type = value.type) => ({ kind: "file", type, getAsFile: () => value });

  await check("plain text, HTML image URLs, absent data and ordinary file items do not become images", () => {
    for (const data of [undefined, {}, { items: [{ kind: "string", type: "text/plain", getAsFile() { throw new Error("must not read text as file"); } }] }, { items: [{ kind: "string", type: "text/html" }], getData: () => '<img src="https://example.com/image.png">' }, { files: [file("notes.txt", "text/plain")] }])
      assert.equal(clipboardImageFile(data), null);
  });
  await check("image file item is found after text and preserves real file bytes", async () => {
    const original = file();
    const result = clipboardImageFile({ items: [{ kind: "string", type: "text/plain" }, item(original)] });
    assert.ok(result instanceof File); assert.equal(result.type, "image/png"); assert.match(result.name, /\.png$/);
    assert.deepEqual(new Uint8Array(await result.arrayBuffer()), new Uint8Array(await original.arrayBuffer()));
  });
  await check("files fallback works with missing items and MIME inferred from a valid extension", () => {
    assert.equal(clipboardImageFile({ files: [file("截图.png")] }).name, "截图.png");
    const result = clipboardImageFile({ items: [], files: [file("扫描.JPG", "")] });
    assert.equal(result.type, "image/jpeg"); assert.equal(result.name, "扫描.JPG");
  });
  await check("null getAsFile does not hide later valid items or the files fallback", () => {
    const empty = { kind: "file", type: "image/png", getAsFile: () => null };
    assert.equal(clipboardImageFile({ items: [empty, item(file("later.png"))] }).name, "later.png");
    assert.equal(clipboardImageFile({ items: [empty], files: [file("fallback.png")] }).name, "fallback.png");
  });
  await check("supported raster image takes priority over unsupported clipboard representations", () => {
    const result = clipboardImageFile({ items: [item(file("vector.svg", "image/svg+xml")), item(file("raster.png"))] });
    assert.equal(result.name, "raster.png"); assert.equal(result.type, "image/png");
  });
  await check("file MIME takes precedence over a conflicting clipboard item MIME", () => {
    const result = clipboardImageFile({ items: [item(file("converted.jpg", "image/png"), "image/jpeg")] });
    assert.equal(result.type, "image/png"); assert.equal(result.name, "converted.png");
  });
  await check("four supported MIME types produce matching extensions for extensionless names", () => {
    for (const [type, extension] of [["image/png", "png"], ["image/jpeg", "jpg"], ["image/webp", "webp"], ["image/gif", "gif"]]) {
      const result = clipboardImageFile({ items: [item(file("剪贴板 图片", type))] });
      assert.equal(result.name, `剪贴板 图片.${extension}`); assert.equal(result.type, type);
    }
  });
  await check("nameless images get a filename, valid names and lastModified remain stable", () => {
    assert.match(clipboardImageFile({ files: [file("")] }).name, /^粘贴图片-.+\.png$/);
    const original = file("中文 空格.png");
    const result = clipboardImageFile({ items: [item(original)] });
    assert.equal(result.name, original.name); assert.equal(result.lastModified, original.lastModified);
  });
  await check("5 MiB boundary accepts exact limit and rejects larger images before reading", () => {
    const boundary = file("boundary.png", "image/png", new Uint8Array(MAX_IMAGE_BYTES));
    assert.equal(clipboardImageFile({ files: [boundary] }).size, MAX_IMAGE_BYTES);
    assert.throws(() => clipboardImageFile({ files: [file("oversized.png", "image/png", new Uint8Array(MAX_IMAGE_BYTES + 1))] }), /5 MiB/);
  });
  await check("unsupported image formats and zero byte images fail explicitly", () => {
    for (const type of ["image/svg+xml", "image/tiff", "image/heic"])
      assert.throws(() => clipboardImageFile({ files: [file("unsupported", type)] }), /PNG、JPEG、WEBP 或 GIF/);
    assert.throws(() => clipboardImageFile({ files: [file("empty.png", "image/png", new Uint8Array())] }), /为空/);
  });
  await check("normalized clipboard image uses existing FileReader and wire attachment shape", async () => {
    const normalized = clipboardImageFile({ items: [item(file("image"))] });
    const attachment = await readChatAttachment(normalized, () => ({ readAsDataURL() { this.result = "data:image/png;base64,AQID"; queueMicrotask(() => this.onload()); } }));
    assert.equal(attachment.previewUrl, "data:image/png;base64,AQID");
    assert.deepEqual(attachmentPayload(attachment), [{ name: "image.png", data: "AQID", mimeType: "image/png", kind: "image", size: 3 }]);
  });
  await check("clipboard FileReader error remains an actionable rejected promise", async () => {
    const normalized = clipboardImageFile({ files: [file()] });
    await assert.rejects(readChatAttachment(normalized, () => ({ readAsDataURL() { queueMicrotask(() => this.onerror()); } })), /读取附件失败/);
  });
  console.log(`${checks} clipboard helper contracts passed`);
  return { checks };
}

/** Run via playwright-cli run-code. Uses a real DOM ClipboardEvent/DataTransfer, never OS clipboard. */
export async function runClipboardBrowserContracts(page, smokeOnly = false) {
  const checks = [];
  const verify = (condition, message) => { if (!condition) throw new Error(message); checks.push(message); };
  const input = page.getByRole("textbox", { name: "输入你的问题" });
  const draft = "请结合这张截图，解释图上的曲线。";
  if (smokeOnly) {
    await input.fill(draft);
    const plain = await page.evaluate(() => {
      const transfer = new DataTransfer(); transfer.setData("text/plain", "普通文字"); transfer.setData("text/html", '<img src="https://example.com/remote.png">');
      const event = new ClipboardEvent("paste", { clipboardData: transfer, bubbles: true, cancelable: true });
      document.querySelector("textarea[aria-label='输入你的问题']").dispatchEvent(event);
      return { prevented: event.defaultPrevented, trusted: event.isTrusted, text: document.querySelector("textarea").value };
    });
    verify(!plain.prevented && plain.text === draft, "plain text/HTML URL paste is not intercepted and draft remains unchanged");
    const pasted = await page.evaluate(async () => {
      const canvas = document.createElement("canvas"); canvas.width = 160; canvas.height = 72;
      const context = canvas.getContext("2d"); context.fillStyle = "#f1f6fb"; context.fillRect(0, 0, 160, 72); context.strokeStyle = "#1769b6"; context.lineWidth = 3;
      context.beginPath(); context.moveTo(8, 60); context.lineTo(32, 45); context.lineTo(60, 14); context.lineTo(95, 51); context.lineTo(150, 29); context.stroke();
      const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
      const transfer = new DataTransfer(); transfer.setData("text/plain", "图像附带的文字"); transfer.items.add(new File([blob], "截图", { type: "image/png" }));
      const event = new ClipboardEvent("paste", { clipboardData: transfer, bubbles: true, cancelable: true });
      document.querySelector("textarea[aria-label='输入你的问题']").dispatchEvent(event);
      return { prevented: event.defaultPrevented, trusted: event.isTrusted };
    });
    await page.getByRole("img", { name: "待发送图片：截图.png" }).waitFor({ state: "visible" });
    verify(pasted.prevented && !pasted.trusted && await input.inputValue() === draft, "DOM image paste shows preview and preserves the typed question");
    verify(await page.getByRole("img", { name: "待发送图片：截图.png" }).evaluate(image => image.naturalWidth > 0), "pasted real PNG preview decodes successfully");
    await page.screenshot({ path: "output/playwright/chat-clipboard-preview.png", scale: "css" });
    await page.getByRole("button", { name: "发送消息", exact: true }).click();
    await page.getByRole("img", { name: "上传图片：截图.png" }).waitFor({ state: "visible" });
    const records = await page.evaluate(() => window.__chatInputQa.records);
    const request = records.find(record => record.path === "/api/chat/stream");
    verify(request?.message === draft && request.attachments.length === 1 && request.attachments[0].name === "截图.png" && request.attachments[0].mimeType === "image/png" && request.attachments[0].kind === "image" && request.attachments[0].base64Bytes > 0, "one stream payload contains exact original text and normalized PNG metadata/base64");
    await page.screenshot({ path: "output/playwright/chat-clipboard-question.png", scale: "css" });
    return { scope: "real DOM event, untrusted synthetic paste; no OS clipboard access", checks, records, screenshots: ["output/playwright/chat-clipboard-preview.png", "output/playwright/chat-clipboard-question.png"] };
  }

  // The smoke phase left a mocked answer pending. Finish only that mock, without testing cancellation.
  await page.getByRole("button", { name: "完成模拟回答", exact: true }).click();
  await page.getByRole("button", { name: "发送消息", exact: true }).waitFor({ state: "visible" });
  await input.fill(draft);
  await page.evaluate(async () => {
    const canvas = document.createElement("canvas"); canvas.width = 80; canvas.height = 40;
    const context = canvas.getContext("2d"); context.fillStyle = "#297b65"; context.fillRect(0, 0, 80, 40);
    window.__clipboardQaBlob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
    window.__dispatchQaPaste = (name, type = "image/png", bytes = window.__clipboardQaBlob) => {
      const transfer = new DataTransfer(); transfer.items.add(new File([bytes], name, { type }));
      const event = new ClipboardEvent("paste", { clipboardData: transfer, bubbles: true, cancelable: true });
      document.querySelector("textarea[aria-label='输入你的问题']").dispatchEvent(event);
      return event.defaultPrevented;
    };
    window.__dispatchQaPaste("保留图片.png");
  });
  await page.getByRole("img", { name: "待发送图片：保留图片.png" }).waitFor({ state: "visible" });
  const unsupported = await page.evaluate(() => window.__dispatchQaPaste("bad.svg", "image/svg+xml", '<svg xmlns="http://www.w3.org/2000/svg"></svg>'));
  await page.getByRole("alert").filter({ hasText: "PNG、JPEG、WEBP 或 GIF" }).waitFor({ state: "visible" });
  verify(unsupported && await page.getByRole("img", { name: "待发送图片：保留图片.png" }).count() === 1 && await input.inputValue() === draft, "unsupported pasted image is rejected without replacing the existing image or draft");
  const oversized = await page.evaluate(() => window.__dispatchQaPaste("too-big.png", "image/png", new Uint8Array(5 * 1024 * 1024 + 1)));
  await page.getByRole("alert").filter({ hasText: "5 MiB" }).waitFor({ state: "visible" });
  verify(oversized && await page.getByRole("img", { name: "待发送图片：保留图片.png" }).count() === 1 && await input.inputValue() === draft, "oversized pasted image is rejected before FileReader and preserves the prior image");
  const empty = await page.evaluate(() => window.__dispatchQaPaste("empty.png", "image/png", new Uint8Array()));
  await page.getByRole("alert").filter({ hasText: "附件为空" }).waitFor({ state: "visible" });
  verify(empty && await page.getByRole("img", { name: "待发送图片：保留图片.png" }).count() === 1, "empty pasted image produces an explicit error while the current image survives");

  await page.evaluate(() => {
    const OriginalReader = window.FileReader;
    window.__originalQaReader = OriginalReader;
    window.FileReader = class {
      readAsDataURL(file) {
        if (file.name === "failure.png") { setTimeout(() => this.onerror?.(new ProgressEvent("error")), 0); return; }
        const reader = new OriginalReader();
        reader.onload = () => { this.result = reader.result; setTimeout(() => this.onload?.(new ProgressEvent("load")), file.name === "older.png" ? 350 : 0); };
        reader.onerror = () => this.onerror?.(new ProgressEvent("error"));
        reader.readAsDataURL(file);
      }
    };
    window.__dispatchQaPaste("failure.png");
  });
  try {
    await page.getByRole("alert").filter({ hasText: "读取附件失败" }).waitFor({ state: "visible" });
    verify(await input.inputValue() === draft && await page.getByRole("img", { name: /^待发送图片：/ }).count() === 0, "FileReader failure shows an error, preserves text and leaves no broken preview");
    await page.evaluate(() => window.__dispatchQaPaste("older.png"));
    await page.getByRole("status").filter({ hasText: "正在读取附件" }).waitFor({ state: "visible" });
    verify(await page.getByRole("button", { name: "发送消息", exact: true }).isDisabled(), "sending is disabled while a pasted file is still being read");
    await page.evaluate(() => window.__dispatchQaPaste("latest.png"));
    await page.getByRole("img", { name: "待发送图片：latest.png" }).waitFor({ state: "visible" });
    await page.waitForTimeout(450); // Deliberately exceed the older injected read's delay.
    verify(await page.getByRole("img", { name: "待发送图片：latest.png" }).count() === 1 && await page.getByRole("img", { name: "待发送图片：older.png" }).count() === 0 && await input.inputValue() === draft, "late completion from an earlier paste cannot overwrite the latest image or draft");
  } finally {
    await page.evaluate(() => { window.FileReader = window.__originalQaReader; delete window.__originalQaReader; });
  }
  await page.screenshot({ path: "output/playwright/chat-clipboard-latest.png", scale: "css" });
  const records = await page.evaluate(() => window.__chatInputQa.records);
  verify(records.filter(record => record.path === "/api/chat/stream").length === 1 && records.every(record => record.path !== "/api/chat/cancel"), "boundary tests make no extra model request and do not retest cancellation");
  return { scope: "real DOM paste dispatch and real FileReader; injected read error/delay; no OS clipboard access", checks, records, screenshots: ["output/playwright/chat-clipboard-latest.png"] };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (process.argv.includes("--emit-browser")) {
    await mkdir(".run/chat-clipboard-ui", { recursive: true });
    await mkdir("output/playwright", { recursive: true });
    await writeFile(".run/chat-clipboard-ui/browser-smoke.js", `async (page) => (${runClipboardBrowserContracts.toString()})(page, true)\n`);
    await writeFile(".run/chat-clipboard-ui/browser-boundaries.js", `async (page) => (${runClipboardBrowserContracts.toString()})(page, false)\n`);
    console.log("Wrote CLI browser smoke and boundary functions; run them in order on the isolated mocked QA page.");
  } else await runClipboardUnitContracts();
}
