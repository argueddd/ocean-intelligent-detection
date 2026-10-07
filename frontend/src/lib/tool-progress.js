/** Tool progress is an action description, never a claim that the data passed inspection. */
const LABELS = {
  fs: "文件操作", read: "读取文件", write: "保存文件", edit: "更新文件",
  glob: "查找文件", grep: "搜索内容", bash: "代码执行", skill: "加载 Skill",
  read_image: "读取图像", vision_inspect: "视觉核验", todo_write: "组织任务",
  run_code: "执行工具流程", job_output: "后台任务", job_list: "后台任务", job_kill: "后台任务",
  lightrag_query_data: "知识检索", kb_ingest: "文档入库", kb_update: "知识更新",
  kb_status: "健康状态", kb_analyze: "知识库体检", kb_report: "运营报告",
  kb_graph_search: "图谱检索", kb_feedback_inbox: "反馈收件箱",
  kb_feedback_context: "反馈上下文", kb_diagnosis_submit: "诊断提交",
};

export const toolLabel = (name) => LABELS[name] || "扩展工具";
export const toolStateLabel = (status) => ({ running: "执行中", cancelling: "正在停止", "stop-unconfirmed": "停止未确认", done: "执行完成", error: "执行失败", partial: "部分完成", pending: "等待批准", allowed: "已批准", rejected: "已拒绝", interrupted: "已中断" })[status] || "状态未知";

export function parseToolArguments(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) return value;
  try { const parsed = JSON.parse(value || "{}"); return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {}; }
  catch { return {}; }
}

