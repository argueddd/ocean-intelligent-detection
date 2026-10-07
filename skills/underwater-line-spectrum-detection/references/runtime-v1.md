# 检测执行与交付 v1.0.0

2026-10-05。本页是新框架执行入口，不是旧 `line_spectrum_methods.py` 的包装。公共五类契约仍为 0.1.0；底层只读预检与旧确认的权限不变。

## 调用前必须明确

先读 [方法规则](cfar-design.md) 与 [门限依据](cfar-threshold-design.md)。真实任务必须有明确的信号/区间/频带、方法、任务类型、参数来源、未知项处理、计算/查看/保存清单与预算。支持某项能力、通过结构检查、交接成功本身均不授权检测；用户在当前会话中明确要求对指定数据执行检测时，该真实请求可作为本次执行授权，参数细节按主 Skill 的 Harness 执行策略解析。

输入仅接收经 `input_adapter.py` 核验的完整主波束/旁路交接包对应的 SignalInput。单通道来源可以是单水听器或已波束形成信号；原始多通道阵列不得绕过波束模块。采样率/单位/方向/时间等事实从核验后的上游继承，不重复猜填。输入交接命令见 [输入适配](input-adapter.md)。

## 文件和调用

| 入口 | 作用 |
|---|---|
| `cfar_registry.py` | 显式导出 `ca_cfar` 或 `os_cfar` 的真实 AlgorithmDescriptor |
| `detection_runtime.py review` | 基础预检 + 必需的完整上游适配 + 科学参数/有效帧/资源/产物/标定匹配核对；不算 PSD |
| `detection_runtime.py confirm` | 将真实用户执行表述绑定到当前完整方案，另建 receipt |
| `detection_runtime.py run` | 重新核对、验证当前 execution receipt、执行、结构检查、独占另存 |
| `cfar_calibration.py` | 独立的 H0 试验标定和验证任务，见 [标定入口](calibration-v1.md) |
| `detection_associations.py` | 双向查询、已有证据联合查看、确认后一次性补算，见 [协作入口](association-runtime-v1.md) |
| `tracking_handoff.py` | 从一个明确的已完成逐窗任务生成/复核只读跟踪输入清单，见 [跟踪交接](tracking-handoff.md)；不运行跟踪或目标判断 |

命令中的路径必须替换为本次明确的绝对位置，不能从示例推断数据或参数：

```text
python3 scripts/cfar_registry.py ca_cfar --out /absolute/metadata/CA.json
python3 scripts/cfar_registry.py os_cfar --out /absolute/metadata/OS.json
python3 scripts/detection_runtime.py review /absolute/request.json /absolute/context.json --source-root /absolute/readonly-inputs
python3 scripts/detection_runtime.py confirm /absolute/request.json /absolute/context.json --source-root /absolute/readonly-inputs --evidence /absolute/user-execution-evidence.json --receipt-output /absolute/new-receipt.json
python3 scripts/detection_runtime.py run /absolute/request.json /absolute/context.json --source-root /absolute/readonly-inputs --receipt /absolute/new-receipt.json
```

只导出本次选中的算法，不自动两种全建任务。登记摘要绑定本 Skill 的执行代码/Schema、已有同级输入依赖脚本及 Python/NumPy/SciPy/jsonschema/referencing 版本。升级后重新导出说明、核对请求并重新确认；标定身份也需重核，不手改摘要绕过。

DetectionRequest 与 PreflightContext 沿用 [已有契约](schema-validation.md)。context 必须包含显式 `handoff_validation.max_package_bytes/max_block_samples`，而非可选地跳过来源复核。文件映射只在指定 source-root 中解析，不搜全盘、不追链接补文件。

## 本版任务和全部参数

`detector` 必须等于所选说明的 detector_id、detector_version、真实 implementation_sha256。`task_kind` 显式为 `framewise` 或 `average_spectrum`。`scope` 仍含原始输出索引的半开 sample_intervals、search_band_hz、原 time_reference。

