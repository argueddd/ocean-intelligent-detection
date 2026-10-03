import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { groupToolSteps, parseToolArguments, toolProgress, toolResultDetail, toolResultState, toolStatusLabel } from "../src/lib/tool-progress.js";

let checks = 0;
function check(name, fn) { fn(); checks += 1; console.log(`PASS ${name}`); }
const tool = (name, args, status = "done", id = "t1") => ({ role: "tool", kind: "tool", id, name, args, argsText: JSON.stringify(args), status });
const inspect = ".venv/bin/python skills/underwater-data-inspection/scripts/inspect_data.py";

check("native Chinese description supplies purpose and live activity", () => {
  const card = tool("bash", { command: `${inspect} run source.sio --config config.json`, description: "计算 PSD，观察能量集中在哪些频率" }, "running");
  const progress = toolProgress(card);
  assert.equal(progress.title, "计算 PSD，观察能量集中在哪些频率");
  assert.equal(progress.activity, "正在计算 PSD，观察能量集中在哪些频率");
  assert.equal(progress.label, "代码执行");
  assert.equal(progress.source, "description");
});
check("purpose alias and whitespace are plain text", () => {
  assert.equal(toolProgress(tool("run_code", { purpose: "正在检查\n有限值统计" })).activity, "正在检查 有限值统计");
  assert.equal(toolProgress(tool("bash", { description: "\n", command: "echo ok" })).title, "运行代码");
});
check("old English description uses conservative Chinese invocation category", () => {
  for (const [mode, title] of [["probe", "探查数据格式与存储结构"], ["run", "执行数据体检与分析流程"], ["execute", "执行已配置的数据处理流程"]]) {
    assert.equal(toolProgress(tool("bash", { command: `cd .run && ${inspect} ${mode} "中文 数据.sio"`, description: "Run inspection" })).title, title);
  }
});
check("script names in read/grep/echo/Python string/heredoc never imply execution", () => {
  for (const command of ["cat skills/inspect_data.py", "grep run skills/inspect_data.py", "echo 'python inspect_data.py probe'", `python -c "print('${inspect} run')"`, `python - <<'PY'\nprint('${inspect} probe')\nPY`]) {
    assert.doesNotMatch(toolProgress(tool("bash", { command })).title, /探查数据格式|执行数据体检/);
    assert.equal(toolResultState(tool("bash", { command }), "body\n[exit code: 2]"), "error");
  }
});
check("unknown commands/tools stay honest and cannot merge into a verification step", () => {
  for (const card of [tool("bash", { command: "custom_experiment --foo" }), tool("new_tool", {}), tool("fs", { action: "unknown" })]) {
    assert.match(toolProgress(card).title, /运行代码|执行本次工具请求|文件操作请求/);
    assert.doesNotMatch(toolProgress(card).title, /校验|完整性|PSD|通过|合格/);
    assert.equal(toolProgress(card).groupKey, undefined);
  }
});
check("file and Skill actions hide paths and distinguish read from report generation", () => {
  assert.equal(toolProgress(tool("read", { file_path: ".run/summary.md" })).title, "读取已有分析摘要");
  assert.equal(toolProgress(tool("write", { file_path: ".run/report-final.md" })).title, "保存分析报告");
  assert.equal(toolProgress(tool("read", { file_path: ".run/result.json" })).title, "读取已有计算结果");
  assert.equal(toolProgress(tool("skill", { name: "underwater-data-inspection" })).title, "加载数据体检与分析方法");
});
check("job reads, waits and task stops have distinct purposes", () => {
  assert.equal(toolProgress(tool("job_output", { job_id: "j1", wait: true })).title, "等待后台任务并读取进展");
  assert.equal(toolProgress(tool("job_output", { job_id: "j1" })).title, "读取后台任务进展");
  assert.equal(toolProgress(tool("job_kill", { job_id: "j1" })).title, "停止指定的后台任务");
});
check("bash nonzero SDK terminal markers preserve failure and inspection partial status", () => {
  assert.equal(toolResultState(tool("bash", { command: `${inspect} probe source.sio` }), "body\n[exit code: 2]"), "partial");
  assert.equal(toolResultState(tool("bash", { command: `${inspect} execute --config config.json` }), "body\n[exit code: 2]"), "partial");
  assert.equal(toolResultState(tool("bash", { command: `${inspect} run source.sio` }), "body\n[exit code: 1]"), "error");
  assert.equal(toolResultState(tool("bash", { command: "ls missing" }), "body\n[exit code: 2]"), "error");
  assert.equal(toolResultState(tool("bash", { command: `${inspect} probe source.sio` }), "body\n[exit code: 2]", true), "error");
});
check("history authoritative error/partial survives truncated result text", () => {
  assert.equal(toolResultState(tool("bash", { command: "ls" }, "error"), "first 4000 chars"), "error");
  assert.equal(toolResultState(tool("bash", { command: `${inspect} probe source.sio` }, "partial"), "first 4000 chars"), "partial");
  const live = tool("bash", { command: `${inspect} run source.sio`, description: "计算三通道基础频谱" }, "running");
  const historic = { ...live, args: undefined, argsText: JSON.stringify(live.args), status: "partial" };
  assert.equal(toolProgress(live).title, toolProgress(historic).title);
  assert.equal(toolResultState(live, "body\n[exit code: 2]"), toolResultState(historic, "truncated"));
});
check("exit code belongs to the final actual invocation, excluding module strings and malformed quotes", () => {
  for (const command of [`${inspect} run source.sio; python unrelated.py`, `${inspect} probe source.sio | tail -20`, "python -m inspect_data.py run source.sio", `${inspect} run 'source.sio`])
    assert.equal(toolResultState(tool("bash", { command }), "out\n[exit code: 2]"), "error", command);
  const compound = `${inspect} run source.sio; python unrelated.py`;
  assert.equal(toolProgress(tool("bash", { command: compound })).title, "执行数据体检与分析流程");
  assert.equal(toolResultState(tool("bash", { command: `cd .run && ${inspect} run source.sio` }), "out\n[exit code: 2]"), "partial");
});
check("ordinary error text or nonterminal code-like lines do not cause false failure", () => {
  for (const text of ["error_count: 0", "The docs mention [exit code: 2]", "out\n  [exit code: 2]", "[exit code: 2]\nThis is quoted output", '{"error":null}'])
    assert.equal(toolResultState(tool("bash", { command: "echo ok" }), text), "done");
});
check("timeouts and killed SDK markers are failures", () => {
  assert.equal(toolResultState(tool("bash", {}), "out\n[timed out after 3000ms]"), "error");
  assert.equal(toolResultState(tool("bash", {}), "out\n[killed by signal: SIGTERM]"), "error");
});
check("job terminal states preserve failed/unknown-source exits without inventing partial", () => {
  for (const marker of ["[status: failed]", "[status: killed, signal: SIGTERM]", "[status: completed, exit code: 2]"])
    assert.equal(toolResultState(tool("job_output", { job_id: "j1" }), marker), "error");
  const running = { ...tool("job_output", { job_id: "j1" }), resultText: "out\n[status: running]" };
  assert.equal(toolStatusLabel(running), "后台运行中");
  assert.match(toolResultDetail(running.resultText, "done", "job_output"), /仍在运行/);
});
check("completed adjacent locating calls group while preserving every original record", () => {
  const calls = [tool("bash", { command: "ls data" }, "done", "a"), tool("bash", { command: "ls results" }, "done", "b"), tool("glob", { pattern: "*.sio" }, "done", "c")];
  const before = JSON.stringify(calls); const groups = groupToolSteps(calls);
  assert.equal(groups.length, 1); assert.equal(groups[0].cards.length, 3);
  assert.deepEqual(groups[0].cards.map(card => card.id), ["a", "b", "c"]);
  assert.equal(JSON.stringify(calls), before);
});
check("failed/partial/active/approval/message steps break grouping and stay visible", () => {
  for (const barrier of [tool("bash", { command: "ls data" }, "error", "e"), tool("bash", { command: "ls data" }, "partial", "p"), tool("bash", { command: "ls data" }, "running", "r"), { role: "approval", id: "approval", status: "pending" }, { role: "assistant", id: "answer", content: "说明" }]) {
    const calls = [tool("bash", { command: "ls data" }, "done", "a"), barrier, tool("bash", { command: "ls results" }, "done", "b")];
    const groups = groupToolSteps(calls); assert.equal(groups.length, 3); assert.equal(groups[1], barrier);
  }
});
check("polls for different job ids cannot merge", () => {
  assert.equal(groupToolSteps([tool("job_output", { job_id: "a" }), tool("job_output", { job_id: "b" })]).length, 2);
});
check("result summary never exposes raw JSON or command output by default", () => {
  assert.equal(toolResultDetail('{"shape":[90000,3]}', "done", "bash"), "已取得工具返回结果。");
  assert.equal(toolResultDetail("failed command: secret-detail", "error", "bash"), "此步骤执行失败，展开查看错误信息。");
});
check("malformed arguments remain safe and inspectable", () => {
  assert.deepEqual(parseToolArguments("not JSON"), {});
  assert.deepEqual(parseToolArguments("[]"), {});
  assert.equal(toolProgress({ name: "bash", argsText: "not JSON" }).title, "运行代码");
});

