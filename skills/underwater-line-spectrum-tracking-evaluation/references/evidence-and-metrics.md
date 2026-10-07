# 证据与指标

## 1. 先判断证据

| 证据 | 可以支持 | 不能支持 |
|---|---|---|
| 只有完整 TrackingResultPackage | 结构完整性、轨迹数量/长度/占用率、间断和频率步进描述 | 真碎片、假轨迹、漏轨、身份交换、准确率 |
| 局部正轨迹标签 | 已标注点匹配率、频率误差、已标注轨迹被覆盖情况 | 把未标注估计点判作 FP；总体 precision |
| 局部完整正负标签 | 声明覆盖内的点级和轨迹级 precision/recall、误差、碎片、身份交换 | 向覆盖外外推 |
| 完整轨迹标签 | 同一范围内的完整性能指标 | 声源/目标身份正确性，除非另有身份真值且由其他模块评价 |
| 同源 baseline | 指标差值与结构差异 | 无真值时自动判定哪个算法更准确 |
| 验收阈值 | 对被请求且有证据的指标判定 pass/fail | 自动生成综合分数或替用户选择阈值 |

空真值文件可能表示未标注，也可能表示确认无轨迹，必须由 `label_scope` 和 `negative_labels_complete` 明确，不能根据空表猜测。

## 2. 无真值描述指标

执行器固定计算：

- `association_completeness`：候选—轨迹映射数 / 上游候选数；这是结构完整性。
- `track_count`、`confirmed_track_count`、`tentative_track_count` 和 `confirmed_track_fraction`。
- `singleton_track_count/fraction`。
- `short_track_count/rate`：短轨上限由请求的 `short_track_max_detections` 定义。
- 轨迹点数、持续时间、行跨度占用率的 min/mean/median/p90/max。
- `gap_termination_count/fraction`、`end_of_input_termination_count`、`tracks_with_gap_count/fraction`。
- 相邻真实观测间绝对频率步进的 min/mean/median/p90/max。
- 最大活动轨迹数、发生终止的行数和终止事件数。

行跨度占用率：

```text
detection_count / eligible rows from start_row through end_row
```

`continuity_basis=all_rows` 时全部账本行进入分母；`tested_rows` 时跳过行不进入分母。它不等于真实目标持续时间覆盖率。

短轨、单点轨和 `gap_exceeded` 数量是结构现象。没有真值时不得将它们重命名为 false track、fragmentation 或 miss。

## 3. 真值指标

匹配只在真值声明的覆盖区域内进行，逐行一对一，先最大化匹配点数，再最小化总绝对频率误差。匹配规则由请求明确。

- `point_recall = matched_truth_points / eligible_truth_points`。
- `point_precision = matched_estimated_points / eligible_estimated_points`，仅完整负类覆盖可算。
- `frequency_bias_hz`、`frequency_mae_hz`、`frequency_rmse_hz`、`frequency_max_abs_error_hz` 只使用匹配点。
- `truth_track_recall`：至少有一条估计轨迹同时满足最少匹配点数与最少真值点召回比例的 truth track 数 / 可评价 truth track 数。
- `estimated_track_precision`：至少与一条 truth track 同时满足上述两个条件的估计轨迹数 / 覆盖内估计轨迹数，仅完整负类覆盖可算。
- `fragmentation_count`：每条 truth track 匹配到的不同估计 `track_id` 数减 1 后求和。
- `identity_switch_count`：同一估计轨迹按时间排序的匹配 truth track ID 发生变化的次数。

身份交换只针对“轨迹标签保持”，不表示现实目标身份错误。局部真值中的 precision、false-track 和完整 fragmentation 保持 null，并说明证据不足。

## 4. 定义域与空值

- 分母为零的指标为 null，不填 0。
- 没有匹配点时频率误差为 null。
- 没有相邻轨迹点时频率步进统计为 null。
- 部分标签导致不可算的 precision/false-track 和完整 fragmentation/identity-switch 指标为 null；另保留带 `observed_labeled_` 前缀的已标注现象计数。
- 输入不完整、哈希变化、候选重复映射或轨迹点不一致时阻断，不输出伪指标。

所有比例均为 `[0,1]`，误差使用 Hz，持续时间使用秒。报告必须同时给出相关计数和分母。
