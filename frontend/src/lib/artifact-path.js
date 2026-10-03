/** Recognize artifact links; authorization and absolute workspace boundaries remain server-owned. */
export function resolveArtifactPath(value, baseDirectory = "") {
  if (typeof value !== "string" || !value.trim()) return null;
  let decoded;
  try { decoded = decodeURIComponent(value.trim()); } catch { return null; }
  if (/^(?:[a-z][a-z\d+.-]*:|\/\/|#)/i.test(decoded)) return null;
  const path = decoded.split("#", 1)[0];
  if (path.startsWith("/")) return /\/(?:\.run|tasks|output)(?:\/|$)/.test(path) ? path : null;
  const candidate = /^(?:\.\/)?(?:\.run|tasks|output)(?:\/|$)/.test(path) ? path.replace(/^\.\//, "")
    : baseDirectory ? `${baseDirectory}/${path}` : null;
  if (!candidate) return null;
  const segments = [];
  for (const segment of candidate.split("/")) {
    if (!segment || segment === ".") continue;
    if (segment === "..") { if (!segments.length) return null; segments.pop(); }
    else segments.push(segment);
  }
  return [".run", "tasks", "output"].includes(segments[0]) ? segments.join("/") : null;
}

export function artifactFileUrl(path, download = false) {
  const query = new URLSearchParams({ path });
  if (download) query.set("download", "1");
  return `/api/artifacts/file?${query}`;
}

export function artifactParent(path) {
  return path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
}
