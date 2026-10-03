import React from "react";
import { createRoot } from "react-dom/client";
import { ArtifactProvider } from "../src/components/ArtifactPreview";
import { Markdown } from "../src/lib/markdown";
import "../src/styles.css";

const content = `# 产物预览隔离验证

此页使用工作台相同组件，不读取或修改真实会话历史。

[测试结果目录](.run/artifact-ui-smoke)

[测试报告](.run/artifact-ui-smoke/report-data-characteristics.md)

[中文与空格报告](<.run/artifact-ui-smoke/中文 空格/报告.md>)

旧路径：\`.run/artifact-ui-smoke/中文 空格\`

未标语言的代码块应保留：

\`\`\`
.run/this-is-fenced-code
\`\`\`

[外部链接](https://example.com) · 普通代码：\`nperseg\`
`;

createRoot(document.getElementById("root")).render(<ArtifactProvider><main style={{ maxWidth: 900, margin: "40px auto", padding: 24 }}><Markdown>{content}</Markdown></main></ArtifactProvider>);
