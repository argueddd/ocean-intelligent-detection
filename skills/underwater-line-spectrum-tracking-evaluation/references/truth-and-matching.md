# 轨迹真值与匹配

## TrackingTruthLabels 1.0.0

真值文件必须绑定同一检测来源：`detection_run_id`、`detection_task_id`、候选表摘要、账本摘要和时间参考。标签点使用检测行 `row`、同一时间参考下的 `time_seconds` 和 `frequency_hz`。

`label_scope` 明确：

- 一个或多个半开 `row_ranges`；
- 闭合 `frequency_range_hz`；
- `truth_tracks_complete`：是否包含覆盖范围内全部真实轨迹；
- `negative_labels_complete`：未标注位置是否可以解释为负类。

`label_status=partial_positive` 时两个 complete 标记必须为 false。`complete` 可以支持负类指标，但真实性仍来自标签提供者，不由结构校验认证。

每条 `truth_track_id` 在同一 row 只能有一个点，点按 row 严格递增。真值轨迹只是评价标签，不得附加或推断 `source_id`、`target_id`、目标类别或身份。

## 匹配规则

请求必须明确：

- `frequency_tolerance_hz > 0`；
- `minimum_matched_points >= 1`；
- `minimum_truth_track_recall` 在 `[0,1]`；
- 固定 `assignment_method=per_row_maximum_cardinality_minimum_frequency_error`；
- 固定稳定平局顺序 `estimated_track_id_then_truth_track_id`。

同一 row 内只匹配频差不超过门宽的点。每个估计点和真值点最多使用一次。算法不进行时间插值、不补缺失真值点、不移动频率、不用未来目标身份消除歧义。

## 覆盖

真值点必须落入声明 row/frequency 覆盖并与上游 row 时间一致；超出范围或时间不一致会阻断。估计点只有位于同一覆盖区域时才进入 truth 指标。

partial positive 标签中，未匹配估计点保持“未知”，不是 false positive。完整标签中才可以计未匹配估计点、未匹配轨迹和 precision。
