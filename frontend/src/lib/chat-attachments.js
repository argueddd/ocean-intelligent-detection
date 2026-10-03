export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_FILE_BYTES = 40 * 1024 * 1024;
const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
const EXTENSION_TYPES = { png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp", gif: "image/gif" };
export const ATTACHMENT_ACCEPT = "image/png,image/jpeg,image/webp,image/gif,.sio,.wav,.h5,.hdf5,.npy,.npz,.mat,.csv,.tsv,.json,.txt,.md,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip";

/** Read only the paste event's image files; text/HTML never grants clipboard access. */
export function clipboardImageFile(clipboardData) {
  if (!clipboardData) return null;
  const candidates = [];
  for (const item of Array.from(clipboardData.items || [])) {
    if (item.kind !== "file" || !String(item.type || "").toLowerCase().startsWith("image/")) continue;
    const file = item.getAsFile();
    if (file) candidates.push({ file, type: String(file.type || item.type).toLowerCase() });
  }
  // Some browsers expose pasted files without DataTransferItem entries.
  for (const file of Array.from(clipboardData.files || [])) {
    const type = String(file.type || EXTENSION_TYPES[String(file.name || "").split(".").at(-1)?.toLowerCase()] || "").toLowerCase();
    if (type.startsWith("image/")) candidates.push({ file, type });
  }
  if (!candidates.length) return null;
  const { file, type } = candidates.find(candidate => IMAGE_TYPES.has(candidate.type)) || candidates[0];
  const extensions = { "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif" };
  if (!extensions[type]) throw new Error("图片请使用 PNG、JPEG、WEBP 或 GIF 格式。");
  // Clipboard screenshots can be nameless or labelled .jpg after conversion to PNG.
  // The server needs a filename extension that agrees with the actual clipboard MIME.
  const original = String(file.name || "").trim();
  const extension = original.split(".").at(-1)?.toLowerCase();
  const name = original && EXTENSION_TYPES[extension] === type ? original
    : `${original.replace(/\.[^.]+$/, "") || `粘贴图片-${Date.now()}`}.${extensions[type]}`;
  const normalized = new File([file], name, { type, lastModified: file.lastModified || Date.now() });
  attachmentMetadata(normalized); // Reject unsupported/oversized content before replacing the current attachment.
  return normalized;
}

export function attachmentMetadata(file) {
  const declaredType = String(file?.type || "").toLowerCase();
  const extension = String(file?.name || "").split(".").at(-1)?.toLowerCase();
  const mimeType = !declaredType || declaredType === "application/octet-stream" ? EXTENSION_TYPES[extension] || "application/octet-stream" : declaredType;
  const kind = IMAGE_TYPES.has(mimeType) ? "image" : "file";
  if (mimeType.startsWith("image/") && kind !== "image") throw new Error("图片请使用 PNG、JPEG、WEBP 或 GIF 格式。");
  const size = Number(file?.size || 0);
  if (!file?.name || size <= 0) throw new Error("附件为空，请选择有内容的文件。");
  if (size > (kind === "image" ? MAX_IMAGE_BYTES : MAX_FILE_BYTES)) throw new Error(kind === "image" ? "图片超过 5 MiB，请缩小后上传。" : "附件超过 40 MiB，请提供本地文件路径。");
  return { name: file.name, mimeType, kind, size };
}

export function readChatAttachment(file, createReader = () => new FileReader()) {
  const metadata = attachmentMetadata(file);
  return new Promise((resolve, reject) => {
    const reader = createReader();
    reader.onload = () => {
      const match = String(reader.result || "").match(/^data:[^,]*;base64,([A-Za-z0-9+/=]+)$/);
      if (!match) { reject(new Error("无法读取附件内容，请重新选择文件。")); return; }
      const data = match[1];
      resolve({ ...metadata, data, ...(metadata.kind === "image" ? { previewUrl: `data:${metadata.mimeType};base64,${data}` } : {}) });
    };
    reader.onerror = () => reject(new Error("读取附件失败，请重新选择文件。"));
    reader.onabort = () => reject(new Error("附件读取已取消。"));
    try { reader.readAsDataURL(file); } catch { reject(new Error("读取附件失败，请重新选择文件。")); }
  });
}

/** Keep local preview data out of API metadata and persisted session lists. */
export function attachmentPayload(attachment) {
  if (!attachment) return undefined;
  const { name, data, mimeType, kind, size } = attachment;
  return [{ name, data, mimeType, kind, size }];
}

export function attachmentSizeLabel(size) {
  return size >= 1024 * 1024 ? `${(size / (1024 * 1024)).toFixed(1)} MiB` : `${Math.ceil(size / 1024)} KiB`;
}
