# 波束形成评价运行时 V1

状态：运行时 1.0.0，请求/结果契约 1.0.0。它只读取已有数组或表格，不计算波束、不修改上游结果、不自动选方向或目标。

## 1. 请求

从 `assets/templates/EvaluationRequest.draft.json` 开始。`specified` 请求需要：

- 评价模式：`descriptive`、`paper`、`engineering` 或 `dual`；
- 一个或多个 job，每个 job 有唯一 ID、命令、主题、输入文件引用、参数、证据状态和限制；
- 每个文件引用的路径和 SHA-256；
- 真值、基线、可比性和独立性状态；
- 绝对、尚未存在的输出目录；
- `confirmation.status=recorded` 和真实确认陈述。

请求本身不安全地接收任意命令行；`command` 只能为 8 个数值入口，输入角色和参数名会按命令白名单核对。

## 2. 输入角色

| command | 必须输入 | 可选输入 |
|---|---|---|
| `spectrum` | `power` | `angles` |
| `doa` | `estimates` | `truth` |
| `freq-bearing` | `matrix` | `freqs`, `angles` |
| `btr` | `matrix` | `times`, `angles`, `truth_track` |
| `signal` | `signal` | `baseline`, `reference` |
| `spectrum-output` | `spectrum`, `freqs` | `baseline` |
| `time-frequency` | `matrix`, `freqs` | `times`, `baseline` |
| `compare` | `metrics`, `spec` | 无 |

`truth_deg` 是 `spectrum` / `freq-bearing` 的显式参数。一旦提供真值文件或 `truth_deg`，`evidence.truth_status` 必须为 `provided` 并说明覆盖。提供 `baseline` 时也必须显式声明。`compare` 只在 `comparability=confirmed` 时执行；否则分开评价，不排名。

## 3. 命令

```bash
python3 -B scripts/validate_contract.py request.json --expect EvaluationRequest
python3 -B scripts/evaluation_runtime.py request.json --preflight-only
python3 -B scripts/evaluation_runtime.py request.json --output-dir /absolute/new/output
```

预检只读，实际打开引用文件并核对 SHA-256、输入角色、证据声明、确认状态和输出目录。`--output-dir` 必须与请求内容完全一致。

执行先在输出目录同级临时目录写入，结果契约校验通过后原子发布。已存在目录始终阻断，不覆盖、不合并、不删除历史包。

## 4. 输出

核心文件：

- `evaluation-result.json`：结果契约、证据等级、job 结果、验收边界和限制；
- `resolved-evaluation-config.json`：实际文件路径、摘要、大小和参数；
- `job-results.json`：各数值命令的完整 JSON 输出；
- `package-manifest.json`：包内文件摘要清单；
- `metrics.csv`、`report.md`：仅在请求中选择时生成。

`metrics.csv` 只展平标量；匹配预览、轨迹预览和对比结构仍以 JSON 为完整证据。没有显式阈值时，`acceptance.status=not_requested`。

## 5. V1 限制

- 数组输入为 CSV/NPY，项目自定义 MAT/二进制需先做无损、可追溯适配。
- 不从时域信号自动估计真值片段，不从频谱自动挑目标带。
- BTR 无真值模式是单主脊线描述，不支持多目标身份跟踪。
- 不估计统计置信区间或相关快拍的有效样本量；需要时必须另行声明方法和假设。
- 不自动判断目标身份、归属、轨迹或调优参数。
