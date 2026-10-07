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
const beamform = ".venv/bin/python skills/underwater-beamforming/scripts";
const beamEvaluate = ".venv/bin/python skills/underwater-beamforming-evaluation/scripts";
const detect = ".venv/bin/python skills/underwater-line-spectrum-detection/scripts";
const evaluate = ".venv/bin/python skills/underwater-line-spectrum-evaluation/scripts";
const track = ".venv/bin/python skills/underwater-line-spectrum-tracking/scripts";
const trackEvaluate = ".venv/bin/python skills/underwater-line-spectrum-tracking-evaluation/scripts";

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
check("beamforming preflight and numerical execution have distinct purpose labels", () => {
  for (const [script, mode, title] of [
    ["preflight.py", "check", "检查波束方案与参数确认记录"],
    ["preflight.py", "digests", "计算波束方案与参数组摘要"],
    ["execute.py", "check", "检查波束计算参数与执行门禁"],
    ["execute.py", "digest", "计算波束计算范围摘要"],
    ["execute.py", "run", "按已确认方案计算波束与所选结果"],
  ]) {
    const progress = toolProgress(tool("bash", { command: `${beamform}/${script} ${mode} execution.json`, description: "Run beamforming" }));
    assert.equal(progress.title, title);
    assert.equal(progress.activity, `正在${title}`);
    assert.equal(progress.source, "classification");
    assert.equal(progress.groupKey, undefined);
  }
});
check("inspection export, saved-beam plotting and bypass handoff do not imply beam calculation", () => {
  for (const [script, modes] of [
    ["inspection_handoff.py", { review: "查看已有体检结果与波束交接缺口", check: "检查波束输入导出参数与来源", digest: "计算波束输入导出范围摘要", prepare: "导出已确认的波束输入与待确认方案" }],
    ["analyze_results.py", { check: "检查已保存波束与补图参数", digest: "计算波束补图范围摘要", run: "计算已选波束的谱与图" }],
    ["bypass_handoff.py", { review: "查看单阵元或已有波束的交接信息", check: "检查单阵元或已有波束的交接参数", digest: "计算旁路交接范围摘要", prepare: "准备已选单阵元或波束的交接包", receive: "检查接收的单阵元或波束交接包" }],
  ]) {
    for (const [mode, title] of Object.entries(modes)) {
      assert.equal(toolProgress(tool("bash", { command: `${beamform}/${script} ${mode} request.json` })).title, title);
    }
  }
});
check("beamforming labels preserve Chinese descriptions and Skill loading uses the right method", () => {
  const progress = toolProgress(tool("bash", { command: `${beamform}/execute.py run execution.json`, description: "计算 CBF 波束，使用已确认方向对比阵列响应" }));
  assert.equal(progress.title, "计算 CBF 波束，使用已确认方向对比阵列响应");
  assert.equal(progress.source, "description");
  assert.equal(toolProgress(tool("skill", { name: "underwater-beamforming" })).title, "加载波束形成与参数确认方法");
  assert.equal(toolProgress(tool("skill", { skill_name: "underwater-beamforming" })).title, "加载波束形成与参数确认方法");
});
check("beamforming invocation supports quoted absolute paths, Python flags and script workdir", () => {
  for (const args of [
    { command: '/workspace/.venv/bin/python3.13 "/workspace/中文 数据/skills/underwater-beamforming/scripts/execute.py" run "配置 文件.json"' },
    { command: "python3 -B -W error::RuntimeWarning -X dev skills/underwater-beamforming/scripts/execute.py run execution.json" },
    { command: "python3 -- execute.py run execution.json", workdir: "/workspace/skills/underwater-beamforming/scripts" },
    { command: "python3 scripts/execute.py run execution.json", workdir: "/workspace/skills/underwater-beamforming" },
    { command: "PYTHONUNBUFFERED=1 python3 execute.py run execution.json", workdir: "/workspace/skills/underwater-beamforming/scripts" },
  ]) assert.equal(toolProgress(tool("bash", args)).title, "按已确认方案计算波束与所选结果");
});
check("generic execute.py and beamforming names in text never acquire an algorithm action", () => {
  for (const command of [
    "python execute.py run execution.json", "python other-skill/scripts/execute.py run execution.json",
    "python skills/underwater-beamforming-other/scripts/execute.py run execution.json",
    `${beamform}/execute.py unknown execution.json`,
    "cat skills/underwater-beamforming/scripts/execute.py",
    "grep run skills/underwater-beamforming/scripts/execute.py",
    `echo '${beamform}/execute.py run execution.json'`,
    `python -c "print('${beamform}/execute.py run execution.json')"`,
    "python -m skills/underwater-beamforming/scripts/execute.py run execution.json",
    `python --help skills/underwater-beamforming/scripts/execute.py run execution.json`,
    `python - <<'PY'\nprint('${beamform}/execute.py run execution.json')\nPY`,
  ]) {
    assert.doesNotMatch(toolProgress(tool("bash", { command })).title, /波束|计算范围摘要|执行门禁/);
    assert.equal(toolResultState(tool("bash", { command }), "out\n[exit code: 2]"), "error");
  }
  // A blocked gate is not the inspection CLI's partial-analysis success.
  assert.equal(toolResultState(tool("bash", { command: `${beamform}/execute.py check execution.json` }), "out\n[exit code: 2]"), "error");
});
check("line-spectrum detection shows input, review, execution and handoff as separate steps", () => {
  for (const [command, title] of [
    [`${detect}/input_adapter.py adapt --handoff handoff.json`, "核对并接收波束时域与来源信息"],
    [`${detect}/input_adapter.py check signal-input.json --handoff handoff.json`, "复核线谱检测输入与上游交接"],
    [`${detect}/validate_contract.py request request.json`, "检查线谱检测请求与结果契约"],
    [`${detect}/detection_runtime.py review request.json context.json --source-root inputs`, "核对检测输入、搜索范围与门限参数"],
    [`${detect}/detection_runtime.py confirm request.json context.json --source-root inputs`, "记录本次线谱检测执行范围"],
    [`${detect}/detection_runtime.py run request.json context.json --source-root inputs`, "计算线谱候选、门限与逐帧账本"],
    [`${detect}/cfar_calibration.py review calibration.json --source-root inputs`, "核对 CFAR 门限标定数据与统计条件"],
    [`${detect}/cfar_calibration.py run calibration.json --source-root inputs`, "标定并验证 CFAR 检测门限"],
    [`${detect}/tracking_handoff.py build result --manifest-sha256 abc --max-read-bytes 100 --output handoff.json`, "整理线谱候选与逐帧账本交接"],
  ]) assert.equal(toolProgress(tool("bash", { command, description: "Run detection" })).title, title);
  assert.equal(toolProgress(tool("skill", { name: "underwater-line-spectrum-detection" })).title, "加载线谱候选检测与门限方法");
});
check("line-spectrum detection names outside the exact Skill path stay generic", () => {
  for (const command of [
    "python detection_runtime.py run request.json context.json",
    "python other-skill/scripts/detection_runtime.py review request.json context.json",
    "cat skills/underwater-line-spectrum-detection/scripts/detection_runtime.py",
    `echo '${detect}/detection_runtime.py run request.json context.json'`,
  ]) assert.doesNotMatch(toolProgress(tool("bash", { command })).title, /线谱候选、门限|检测输入、搜索范围/);
});
check("beamforming evaluation separates request checks, evidence preflight and metric execution", () => {
  for (const [command, title] of [
    [`${beamEvaluate}/validate_contract.py request.json --expect EvaluationRequest`, "检查波束评价请求与字段约束"],
    [`${beamEvaluate}/evaluation_runtime.py request.json --preflight-only`, "检查波束评价输入、摘要与证据边界"],
    [`${beamEvaluate}/evaluation_runtime.py request.json --output-dir .run/beam-evaluation`, "计算已确认的波束评价指标"],
    [`${beamEvaluate}/evaluation_runtime.py request.json --output-dir=.run/beam-evaluation`, "计算已确认的波束评价指标"],
    [`${beamEvaluate}/beamforming_metrics.py spectrum power.npy --angles angles.npy`, "评价空间谱主瓣、旁瓣与峰结构"],
    [`${beamEvaluate}/beamforming_metrics.py doa estimates.npy --truth truth.npy`, "评价方位估计误差与匹配结果"],
    [`${beamEvaluate}/beamforming_metrics.py freq-bearing matrix.npy --freqs frequencies.npy --angles angles.npy`, "评价频率—方位响应结构"],
    [`${beamEvaluate}/beamforming_metrics.py btr matrix.npy --times time.npy --angles angles.npy`, "评价波束方位随时间的稳定性"],
    [`${beamEvaluate}/beamforming_metrics.py signal beam.npy --fs 2000`, "评价波束时域输出与参考关系"],
    [`${beamEvaluate}/beamforming_metrics.py spectrum-output psd.npy --freqs frequencies.npy`, "评价波束输出频谱特征"],
    [`${beamEvaluate}/beamforming_metrics.py time-frequency tf.npy --freqs frequencies.npy --target-band 100:130`, "评价波束时频输出特征"],
    [`${beamEvaluate}/beamforming_metrics.py compare metrics.csv spec.csv`, "比较已确认可比的波束算法指标"],
    [`${beamEvaluate}/beamforming_metrics.py plot-pareto --metrics metrics.csv --spec spec.csv`, "生成波束算法权衡关系图"],
  ]) {
    const progress = toolProgress(tool("bash", { command, description: "Evaluate beamforming outputs" }));
    assert.equal(progress.title, title);
    assert.equal(progress.activity, `正在${title}`);
    assert.doesNotMatch(progress.title, /重新波束|自动选优|通过|合格/);
  }
});
check("beamforming evaluation loading and descriptions preserve its distinct role", () => {
  const described = toolProgress(tool("bash", { command: `${beamEvaluate}/evaluation_runtime.py request.json --preflight-only`, description: "核对空间谱来源与真值覆盖范围" }));
  assert.equal(described.title, "核对空间谱来源与真值覆盖范围");
  assert.equal(described.source, "description");
  for (const args of [{ name: "underwater-beamforming-evaluation" }, { skill_name: "underwater-beamforming-evaluation" }])
    assert.equal(toolProgress(tool("skill", args)).title, "加载波束结果评价与证据分析方法");
  assert.equal(toolProgress(tool("skill", { name: "underwater-beamforming" })).title, "加载波束形成与参数确认方法");
});
check("beamforming evaluation names outside its Skill never imply metric execution", () => {
  for (const command of [
    "python evaluation_runtime.py request.json --preflight-only",
    "python other-skill/scripts/beamforming_metrics.py spectrum power.npy",
    "python skills/underwater-beamforming-evaluation-other/scripts/evaluation_runtime.py request.json --preflight-only",
    "cat skills/underwater-beamforming-evaluation/scripts/evaluation_runtime.py",
    `echo '${beamEvaluate}/evaluation_runtime.py request.json --preflight-only'`,
    `python -c "print('${beamEvaluate}/beamforming_metrics.py spectrum power.npy')"`,
  ]) assert.doesNotMatch(toolProgress(tool("bash", { command })).title, /波束评价|空间谱主瓣|方位估计误差/);
});
check("line-spectrum evaluation distinguishes document checks, evidence preflight and metric execution", () => {
  for (const [command, title] of [
    [`${evaluate}/validate_contract.py request.json --kind EvaluationRequest`, "检查线谱评价文档字段与局部一致性"],
    [`${evaluate}/validate_contract.py coverage.json --kind TruthCoverage`, "检查线谱评价文档字段与局部一致性"],
    [`${evaluate}/validate_truth_labels.py labels.json`, "检查线谱真值标签格式"],
    [`${evaluate}/evaluation_runtime.py request.json --preflight-only`, "检查线谱评价输入与跨文档证据"],
    [`${evaluate}/evaluation_runtime.py request.json --output-dir .run/evaluation`, "计算已确认的线谱评价指标"],
    [`${evaluate}/evaluation_runtime.py request.json --output-dir=.run/evaluation`, "计算已确认的线谱评价指标"],
  ]) {
    const progress = toolProgress(tool("bash", { command, description: "Evaluate candidates" }));
    assert.equal(progress.title, title);
    assert.equal(progress.activity, `正在${title}`);
    assert.equal(progress.groupKey, undefined);
    assert.doesNotMatch(progress.title, /执行检测|重新检测|CFAR|通过|合格/);
  }
});
check("line-spectrum evaluation descriptions remain primary and loading does not imply detection", () => {
  const progress = toolProgress(tool("bash", { command: `${evaluate}/evaluation_runtime.py request.json --output-dir .run/evaluation`, description: "统计已选结果的帧均候选数，包含零候选帧" }));
  assert.equal(progress.title, "统计已选结果的帧均候选数，包含零候选帧");
  assert.equal(progress.source, "description");
  for (const args of [{ name: "underwater-line-spectrum-evaluation" }, { skill_name: "underwater-line-spectrum-evaluation" }])
    assert.equal(toolProgress(tool("skill", args)).title, "加载线谱结果评价与证据检查方法");
  assert.equal(toolProgress(tool("skill", { name: "underwater-line-spectrum-detection" })).title, "加载线谱候选检测与门限方法");
});
check("evaluation invocation resolves quoted paths and workdirs without confusing CLI flags", () => {
  for (const args of [
    { command: 'python3 -B "/workspace/中文 数据/skills/underwater-line-spectrum-evaluation/scripts/evaluation_runtime.py" "评价 请求.json" --preflight-only' },
    { command: "python3 -I -B evaluation_runtime.py request.json --preflight-only", workdir: "/workspace/skills/underwater-line-spectrum-evaluation/scripts" },
    { command: "python3 -- scripts/evaluation_runtime.py request.json --preflight-only", workdir: "/workspace/skills/underwater-line-spectrum-evaluation" },
    { command: "python3 skills/underwater-line-spectrum-evaluation/scripts/../scripts/evaluation_runtime.py request.json --preflight-only" },
    { command: `${evaluate}/evaluation_runtime.py request.json --output-dir .run/evaluation --preflight-only` },
  ]) assert.equal(toolProgress(tool("bash", args)).title, "检查线谱评价输入与跨文档证据");
  for (const command of [`${evaluate}/evaluation_runtime.py request.json`, `${evaluate}/evaluation_runtime.py request.json -- --preflight-only`, `${evaluate}/evaluation_runtime.py --help`])
    assert.equal(toolProgress(tool("bash", { command })).title, "运行代码");
});
check("evaluation script names outside the Skill or mentioned as data never imply evaluation", () => {
  for (const command of [
    "python evaluation_runtime.py request.json --preflight-only",
    "python other-skill/scripts/validate_contract.py request.json",
    "python skills/underwater-line-spectrum-detection/scripts/evaluation_runtime.py request.json --preflight-only",
    "python skills/underwater-line-spectrum-evaluation-other/scripts/evaluation_runtime.py request.json --preflight-only",
    "python skills/underwater-line-spectrum-evaluation/scripts/../../other-skill/scripts/evaluation_runtime.py request.json --preflight-only",
    "cat skills/underwater-line-spectrum-evaluation/scripts/evaluation_runtime.py",
    "grep preflight-only skills/underwater-line-spectrum-evaluation/scripts/evaluation_runtime.py",
    `echo '${evaluate}/evaluation_runtime.py request.json --preflight-only'`,
    `python -c "print('${evaluate}/evaluation_runtime.py request.json --preflight-only')"`,
    `python -cprint('test') skills/underwater-line-spectrum-evaluation/scripts/evaluation_runtime.py request.json --preflight-only`,
    "python -m skills/underwater-line-spectrum-evaluation/scripts/evaluation_runtime.py request.json --preflight-only",
    "python --version skills/underwater-line-spectrum-evaluation/scripts/evaluation_runtime.py request.json --preflight-only",
    `python - <<'PY'\nprint('${evaluate}/evaluation_runtime.py request.json --preflight-only')\nPY`,
  ]) assert.doesNotMatch(toolProgress(tool("bash", { command })).title, /线谱|真值标签|跨文档/);
});
check("line-spectrum tracking shows contract review and confirmed association as separate steps", () => {
  for (const [command, title] of [
    [`${track}/validate_contract.py request /absolute/request.json`, "检查线谱跟踪请求、交接与结果契约"],
    [`${track}/validate_contract.py handoff /absolute/handoff.json`, "检查线谱跟踪请求、交接与结果契约"],
    [`${track}/tracking_runtime.py review /absolute/request.json`, "核对逐窗候选、帧账本与跟踪参数"],
    [`${track}/tracking_runtime.py execute /absolute/request.json --review-sha256 abc`, "按已确认门限关联线谱频率轨迹"],
  ]) {
    const progress = toolProgress(tool("bash", { command, description: "Run tracking" }));
    assert.equal(progress.title, title);
    assert.equal(progress.activity, `正在${title}`);
    assert.doesNotMatch(progress.title, /重新检测|目标识别|评价通过/);
  }
  for (const args of [{ name: "underwater-line-spectrum-tracking" }, { skill_name: "underwater-line-spectrum-tracking" }])
    assert.equal(toolProgress(tool("skill", args)).title, "加载线谱候选轨迹关联方法");
});
check("line-spectrum tracking evaluation keeps review, execution and loading distinct", () => {
  for (const [command, title] of [
    [`${trackEvaluate}/validate_contract.py request /absolute/request.json`, "检查线谱轨迹评价请求与证据契约"],
    [`${trackEvaluate}/validate_contract.py truth /absolute/truth.json`, "检查线谱轨迹评价请求与证据契约"],
    [`${trackEvaluate}/evaluation_runtime.py review /absolute/request.json`, "核对轨迹包、真值范围与评价条件"],
    [`${trackEvaluate}/evaluation_runtime.py execute /absolute/request.json --review-sha256 abc`, "计算已确认的线谱轨迹评价指标"],
  ]) assert.equal(toolProgress(tool("bash", { command })).title, title);
  for (const args of [{ name: "underwater-line-spectrum-tracking-evaluation" }, { skill_name: "underwater-line-spectrum-tracking-evaluation" }])
    assert.equal(toolProgress(tool("skill", args)).title, "加载线谱轨迹评价与证据分析方法");
  assert.equal(toolProgress(tool("skill", { name: "underwater-line-spectrum-tracking" })).title, "加载线谱候选轨迹关联方法");
});
check("tracking script names outside exact Skill paths never imply tracking or evaluation", () => {
  for (const command of [
    "python tracking_runtime.py review request.json",
    "python other-skill/scripts/tracking_runtime.py execute request.json --review-sha256 abc",
    "python skills/underwater-line-spectrum-tracking-other/scripts/tracking_runtime.py review request.json",
    "cat skills/underwater-line-spectrum-tracking/scripts/tracking_runtime.py",
    `echo '${trackEvaluate}/evaluation_runtime.py review request.json'`,
    `python -c "print('${track}/tracking_runtime.py execute request.json')"`,
  ]) assert.doesNotMatch(toolProgress(tool("bash", { command })).title, /轨迹关联|逐窗候选|轨迹评价|轨迹包/);
});
check("failed evaluation checks preserve failure instead of claiming partial inspection success", () => {
  for (const script of ["validate_contract.py", "validate_truth_labels.py", "evaluation_runtime.py"]) {
    for (const code of [1, 2]) assert.equal(toolResultState(tool("bash", { command: `${evaluate}/${script} request.json --preflight-only` }), `out\n[exit code: ${code}]`), "error");
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
