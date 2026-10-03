import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { artifactFileUrl, resolveArtifactPath } from "../src/lib/artifact-path.js";

let checks = 0;
function check(name, fn) { fn(); checks += 1; console.log(`PASS ${name}`); }
check("workspace path roots and relative report resources", () => {
  assert.equal(resolveArtifactPath(".run/a.md", "tasks/other"), ".run/a.md");
  assert.equal(resolveArtifactPath("./tasks/a.md", ".run/other"), "tasks/a.md");
  assert.equal(resolveArtifactPath("figures/psd.png", ".run/报告 目录"), ".run/报告 目录/figures/psd.png");
  assert.equal(resolveArtifactPath("../result.json", ".run/report/figures"), ".run/report/result.json");
  assert.equal(resolveArtifactPath("../../../backend/.env", ".run/report"), null);
});
check("absolute paths remain server-authorized", () => {
  assert.equal(resolveArtifactPath("/workspace/ocean/.run/中文 文件.md"), "/workspace/ocean/.run/中文 文件.md");
  assert.equal(resolveArtifactPath("/workspace/ocean/backend/.env"), null);
});
check("URL encoding preserves Chinese, spaces and download option", () => {
  const path = ".run/中文 空格/结果.json";
  const url = new URL(artifactFileUrl(path, true), "http://localhost");
  assert.equal(url.searchParams.get("path"), path);
  assert.equal(url.searchParams.get("download"), "1");
  assert.equal(resolveArtifactPath(encodeURI(path)), path);
});
check("external and unsafe protocols are not local artifact links", () => {
  for (const path of ["https://example.com/report.md", "http://127.0.0.1:3090/kb/image?p=a", "//example.com/.run/a", "javascript:alert(1)", "file:///tmp/a", "#section", "%FF"])
    assert.equal(resolveArtifactPath(path, ".run/report"), null, path);
});

const server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), server: { middlewareMode: true }, appType: "custom" });
try {
  const { Markdown } = await server.ssrLoadModule("/src/lib/markdown.jsx");
  const render = (source, baseDirectory = "") => renderToStaticMarkup(React.createElement(Markdown, { children: source, baseDirectory }));
  check("Markdown absolute/spaced local links and inline images", () => {
    const html = render("[报告](</workspace/ocean/.run/中文 文件/report.md>)\n\n![频谱](<.run/中文 文件/psd.png>)");
    assert.match(html, /data-artifact-path="\/workspace\/ocean\/\.run\/中文 文件\/report.md"/);
    assert.match(html, /data-artifact-path="\.run\/中文 文件\/psd.png"/);
    assert.match(html, /<img[^>]+src="\/api\/artifacts\/file\?/);
  });
  check("report relative links/images resolve against report parent", () => {
    const html = render("[JSON](result.json)\n\n![图](figures/psd.png)\n\n[根目录](tasks/demo)", ".run/报告 目录");
    assert.match(html, /data-artifact-path="\.run\/报告 目录\/result.json"/);
    assert.match(html, /data-artifact-path="\.run\/报告 目录\/figures\/psd.png"/);
    assert.match(html, /data-artifact-path="tasks\/demo"/);
  });
  check("legacy inline path becomes link; normal inline code stays code", () => {
    const html = render("`.run/result` `nperseg` `>f4`", ".run/report");
    assert.equal((html.match(/data-artifact-path=/g) || []).length, 1);
    assert.match(html, /<code>nperseg<\/code>/);
    assert.match(html, /<code>&gt;f4<\/code>/);
  });
  check("unlabelled, labelled and indented code blocks stay ordinary code", () => {
    for (const source of ["```\n.run/report.md\n```", "```text\n.run/report.md\n```", "    .run/report.md"])
      assert.doesNotMatch(render(source), /data-artifact-path=/, source);
  });
  check("external links/knowledge images keep their original addresses", () => {
    const html = render("[来源](https://example.com/test)\n\n![知识库](http://127.0.0.1:3090/kb/image?p=test)");
    assert.match(html, /href="https:\/\/example.com\/test"/);
    assert.match(html, /src="http:\/\/127.0.0.1:3090\/kb\/image\?p=test"/);
    assert.doesNotMatch(html, /data-artifact-path=/);
  });
  check("raw HTML and JavaScript Markdown links do not execute", () => {
    const html = render('<script>alert(1)</script>\n\n[bad](javascript:alert%281%29)\n\n<img src="x" onerror="alert(1)">');
    assert.doesNotMatch(html, /<script|onerror|href="javascript:/);
  });
  console.log(`${checks} artifact renderer contracts passed`);
} finally { await server.close(); }