`resolved_parameters` 无科学数值默认值，其闭合 Schema 由登记器导出：

| 参数组 | 必填内容与含义 |
|---|---|
| spectrum | window_length、hop_length、nfft；window=`rectangular` 或 `periodic_hann`；demean 布尔；frame_origin=`each_interval_start` 或 `signal_sample_zero`；invalid_frame=`skip_and_report` 或 `stop`；unknown_validity=`reject` 或 `analyze_unverified` |
| cfar | reference_per_side=R、guard_per_side=G；rank 为 CA 的 null 或 OS 的 1 起始整数 k；reference_band_hz；insufficient_reference、zero_background 都明确为 skip_and_report/stop |
| threshold | route=theory/calibration；event_scope=frame/segment；event_probability=q；family=`this_task_signal_detector_only_no_joint_guarantee`；theory_assumption 与 calibration_ref 按路线二选一，另一项必须 null |
| candidates | group_width_hz=null（明确不启用）或 [最小,最大]；minimum_peak_distance_hz=null 或正数。组宽不是物理线宽 |
| display | 无绘图时 null；绘图时明确 db_reference_psd、递增的 db_limits、spectrum_rows（精确行索引）、title。时频图只支持 framewise，不顺便计算平均谱 |

窗长至少 2，nfft 不小于窗长，hop 正整数；步长可大于窗长，遗漏样本会进入排除覆盖，不自动补帧。样本分段逐段分帧，不把间隙拼在一起。`signal_sample_zero` 表示起点在信号输出索引零的 hop 整数网格上；另一选项以每个明确区间起点为网格起点。

逐帧去均值发生在加窗前。周期 Hann 为 `0.5-0.5*cos(2*pi*n/L)`。单边密度为 `|rFFT(w*x)|² / (fs*sum(w²))`，仅正频内部单元加倍；偶数 nfft 的 Nyquist、DC 不加倍。平均谱为全部有效完整帧 PSD 的算术平均，不把重叠帧当独立样本。与 [SciPy periodogram](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.periodogram.html) 的 density 定义对照测试。

`processing_steps` 必须依次为 spectrum、cfar、threshold、candidates、display，各 parameters 为 `{ "/组名": 对应 resolved_parameters 的整个组 }`。可使用 `cfar_registry.processing_steps(parameters)` 明确生成引用，不另造默认值。parameter_evidence 必须覆盖参数，记录真实选择/假设/来源；示例和合成测试的 MOCK 不是用户证据。

元数据 unknown 的允许处理还需请求中的、准确覆盖任务及 detection 动作的 unknown_decisions。`analyze_unverified` 不会把原掩码改成全有效；输出保留 unknown。上游交接包自身不满足有限值等接收契约时先受阻；不能用下游 skip 规则掩盖坏的输入包。

同时选逐窗和平均谱时，先说明本版只实现每项 task 的独立范围，分别确认 family/q，不承诺同信号两任务合并后的 q。需要联合预算则阻断并报告本版不支持。

## 理论/标定门禁

理论需要：`theory_assumption={model: iid_exponential_cells, applicability: model_asserted 或 nominal_approximation, rationale: 真实依据}`。Hann、零填充及波束来源必须显式选择 nominal_approximation；矩形窗不自动证明模型成立。平均谱不允许套单指数理论，只接匹配的离线标定。q/M、统计假设和残差见门限参考。

标定需要显式 file_ref、context.source_files 绑定、匹配的配置/模型证据及独立验证通过记录。不匹配就询问处理，不自动重标定或换理论路线。

## 真正的执行确认

review 返回 `ready_pending_execution_confirmation` 或 blocked，`can_execute=false`。前者只是就绪，不是已执行。

用户明确要求执行后才能生成 evidence。若该要求已经出现在当前会话中，review 通过后直接绑定该真实表述，不再要求用户重复确认。键严格为：

