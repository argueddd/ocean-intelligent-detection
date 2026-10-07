# 评价运行与交付 1.0.0

## 输入

`EvaluationRequest 1.0.0` 引用：

- primary `TrackingResultPackage` 目录和 `package-manifest.json` SHA-256；
- 可选 baseline 包；
- 可选 `TrackingTruthLabels` 文件路径与 SHA-256；
- 描述设置、真值匹配规则、验收阈值和新输出目录。

runtime 会重新读取 manifest 中全部文件，核对大小和摘要，并验证 `tracking-result.json`。它不会读取或修改原始波形、检测包，也不会调用跟踪执行器。

## 命令

只读 review：

```text
python3 scripts/evaluation_runtime.py review /absolute/EvaluationRequest.json
```

独立执行：

```text
python3 scripts/evaluation_runtime.py execute /absolute/EvaluationRequest.json \
  --review-sha256 <review_sha256>
```

输出目录必须不存在。执行器在同级临时目录完成 Schema 和一致性检查后原子发布；任何输入变化都会使旧 review 摘要失效。

## 输出包

核心文件：

- `evaluation-result.json`
- `resolved-evaluation-config.json`
- `review.json`
- `metrics.csv`
- `report.md`
- `package-manifest.json`

有真值且 `save_matches=true` 时增加 `matches.json`；`save_plots=true` 时增加 `track-length-summary.png`，有匹配误差时再增加 `frequency-error-histogram.png`。

## 运行状态

结构校验通过只表示“结果格式与内部计数一致”。无真值描述评价完成，不表示跟踪质量通过。有真值指标完成也只覆盖标签声明的范围。验收结论只针对请求中的指标和阈值。