const basename = (value) => String(value || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop();
const filePath = (args) => args.file_path || args.path || "";

function fileAction(path, writing = false) {
  const name = basename(path);
  if (/^summary\.md$/i.test(name)) return writing ? "保存分析摘要" : "读取已有分析摘要";
  if (/report.*\.md$/i.test(name)) return writing ? "保存分析报告" : "读取已有分析报告";
  if (/^result\.json$/i.test(name)) return writing ? "保存计算结果" : "读取已有计算结果";
  if (/(?:config|cfg).*\.json$|(?:config|cfg)\.json$/i.test(name)) return writing ? "保存任务参数配置" : "读取任务参数配置";
  if (/SKILL\.md$/i.test(name)) return writing ? "更新处理方法说明" : "读取处理方法说明";
  if (/data-contract\.md$|analysis-guide\.md$/i.test(name)) return "读取数据格式与分析约定";
  if (/\.(?:sio|wav|h5|hdf5|npy|npz|mat)$/i.test(name)) return writing ? "保存数据文件" : "读取数据文件";
  return writing ? "保存文件内容" : "读取文件内容";
}

/** A small lexer for classification only: quoted strings stay arguments, never executed here. */
function shellCommands(source) {
  if (/<<\s*[-]?\s*['"]?\w/.test(source)) return []; // A heredoc body is not a shell command.
  const commands = []; let words = []; let word = ""; let quote = ""; let escape = false;
  const flushWord = () => { if (word) { words.push(word); word = ""; } };
  const flushCommand = () => { flushWord(); if (words.length) commands.push(words); words = []; };
  for (const char of String(source || "")) {
    if (escape) { word += char; escape = false; continue; }
    if (char === "\\" && quote !== "'") { escape = true; continue; }
    if (quote) { if (char === quote) quote = ""; else word += char; continue; }
    if (char === "'" || char === '"') { quote = char; continue; }
    if (/[;|&\n]/.test(char)) { flushCommand(); continue; }
    if (/\s/.test(char)) { flushWord(); continue; }
    word += char;
  }
  if (quote || escape) return [];
  flushCommand();
  return commands.map(parts => {
    while (/^[A-Za-z_]\w*=/.test(parts[0] || "")) parts = parts.slice(1);
    return parts;
  }).filter(parts => parts.length);
}

function inspectionMode(command, finalCommandOnly = false) {
  const commands = shellCommands(command);
  for (const words of finalCommandOnly ? commands.slice(-1) : commands) {
    const executable = basename(words[0]);
    const python = /^python(?:\d+(?:\.\d+)?)?$/.test(executable);
    const scriptIndex = python ? words.findIndex((value, index) => index > 0 && !value.startsWith("-")) : 0;
    // Do not read Python -c strings, shell echo output, grep targets or file contents as invocations.
    if (python && (words.includes("-c") || words.includes("-m"))) continue;
    if (basename(words[scriptIndex]) === "inspect_data.py") {
      const mode = words[scriptIndex + 1];
      if (["probe", "run", "execute"].includes(mode)) return mode;
    }
  }
  return null;
}

const BEAMFORMING_ACTIONS = {
  "preflight.py": { check: "检查波束方案与参数确认记录", digests: "计算波束方案与参数组摘要" },
  "execute.py": { check: "检查波束计算参数与执行门禁", digest: "计算波束计算范围摘要", run: "按已确认方案计算波束与所选结果" },
  "inspection_handoff.py": { review: "查看已有体检结果与波束交接缺口", check: "检查波束输入导出参数与来源", digest: "计算波束输入导出范围摘要", prepare: "导出已确认的波束输入与待确认方案" },
  "analyze_results.py": { check: "检查已保存波束与补图参数", digest: "计算波束补图范围摘要", run: "计算已选波束的谱与图" },
  "bypass_handoff.py": { review: "查看单阵元或已有波束的交接信息", check: "检查单阵元或已有波束的交接参数", digest: "计算旁路交接范围摘要", prepare: "准备已选单阵元或波束的交接包", receive: "检查接收的单阵元或波束交接包" },
};

function skillScriptInvocations(command, workdir, skillName) {
  const invocations = [];
  for (const words of shellCommands(command)) {
    const python = /^python(?:\d+(?:\.\d+)?)?$/.test(basename(words[0]));
    let scriptIndex = 0;
    if (python) {
      scriptIndex = 1;
      while (words[scriptIndex]?.startsWith("-")) {
        const option = words[scriptIndex++];
        // Inline code, modules and informational modes never run a script argument.
        if (/^-[cm]/.test(option) || ["-h", "--help", "-V", "--version"].includes(option)) { scriptIndex = -1; break; }
        if (option === "--") break;
        if (["-W", "-X", "--check-hash-based-pycs"].includes(option)) scriptIndex++;
      }
      if (scriptIndex < 0) continue;
    }
    const script = words[scriptIndex] || "";
    const source = /^[\\/]|^[A-Za-z]:/.test(script) ? script : `${workdir || ""}/${script}`;
    const parts = [];
    for (const part of source.split(/[\\/]/)) {
      if (part === "..") parts.pop();
      else if (part && part !== ".") parts.push(part);
    }
    // Generic script filenames require this Skill's actual path or working directory.
    if (parts.slice(-3).join("/") !== `${skillName}/scripts/${basename(script)}`) continue;
    invocations.push({ script: basename(script), args: words.slice(scriptIndex + 1) });
  }
  return invocations;
}

function beamformingAction(command, workdir) {
  for (const { script, args } of skillScriptInvocations(command, workdir, "underwater-beamforming")) {
    const title = BEAMFORMING_ACTIONS[script]?.[args[0]];
    if (title) return { title };
  }
  return null;
}

function lineSpectrumEvaluationAction(command, workdir) {
  for (const { script, args } of skillScriptInvocations(command, workdir, "underwater-line-spectrum-evaluation")) {
    if (args.some(value => ["-h", "--help"].includes(value))) continue;
    if (script === "validate_contract.py") return { title: "检查线谱评价文档字段与局部一致性" };
    if (script === "validate_truth_labels.py") return { title: "检查线谱真值标签格式" };
    if (script !== "evaluation_runtime.py") continue;
    const options = args.includes("--") ? args.slice(0, args.indexOf("--")) : args;
    if (options.includes("--preflight-only")) return { title: "检查线谱评价输入与跨文档证据" };
    if (options.some(value => value === "--output-dir" || value.startsWith("--output-dir="))) return { title: "计算已确认的线谱评价指标" };
  }
  return null;
}

function lineSpectrumTrackingAction(command, workdir) {
  for (const { script, args } of skillScriptInvocations(command, workdir, "underwater-line-spectrum-tracking")) {
    if (args.some(value => ["-h", "--help"].includes(value))) continue;
    if (script === "validate_contract.py") return { title: "检查线谱跟踪请求、交接与结果契约" };
    if (script !== "tracking_runtime.py") continue;
    if (args[0] === "review") return { title: "核对逐窗候选、帧账本与跟踪参数" };
    if (args[0] === "execute") return { title: "按已确认门限关联线谱频率轨迹" };
  }
  return null;
}

function lineSpectrumTrackingEvaluationAction(command, workdir) {
  for (const { script, args } of skillScriptInvocations(command, workdir, "underwater-line-spectrum-tracking-evaluation")) {
    if (args.some(value => ["-h", "--help"].includes(value))) continue;
    if (script === "validate_contract.py") return { title: "检查线谱轨迹评价请求与证据契约" };
    if (script !== "evaluation_runtime.py") continue;
    if (args[0] === "review") return { title: "核对轨迹包、真值范围与评价条件" };
    if (args[0] === "execute") return { title: "计算已确认的线谱轨迹评价指标" };
  }
  return null;
}

function beamformingEvaluationAction(command, workdir) {
  for (const { script, args } of skillScriptInvocations(command, workdir, "underwater-beamforming-evaluation")) {
    if (args.some(value => ["-h", "--help"].includes(value))) continue;
    if (script === "validate_contract.py") return { title: "检查波束评价请求与字段约束" };
    if (script === "evaluation_runtime.py") {
      const options = args.includes("--") ? args.slice(0, args.indexOf("--")) : args;
      if (options.includes("--preflight-only")) return { title: "检查波束评价输入、摘要与证据边界" };
      if (options.some(value => value === "--output-dir" || value.startsWith("--output-dir="))) return { title: "计算已确认的波束评价指标" };
      return { title: "执行已确认的波束结果评价" };
    }
    if (script !== "beamforming_metrics.py") continue;
    const titles = {
      spectrum: "评价空间谱主瓣、旁瓣与峰结构",
      doa: "评价方位估计误差与匹配结果",
      "freq-bearing": "评价频率—方位响应结构",
      btr: "评价波束方位随时间的稳定性",
      signal: "评价波束时域输出与参考关系",
      "spectrum-output": "评价波束输出频谱特征",
      "time-frequency": "评价波束时频输出特征",
      compare: "比较已确认可比的波束算法指标",
      "plot-compare": "生成波束算法指标对比图",
      "plot-pareto": "生成波束算法权衡关系图",
      "plot-scenario-curves": "生成波束性能工况曲线",
      "plot-radar": "生成波束算法多指标雷达图",
    };
    if (titles[args[0]]) return { title: titles[args[0]] };
  }
  return null;
}

function shellAction(command, workdir) {
  const mode = inspectionMode(command);
  if (mode === "probe") return { title: "探查数据格式与存储结构" };
  if (mode === "run") return { title: "执行数据体检与分析流程" };
  if (mode === "execute") return { title: "执行已配置的数据处理流程" };
  const beamforming = beamformingAction(command, workdir);
  if (beamforming) return beamforming;
  const beamEvaluation = beamformingEvaluationAction(command, workdir);
  if (beamEvaluation) return beamEvaluation;
  const tracking = lineSpectrumTrackingAction(command, workdir);
  if (tracking) return tracking;
  const trackingEvaluation = lineSpectrumTrackingEvaluationAction(command, workdir);
  if (trackingEvaluation) return trackingEvaluation;
  const evaluation = lineSpectrumEvaluationAction(command, workdir);
  if (evaluation) return evaluation;
  const commands = shellCommands(command);
  for (const words of commands) {
    const executable = basename(words[0]);
    if (["cat", "head", "tail"].includes(executable)) {
      const target = words.slice(1).find(word => !word.startsWith("-") && !/^\d+$|^\d*>/.test(word));
      if (/\.log$/i.test(target || "")) return { title: "查看任务运行日志", groupKey: `log:${target}`, groupTitle: "查看任务运行进展" };
      if (target && /(?:summary\.md|result\.json|report.*\.md|(?:config|cfg).*\.json|SKILL\.md|data-contract\.md|analysis-guide\.md)$/i.test(basename(target))) {
        // An explicit output redirection writes a file rather than reading an existing report.
        if (/(?:^|\s)>{1,2}\s*[^&\s]/.test(command)) return { title: "写入任务文件" };
        return { title: fileAction(target) };
      }
    }
    if (["ps", "pgrep"].includes(executable)) return { title: "查看任务运行状态", groupKey: "process-status", groupTitle: "查看任务运行进展" };
    if (executable === "sleep") return { title: "等待任务继续运行", groupKey: "wait", groupTitle: "等待任务继续运行" };
    if (["ls", "find", "pwd", "stat", "test"].includes(executable)) return { title: "查看文件与目录", groupKey: "locate", groupTitle: "定位任务需要的文件" };
    if (["grep", "rg"].includes(executable)) return { title: "查找任务所需的信息" };
    if (executable === "mkdir") return { title: "准备任务保存目录" };
    if (["cat", "head", "tail"].includes(executable)) return { title: "读取文件内容" };
  }
  return { title: "运行代码" };
}

function inferredAction(name, args) {
  if (name === "bash") return shellAction(args.command || "", args.workdir);
  if (name === "read") return { title: fileAction(filePath(args)) };
  if (name === "write") return { title: fileAction(filePath(args), true) };
  if (name === "edit") return { title: "更新文件中的指定内容" };
  if (name === "skill") {
    const skillName = args.name || args.skill_name || "";
    return { title: skillName === "underwater-data-inspection" ? "加载数据体检与分析方法" : skillName === "underwater-beamforming-evaluation" ? "加载波束结果评价与证据分析方法" : skillName === "underwater-beamforming" ? "加载波束形成与参数确认方法" : skillName === "underwater-line-spectrum-tracking-evaluation" ? "加载线谱轨迹评价与证据分析方法" : skillName === "underwater-line-spectrum-tracking" ? "加载线谱候选轨迹关联方法" : skillName === "underwater-line-spectrum-evaluation" ? "加载线谱结果评价与证据检查方法" : "加载任务所需的处理方法" };
  }
  if (name === "glob") return { title: "查找任务需要的文件", groupKey: "locate", groupTitle: "定位任务需要的文件" };
  if (name === "fs") return { title: "处理本次文件操作请求" };
  if (name === "grep") return { title: "搜索任务需要的信息" };
  if (name === "job_output") return { title: args.wait ? "等待后台任务并读取进展" : "读取后台任务进展", groupKey: `job:${args.jobId || args.job_id || args.id || "unknown"}`, groupTitle: "查看后台任务进展" };
  const titles = {
    job_list: "查看后台任务列表", job_kill: "停止指定的后台任务",
    read_image: "读取图像内容", vision_inspect: "读取图像并核对可见信息",
    todo_write: "整理任务步骤", run_code: "运行工具流程",
    lightrag_query_data: "检索与问题相关的知识", kb_ingest: "将文档加入知识库",
    kb_update: "更新知识库中的指定内容", kb_status: "查看知识库运行状态",
    kb_analyze: "检查知识库内容与状态", kb_report: "生成知识库运营报告",
    kb_graph_search: "检索知识图谱中的关联", kb_feedback_inbox: "读取用户反馈",
    kb_feedback_context: "读取反馈对应的上下文", kb_diagnosis_submit: "提交诊断结果",
  };
  return { title: titles[name] || "执行本次工具请求" };
}

function descriptionOf(args) {
  for (const value of [args.description, args.purpose]) {
    if (typeof value !== "string") continue;
    const text = value.replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim();
    if (!/[\u3400-\u9fff]/.test(text) || /^(?:\/?[\w.-]+\/|(?:cd|ls|cat|bash|python\d*)\s)/.test(text)) continue;
    return text.length > 80 ? `${text.slice(0, 79)}…` : text;
  }
  return "";
}

/** SDK bash.description is supported today; args.purpose is a compatible future alias. */
export function toolProgress(card) {
  const args = parseToolArguments(card.args || card.argsText);
  const fallback = inferredAction(card.name, args);
  const description = descriptionOf(args);
  const title = description || fallback.title;
  return { ...fallback, title, label: toolLabel(card.name), activity: `正在${title.replace(/^正在/, "")}`, source: description ? "description" : "classification" };
}

/** Group only completed, adjacent bookkeeping steps. Failures, approvals and active work stay visible. */
export function groupToolSteps(items) {
  const output = [];
  for (const item of items) {
    const progress = item.progress || toolProgress(item);
    const eligible = (item.role === "tool" || item.kind === "tool") && item.status === "done" && progress.groupKey;
    const previous = output.at(-1);
    if (eligible && previous?.role === "tool-group" && previous.progress.groupKey === progress.groupKey) {
      previous.cards.push(item); continue;
    }
    if (eligible && (previous?.role === "tool" || previous?.kind === "tool") && previous.status === "done" && (previous.progress || toolProgress(previous)).groupKey === progress.groupKey) {
      output[output.length - 1] = { role: "tool-group", kind: "tool-group", id: previous.id, status: "done", cards: [previous, item], progress };
    } else output.push(item);
  }
  return output;
}

function jobMarker(text) {
  return String(text || "").trimEnd().split("\n").at(-1)?.match(/^\[status: (running|stopping|completed|failed|killed)(?:, (.*))?\]$/);
}

export function toolResultState(card, text, isError = false) {
  if (isError || card.status === "error") return "error";
  if (card.status === "partial") return "partial"; // The history API determines this before truncating output.
  if (["cancelling", "stop-unconfirmed", "interrupted"].includes(card.status)) return card.status;
  const lastLine = String(text || "").trimEnd().split("\n").at(-1) || "";
  const exit = card.name === "bash" ? lastLine.match(/^\[exit code: (-?\d+)\]$/) : null;
  if (exit && Number(exit[1]) !== 0) {
    return Number(exit[1]) === 2 && inspectionMode(parseToolArguments(card.args || card.argsText).command || "", true) ? "partial" : "error";
  }
  if (card.name === "bash" && /^\[(?:timed out after \d+ms|killed by signal: [^\]]+)\]$/.test(lastLine)) return "error";
  if (card.name === "job_output") {
    const marker = jobMarker(text);
    if (marker && ["failed", "killed"].includes(marker[1])) return "error";
    if (marker?.[1] === "completed" && /^exit code: -?\d+$/.test(marker[2] || "") && Number(marker[2].slice(11)) !== 0) return "error";
  }
  return "done";
}

export function toolStatusLabel(card) {
  if (card.name === "job_output" && card.status === "done") {
    const marker = jobMarker(card.resultText);
    if (marker && ["running", "stopping"].includes(marker[1])) return marker[1] === "running" ? "后台运行中" : "后台停止中";
  }
  if (card.name === "bash" && card.status === "done" && /^started background job \S+$/.test(String(card.resultText || "").trim())) return "任务已启动";
  return toolStateLabel(card.status);
}

export function toolResultDetail(text, state, name) {
  if (state === "cancelling") return "正在等待服务端停止此步骤。";
  if (state === "stop-unconfirmed") return "停止尚未确认，任务可能仍在执行。";
  if (state === "interrupted") return "此步骤已中断，未取得完成结果。";
  if (state === "error") return "此步骤执行失败，展开查看错误信息。";
  if (state === "partial") return "流程部分完成，仍需补充信息；展开查看返回结果。";
  if (name === "job_output") {
    const marker = jobMarker(text);
    if (marker?.[1] === "running") return "已读取任务进展，后台任务仍在运行。";
    if (marker?.[1] === "stopping") return "已读取任务进展，后台任务正在停止。";
  }
  if (name === "bash" && /^started background job \S+$/.test(String(text || "").trim())) return "后台任务已启动，正在执行。";
  return String(text || "").trim() ? "已取得工具返回结果。" : "工具执行结束，未返回文本。";
}
