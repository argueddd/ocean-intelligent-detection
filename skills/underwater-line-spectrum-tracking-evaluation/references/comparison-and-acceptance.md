# 比较与验收

## 可比性门禁

primary 与 baseline 必须具有完全相同的：

- detection run/task；
- candidate table SHA-256 和 ledger SHA-256；
- time reference、analysis grid 和评价覆盖；
- 候选总数及行账本来源。

不满足时 V1 阻断 comparison，不用归一化或公共子集偷偷制造可比性。算法参数可以不同，正是比较对象的一部分。

comparison 输出 primary、baseline 指标和 `primary - baseline` 原始差值。没有真值时不根据轨迹更少、confirmed 更多或曲线更平滑自动宣布更优。

## 验收检查

每项检查包含：

```text
metric + operator + threshold
```

支持 `<=`、`<`、`>=`、`>` 和 `==`。只允许执行器登记的标量指标，不接受任意表达式或加权总分。

- 指标存在且有限：按运算符判断 pass/fail。
- 指标因证据不足或分母为零而为 null：`insufficient_evidence`。
- 没有检查：整体 `not_requested`。
- 任一 fail：整体 `failed`。
- 无 fail 但存在 insufficient：整体 `insufficient_evidence`。
- 全部 pass：整体 `passed`。

阈值来源由请求中的 `source` 记录。评价执行器不认证该标准是否合理，也不在运行中改阈值以获得通过。

## 可验收指标

描述指标包括：`association_completeness`、`confirmed_track_rate`、`singleton_track_rate`、`short_track_rate`、`gap_exceeded_rate`、`mean_row_span_occupancy`。

真值指标包括：`point_recall`、`point_precision`、`frequency_mae_hz`、`frequency_rmse_hz`、`track_recall`、`track_precision`、`fragmentation_count`、`identity_switch_count`。

comparison 的差值仅报告，不直接作为验收指标；若需要差值阈值，应在未来版本显式定义方向和证据规则。
