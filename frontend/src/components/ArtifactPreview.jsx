import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, DownloadSimple, File, FolderOpen, X } from "@phosphor-icons/react";
import { ArtifactContext } from "../lib/artifact-context";
import { artifactFileUrl, artifactParent } from "../lib/artifact-path";
import { fetchArtifact, fetchArtifactText } from "../lib/api";
import { Markdown } from "../lib/markdown";

const sizeLabel = (size) => size < 1024 ? `${size} B` : size < 1048576 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1048576).toFixed(1)} MB`;

function ArtifactDialog({ path, canGoBack, onBack, onNavigate, onClose }) {
  const [state, setState] = useState({ loading: true });
  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    closeRef.current?.focus();
    return () => previous?.isConnected && previous.focus?.();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    closeRef.current?.focus();
    setState({ loading: true });
    (async () => {
      let metadata;
      try {
        metadata = await fetchArtifact(path, controller.signal);
        let text;
        if (["markdown", "text"].includes(metadata.preview)) text = await fetchArtifactText(metadata.fileUrl || artifactFileUrl(metadata.path), controller.signal);
        if (!controller.signal.aborted) setState({ metadata, text });
      } catch (error) {
        if (!controller.signal.aborted) setState({ metadata, error: error.message });
      }
    })();
    return () => controller.abort();
  }, [path]);
  const metadata = state.metadata;
  const fileUrl = metadata?.fileUrl || artifactFileUrl(metadata?.path || path);
  const downloadUrl = metadata?.downloadUrl || artifactFileUrl(metadata?.path || path, true);
  const parent = artifactParent(metadata?.path || "");
  const keyDown = (event) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(); }
    if (event.key !== "Tab") return;
    const nodes = [...dialogRef.current.querySelectorAll('button:not([disabled]), a[href], iframe, [tabindex="0"]')];
    const first = nodes[0]; const last = nodes.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  };
  let text = state.text;
  if (metadata?.preview === "text" && /\.json$/i.test(metadata.name)) {
    try { text = JSON.stringify(JSON.parse(text), null, 2); } catch { /* Retain the source when JSON is invalid. */ }
  }
  return <div className="artifact-layer">
    <button className="artifact-backdrop" type="button" aria-label="关闭产物预览" tabIndex={-1} onClick={onClose} />
    <section className="artifact-dialog" role="dialog" aria-modal="true" aria-labelledby="artifact-title" ref={dialogRef} onKeyDown={keyDown}>
      <header className="artifact-header">
        <div><span>分析产物</span><h2 id="artifact-title">{metadata?.name || "预览"}</h2><p>{metadata?.path || path}</p></div>
        <button className="artifact-icon-button" type="button" aria-label="关闭预览" ref={closeRef} onClick={onClose}><X size={20} /></button>
      </header>
      <nav className="artifact-toolbar" aria-label="产物操作">
        {canGoBack ? <button type="button" onClick={onBack}><ArrowLeft size={16} />返回</button> : null}
        {parent ? <button type="button" onClick={() => onNavigate(parent)}><FolderOpen size={16} />所在目录</button> : null}
        {metadata?.kind === "file" ? <a href={downloadUrl} download={metadata.name}><DownloadSimple size={16} />下载</a> : null}
        {metadata?.kind === "file" ? <span>{sizeLabel(metadata.sizeBytes)}</span> : null}
      </nav>
      <div className="artifact-body" aria-live="polite">
        {state.loading ? <p className="artifact-notice">正在读取产物…</p> : null}
        {state.error ? <p className="artifact-notice is-error" role="alert">{state.error}</p> : null}
        {metadata?.kind === "directory" ? <div className="artifact-directory">
          {(metadata.entries || []).map(entry => <button type="button" key={entry.path} onClick={() => onNavigate(entry.path)} aria-label={`打开 ${entry.name}`}>
            {entry.kind === "directory" ? <FolderOpen size={20} /> : <File size={20} />}
            <span><strong>{entry.name}</strong><small>{entry.kind === "directory" ? "目录" : `${entry.preview === "download" ? "下载文件" : "可预览"} · ${sizeLabel(entry.sizeBytes)}`}</small></span>
          </button>)}
          {!metadata.entries?.length ? <p className="artifact-notice">此目录没有可展示的产物。</p> : null}
          {metadata.truncated ? <p className="artifact-notice">目录文件较多，仅展示部分条目。</p> : null}
        </div> : null}
        {metadata?.preview === "markdown" && state.text !== undefined ? <Markdown className="artifact-markdown" baseDirectory={artifactParent(metadata.path)}>{state.text}</Markdown> : null}
        {metadata?.preview === "image" ? <figure className="artifact-image"><img src={fileUrl} alt={metadata.name} /><figcaption>{metadata.name}</figcaption></figure> : null}
        {metadata?.preview === "pdf" ? <iframe className="artifact-pdf" src={fileUrl} title={metadata.name} /> : null}
        {metadata?.preview === "text" && text !== undefined ? <pre className="artifact-text">{text}</pre> : null}
        {metadata?.preview === "download" ? <div className="artifact-notice"><p>此格式支持下载后查看。</p><a href={downloadUrl} download={metadata.name}>下载 {metadata.name}</a></div> : null}
      </div>
    </section>
  </div>;
}

export function ArtifactProvider({ children }) {
  const [paths, setPaths] = useState([]);
  const open = useCallback(path => setPaths(items => items.at(-1) === path ? items : [...items, path]), []);
  const close = useCallback(() => setPaths([]), []);
  return <ArtifactContext.Provider value={open}>
    {children}
    {paths.length ? <ArtifactDialog path={paths.at(-1)} canGoBack={paths.length > 1} onBack={() => setPaths(items => items.slice(0, -1))} onNavigate={open} onClose={close} /> : null}
  </ArtifactContext.Provider>;
}
