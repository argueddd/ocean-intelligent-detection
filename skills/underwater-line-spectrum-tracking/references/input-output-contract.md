# 输入输出契约

## 正式输入

运行只接受一个 `DetectionTrackingHandoff 1.0.0`。它必须来自一个已完成的 `framewise` 检测任务，并绑定：

- 检测结果与 resolved configuration；
- 完整、未截断的候选表；
- 包含零候选行和跳过行的完整账本；
- 原生采样率、时间映射、窗长、步长、NFFT 和频率网格；
- 原检测包 manifest、候选表和账本的大小及 SHA-256。

runtime 会重新读取并核验候选表和账本。仅有截图、候选摘要、平均谱任务、临时候选或缺失账本均不能执行。交接声明中的 `tracking_performed`、`harmonic_grouping_performed`、`source_association_performed`、`target_identification_performed` 和 `evaluation_performed` 必须均为 false。

## TrackingRequest 1.0.0

请求 Schema 位于 `assets/schemas/TrackingRequest.schema.json`。可执行请求必须：

- `document_status=specified` 且 `unresolved_items=[]`；
- 给出唯一 `tracking_run_id`；
- 用绝对路径和 SHA-256 固定交接文件；
- 给出一个尚不存在的绝对输出目录；
- 明确所有算法参数；
- 明确是否保存轨迹图。

算法参数：

| 字段 | 语义 |
|---|---|
| prediction_mode | `last_frequency` 或 `constant_velocity` |
| frequency_gate_hz | 候选相对预测频率的最大绝对残差 |
| frequency_rate_gate_hz_per_s | 相邻已关联观测的最大绝对频率变化率；null 表示明确禁用 |
| power_change_gate_db | 相邻已关联观测的最大绝对功率变化；null 表示明确禁用 |
| frequency_cost_weight | 归一化频率残差代价权重 |
| power_cost_weight | 归一化功率变化代价权重；未启用功率门限时必须为 0 |
| max_missed_rows | 允许连续越过的计数行数；下一行仍未关联才终止 |
| gap_count_basis | `tested_rows_only` 或 `all_rows` |
| min_confirmed_detections | 轨迹标记为 confirmed 所需的最少真实候选点数 |

参数来自用户选择或外部规范，不从本次候选反向优化。Hz、Hz/s、dB 和行数不可混用。

## 候选观测

当前版本使用候选的：

- `candidate_id`、`task_id`；
- `frequency.value_hz`；
- `analysis_support.sample_intervals`；
- `extensions.cfar_v1.row`；
- 可选 `measurements[name=power]`。

时间取原半开样本区间的离散样本中心，并用交接中的 `sample_zero_offset_seconds` 映射：

```text
t = sample_zero_offset_seconds + (start + stop - 1) / (2 * sample_rate_hz)
```

v1 每个检测行只接受一个连续样本区间。多个不连续区间不能压成一个伪中心时间。

## 输出

execute 创建新目录，至少包含：

- `tracking-result.json`：符合 `TrackingResult 1.0.0` 的完整结果；
- `resolved-request.json`：本次请求快照；
- `review.json`：实际执行前重新生成的 review；
- `package-manifest.json`：上述文件及可选图片的大小和 SHA-256；
- `frequency-tracks.png`：仅当 `save_plot=true`。

结果中的轨迹点逐一引用原 `candidate_id`；结果不修改、复制替代或隐藏原检测证据。