```text
actor: user
decision: authorize_execution
plan_sha256: 本次 runtime review 的摘要
statement: 用户真实执行表述
reference: 对应真实消息/确认出处
```

confirm 写新的 receipt_version=1.0.0、scope=detection 记录。旧 `preflight_plan_only_not_execution` 记录不能替代它。请求、来源、上下文、实现、科学参数、产物或输出位置变化均需重新 review；变化超出用户原请求授权时才重新询问。本地文件不认证用户身份，authority_verified 始终 false；调用方必须对照真实对话。

## 按需产物和保存

每项 task 分别列出 products.compute/view/save。view/save 必须包含在 compute 中；spectrum_plot、time_frequency_plot 另要求明确的 spectra 依赖。

| product_id | 内容 |
|---|---|
| candidates | 带判据/支持/来源的 JSON 候选表 |
| ledger | 完整逐行检验/排除频点、零候选行、剔除的超门限组等审计记录 |
| spectra | 线性 PSD、背景、门限、cell_valid、频率及原样本行坐标；NPZ 不使用 pickle |
| spectrum_plot | 仅指定 spectrum_rows 的谱、背景、门限和候选 PNG |
| time_frequency_plot | 逐窗 PSD 和候选 PNG；保留时间缺口，不做跟踪 |
| report | 来源、候选、覆盖、限制的 HTML 摘要，不计算评价指标 |

展示 dB 参考和色标显式确定，裁到显示范围不改线性数据。单位未知不标声压级。每个频率位置是原 FFT 中心；显示帧中心为 `sample_zero_offset_seconds+(start+stop-1)/(2fs)`。图中色块宽度用于展示、不是事件持续时间。

持久化时最小包总含 request.json、resolved-configuration.json、detection-result.json、association.json、最后发布的 package-manifest.json。配置附最小逐帧覆盖账本、零候选行计数、几何频点集/异常排除、M、p、alpha/系数残差等；不默认保存完整谱矩阵或图集。额外产品仅 save 选中者写盘。无候选而存在合格检验是 completed；无有效帧/无可检验单元不是成功零候选。

资源字段全部必填：

- saved：明确新 output_directory，temporary_storage_policy=`memory_only_until_publish`。父目录已存在且无符号链接，输出位于只读 source-root 外，绝不覆盖旧目录。
- session：output_directory=null，temporary_storage_policy=`memory_only`。Python API 返回 files/views 字节对象；CLI 结束后临时产物不保留，不虚构可打开的持久路径。
- max_working_bytes 是保守分配准入，不是 OS 强制 RSS 限制；整段内存处理，不支持流式/自动分块降级。max_artifact_bytes 在发布前按实际生成字节复核；库字体缓存不属于信号临时文件。

保存包含外部上游引用和明确 source_bindings，不自动复制原录音/波束数据；分享结果时先确认是否连同来源打包。不能把“有引用”说成“上游文件随包”。

CLI 在阻断、部分完成、标定未达所选验证规则或补算失败时返回非零退出码，并保留结构化状态；不能只凭生成了 JSON 就认为成功。

stop_batch 遇运行故障停止且不发布完成包；continue_independent 保留单项失败，包状态 partial，失败候选为 null。写盘中断或源变化可能留下无完成清单的目录，不能使用或自动清理/覆盖。运行前、发布前及清单写入前检查来源；这不是文件系统锁或物理连续性证明。

## 验证范围

运行 `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -v`。`test_detection_runtime.py` 使用合成数据和明确的测试伪确认，覆盖数值对照、两种检测、两种谱任务、标定/消费、来源/权限/预算、按需绘图、索引、旧证据查看与补算；`test_tracking_handoff.py` 覆盖完整候选/账本交接、来源复核、边界语义和缺失产物阻断。旧契约/适配/预检/理论测试保持独立。

通过代码回归不代表 S59 实测效果、真实 Pfa/Pd、物理阵列正确或工程验收；这些需要另外确认实测方案及独立评价证据。
