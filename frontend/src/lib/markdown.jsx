import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useArtifactPreview } from "./artifact-context";
import { artifactFileUrl, resolveArtifactPath } from "./artifact-path";

/** GFM answers and reports; local artifacts use previews while external/knowledge links stay intact. */
export function Markdown({ children, className = "", baseDirectory = "" }) {
  const openArtifact = useArtifactPreview();
  const openLocal = (event, path) => {
    if (!openArtifact || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    openArtifact(path);
  };
  return (
    <div className={`chat-md${className ? ` ${className}` : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          table: ({ node, ...props }) => (
            <div className="md-table-wrap">
              <table {...props} />
            </div>
          ),
          a: ({ node, href, children, ...props }) => {
            const path = resolveArtifactPath(href, baseDirectory);
            return path ? <a {...props} className="md-artifact-link" href={artifactFileUrl(path)}
              data-artifact-path={path} onClick={(event) => openLocal(event, path)}>{children}</a>
              : <a {...props} href={href}>{children}</a>;
          },
          img: ({ node, src, alt, ...props }) => {
            const path = resolveArtifactPath(src, baseDirectory);
            if (!path) return <img {...props} src={src} alt={alt || ""} />;
            return <a className="md-artifact-image" href={artifactFileUrl(path)} data-artifact-path={path}
              aria-label={`打开图片：${alt || path.split("/").pop()}`} onClick={(event) => openLocal(event, path)}>
              <img {...props} src={artifactFileUrl(path)} alt={alt || "分析图片"} loading="lazy" />
            </a>;
          },
          code: ({ node, className, children, ...props }) => {
            const value = String(children);
            // Fenced code carries a trailing newline; preserve it even when it contains a path.
            // Only explicit workspace paths in inline code are legacy artifact links.
            const path = !className && !value.includes("\n") ? resolveArtifactPath(value) : null;
            const code = <code {...props} className={className}>{children}</code>;
            return path ? <a className="md-artifact-link md-artifact-inline" href={artifactFileUrl(path)}
              data-artifact-path={path} onClick={(event) => openLocal(event, path)}>{code}</a> : code;
          },
        }}
      >
        {children || ""}
      </ReactMarkdown>
    </div>
  );
}