const server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), server: { middlewareMode: true }, appType: "custom" });
try {
  const { ToolCard, ToolGroup, ToolDebugDetails, TimelineDrawer, ApprovalCard } = await server.ssrLoadModule("/src/components/AgentChat.jsx");
  const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));
  const card = { ...tool("bash", { command: "python raw_command.py --input /a/private/file", description: "计算 PSD 并保存结果", timeoutMs: 1000 }, "done"), resultText: "RAW_RESULT_SENTINEL" };
  check("collapsed card presents purpose, category and status; hides command/path/output", () => {
    const html = render(ToolCard, { card });
    assert.match(html, /计算 PSD 并保存结果/); assert.match(html, /代码执行/); assert.match(html, /执行完成/);
    assert.match(html, /aria-expanded="false"/); assert.doesNotMatch(html, /raw_command|private\/file|RAW_RESULT_SENTINEL/);
  });
  check("expanded debug details retain full raw command, arguments and output", () => {
    const longCard = { ...card, resultText: "X".repeat(5000) + "END_OF_FULL_OUTPUT" };
    const html = render(ToolCard, { card: longCard, initialOpen: true });
    assert.match(html, /raw_command\.py/); assert.match(html, /查看全部输入参数/); assert.match(html, /timeoutMs/); assert.match(html, /END_OF_FULL_OUTPUT/);
    assert.match(render(ToolDebugDetails, { card: longCard }), /END_OF_FULL_OUTPUT/);
  });
  check("failure and partial cards visibly retain different statuses without raw output leakage", () => {
    for (const [status, label] of [["error", "执行失败"], ["partial", "部分完成"]]) {
      const html = render(ToolCard, { card: { ...card, status } });
      assert.match(html, new RegExp(label)); assert.match(html, new RegExp(`is-${status}`)); assert.doesNotMatch(html, /RAW_RESULT_SENTINEL/);
    }
  });
  check("group hides technical details but expanded group preserves each step purpose", () => {
    const cards = [tool("bash", { command: "ls raw_dir1", description: "定位输入数据" }, "done", "a"), tool("bash", { command: "ls raw_dir2", description: "定位已有结果" }, "done", "b")];
    const group = groupToolSteps(cards)[0];
    assert.doesNotMatch(render(ToolGroup, { group }), /raw_dir1|raw_dir2/);
    const expanded = render(ToolGroup, { group, initialOpen: true });
    assert.match(expanded, /定位输入数据/); assert.match(expanded, /定位已有结果/); assert.doesNotMatch(expanded, /raw_dir1|raw_dir2/);
  });
  check("timeline uses the same purpose, preserves failure and hides raw data inside details", () => {
    const item = { ...card, kind: "tool", title: toolProgress(card).title, status: "error", detail: toolResultDetail(card.resultText, "error", card.name) };
    const html = render(TimelineDrawer, { open: true, onClose() {}, timeline: [item], activity: "waiting" });
    assert.match(html, /计算 PSD 并保存结果/); assert.match(html, /执行失败/); assert.match(html, /包含未完成步骤/);
    assert.match(html, /<details class="chat-timeline-debug"><summary>查看执行详情<\/summary>/);
    assert.doesNotMatch(html, /role="progressbar"/);
  });
  check("knowledge-mode facts remain available with a purpose-oriented header", () => {
    const html = render(ToolCard, { card: { ...tool("kb_status", {}), resultJson: { engine: { status: "online", pipeline_busy: false }, stats: { active: 3 } } } });
    assert.match(html, /查看知识库运行状态/); assert.match(html, /online/); assert.match(html, /生效文档：3/);
  });
  check("approval pending/allowed/rejected states and decision controls remain intact", () => {
    const base = { toolName: "kb_ingest", reason: "将指定文档加入知识库", status: "pending" };
    const pending = render(ApprovalCard, { card: base, onDecide() {} });
    assert.match(pending, /需要你的批准/); assert.match(pending, /批准执行/); assert.match(pending, /拒绝/);
    assert.match(render(ApprovalCard, { card: { ...base, status: "allowed" }, onDecide() {} }), /已批准/);
    assert.match(render(ApprovalCard, { card: { ...base, status: "rejected" }, onDecide() {} }), /已拒绝/);
  });
  console.log(`${checks} tool progress contracts passed`);
} finally { await server.close(); }
