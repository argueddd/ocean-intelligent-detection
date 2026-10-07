# 检测结果向频率轨迹模块交接

状态：生产端交接实现 1.0.0。它只核验并引用一个已完成逐窗检测任务的完整候选表和账本，不执行跨帧关联、轨迹生成、谐波归并、声源关联、目标识别或评价。

## 职责边界

检测端负责提供不可歧义的测量输入；未来跟踪模块负责建立新的 `track_id` 并引用原 `run_id + task_id + candidate_id`。两端不得把下列三种关系混为一谈：

- `AssociationRecord`：数据、波束、任务、候选和产物之间的来源追溯；不是物理同源关系。
- 候选—轨迹关联：不同时间窗的候选是否属于同一条频率轨迹；由跟踪模块产生。
- 轨迹—目标归属：轨迹/特征属于哪个声源或现实目标；由后续关联/识别模块产生。

交接文档明确声明 `tracking_performed=false`、`target_identification_performed=false`，并禁止出现 `track_id`、`source_id`、`target_id`、`harmonic_family_id`、`same_target` 等语义键。频率接近、同一波束或多算法共同检出都不能改变这一边界。

## 生产条件

只接受一个明确 `task_id`，并且同时满足：

- 来源为带最终 `package-manifest.json` 的 completed/partial 检测包；所选 task 自身必须 completed。
- `task_kind=framewise`；平均谱只有一张段级结果，不冒充时间轨迹输入。
- candidates 和 ledger 已明确计算并持久保存；临时、未保留或仅有图像的结果不能交接。
- 保存的候选表与 DetectionResult 中完整候选逐项一致，没有截断。
- 保存账本、resolved configuration 的最小账本和候选行号一致；零候选检测行、无效/跳过完整帧仍保留。
- 候选的分析支持与原检测行严格对应；不从时间窗推断事件持续时间。

交接保留信号、波束、时间参考、原始半开样本区间、采样率、窗长、步长、NFFT、频率网格、单位/有效性状态和全部来源哈希。未知仍是未知，不为了跟踪补成全有效、校准量或真实方位。

## 命令

先从用户明确指定的现有结果包和 task 创建一个包外新文件；不得写回或修改检测包：

```text
python3 scripts/tracking_handoff.py build /absolute/detection-package exact_task_id \
  --manifest-sha256 <64位摘要> --max-read-bytes <正整数> \
  --output /absolute/new-tracking-handoff.json
```

以后使用前重新读取全部绑定证据并核验：

```text
python3 scripts/tracking_handoff.py check /absolute/new-tracking-handoff.json \
  --max-read-bytes <正整数>
```

build/check 都不运行检测或跟踪。输出已存在、来源变更、候选/账本未保存、任务不是逐窗、哈希或计数不一致时阻断；不自动补算、覆盖、寻找其他同名包或选择另一个 task。

## 交付语义

`DetectionTrackingHandoff` 是派生证据清单，不增加或修改五类公共检测契约。它引用原检测包内的 DetectionResult、resolved configuration、完整候选表和完整账本，并记录：

- 候选表/帧账本是否完整及数量；
- 零候选行和无效/跳过帧是否纳入；
- 候选输出未截断；
- 原生时间/频率网格；
- 来源波束身份或不适用状态；
- 未执行跟踪、谐波、声源归属、目标识别和评价。

若未来跟踪算法需要检测端当前未保存的测量量，应提出新的检测产物请求并生成新检测结果；不得回填旧包或从图片恢复精确数值。
