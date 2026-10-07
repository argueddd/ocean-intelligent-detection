# 结果输出与展示：按需产物 / 子集补图 v0.4.2

修改输出策略或执行补图时完整阅读本页。物理/阵列计算仍遵守 data-contract.md 与 numerical-execution.md；本页覆盖旧文档中“保存全部计算方向时域”的要求。

## 1. 两套方向列表

- 计算方向：指定列表或经确认的固定网格，决定波束计算、每束 PSD/时频矩阵、频率—角度和时间—角度覆盖。
- 时域保留方向：由用户指定或按下游任务与资源预算自主选择的计算方向子集。先把角度与完整方向定义准确匹配到扫描索引并记录映射；不以未声明规则取最近角度，也不把峰值自动解释成真实目标。
- 没有说明要保留哪些方向，必须询问；不能默认全存、默认不存或存最强方向。
- 当前任务只需空间/谱评价且没有下游时域需求时允许空列表；后续线谱检测仍以实际保留的时域数据为主要接口，只有谱时不能说时域交接就绪。
- 只在内存中产生所有方向的合成波形用于统一输出谱定义，不将未选方向时域波形写盘，亦不作为临时磁盘文件保留。
- 旧运行已存在的全方向时域文件不自动删除或覆盖。新的“不保存”策略不是历史数据删除授权。

## 2. 新执行配置

execute.py 只接受 execution_version=0.4，plan.schema_version=0.4。旧 0.3 执行配置会阻断，要求先确认保留方向；不能为兼容悄悄运行原先的全存策略。preflight.py 仍可只读检查历史 0.2 plan，但它不是执行入口。

plan.output 保留 directory、format=npy、weights=save_all、max_waveform_bytes 与 auxiliary_products，新增/变更：

- beam_selection="explicit_indices"。
- time_domain_beam_indices：显式的零基扫描索引列表；保持用户指定顺序，拒绝重复、越界、布尔索引；缺失/null 阻断并询问。
- save_time_domain：必须与 bool(time_domain_beam_indices) 一致。
- [] 配合 false 是明确不保存，不是未知；也不能以此绕过真实用户确认。
- auxiliary_products 为显式唯一列表，可从 psd、time_frequency、spatial_spectrum、frequency_angle、btr 中单选或组合，不再强制完整五项包。缺失/null 仍阻断，不能推断为全选或不选；[] 仅用于已明确的纯时域任务。
- 时域净字节预算只计算所选波束；谱产物磁盘预算按所选矩阵、共享坐标和图片数量估算。内部仍会构造逐帧 PSD 立方体供归约，内存预算保留全量暂态空间；本次不是流式改造，少存产物不等于消除计算内存。

执行包装必填 analysis：请求任意谱产物时为下节完整对象；纯时域时显式 null。它被 execution approval 的范围摘要覆盖；更改任何值或输出选择必须重新核对并确认。未选时域且未选任何谱产物视为没有信号交付，阻断。

### 按需输出的选择方式

| 配置标识 | 交付内容 |
|---|---|
| psd | 每束平均功率谱数值与曲线 |
| time_frequency | 每束合成时域信号的时频 PSD 数值与图 |
| frequency_angle | 平均 PSD 的频率—角度矩阵与图 |
| btr | 频带积分功率的时间—角度矩阵与图 |
| spatial_spectrum | 保留旧配置名；实际为扫描输出功率（scan_power），不是 Capon 理论谱 |

选择时域与选择谱产物互相独立。例如：
- 仅时域：auxiliary_products=[]、analysis=null，同时明确保留方向。
- 时域 + PSD + 时频图：auxiliary_products=["psd","time_frequency"]，同时明确保留方向。
- 仅时频图：auxiliary_products=["time_frequency"]、time_domain_beam_indices=[]、save_time_domain=false。
- 仅角度图和 BTR：auxiliary_products=["frequency_angle","btr"]，时域是否保留仍按明确请求填写。

这些只是主执行器输出字段的示意，不是完整可执行配置，也不提供角度、声速、窗长等实测默认值。不能把这些示例作为用户确认。主计算每项谱仍覆盖全部已确认计算方向；已有结果可用下节0.4.2补图入口选择保存子集，但同一补图任务内各产物仍共用一份选择列表。单方向也可请求角度图，但必须说明只有一个方向，不表示扫描或自动定位。

## 3. 谱与图的计算定义

analysis 各项没有实测默认数值。完整字段：

| 字段 | 当前支持的值 |
|---|---|
| profile | reconstructed_waveform_psd_v1 |
| window / window_periodic | hann、hamming、boxcar；显式布尔 |
| window_samples / hop_samples / nfft | 已确认正整数，hop <= window <= nfft |
| band_hz | 已确认闭区间；必须位于原波束处理频带中 |
| detrend | none；不对输出帧额外去均值/趋势，原处理历史保留 |
| frame_origin | output_sample_zero |
| validity | complete_frames_all_samples_valid |
| scaling | onesided_density |
| time_average | arithmetic_mean_linear |
| frequency_integration | bin_sum_df |
| display.scale | shared_peak_db_per_quantity |
| display.limits | shared_finite_range |
| display.zero_power | mask |

先对最终合成时域信号 y 重新分帧分析，不能把处理内部的自适应加权 STFT 直接冒称 y 的 STFT。周期性窗的定义由 window_periodic 明确给出。

候选帧从输出样本 0 开始，每 H 点一帧；只保留完整落在片段内且帧内所有样本 valid=true 的帧。不填充、不跨缺口、不拼接或压缩时间，不把实际无效边界当正常数据。若没有有效完整帧则停止，不自动缩窗。

对窗 w、频点 k：

`P[t,k,b] = factor[k] * |rFFT(w*y)|² / (fs*sum(w²))`

DC 与偶数 nfft 的 Nyquist 的 factor=1，其余正频率=2；奇数 nfft 的最后一个频点也乘 2。只保留中心位于 band_hz 闭区间的频点，不插值带边。该定义与显式 window、detrend=False、density 的单边 periodogram 一致。

- 每波束 PSD：P 沿有效帧作线性算术平均，[frequency,scan_beam]。
- 每波束时频图：P 的对应方向切片；总矩阵 [frame,frequency,scan_beam]。
- 频率—角度图：同一个时间平均 PSD 矩阵的另一种展示；同时选 PSD 时共用文件，只选频率—角度时独立命名，不另造估计器。
- BTR：每帧在所选频带内 sum(P)*df，df=fs/nfft，[frame,scan_beam]。
- 角度扫描功率：BTR 沿时间作线性平均，[scan_beam]。
- 时间坐标：first_sample_offset + (frame_start + (L-1)/2)/fs，保留真实帧起点和时间间隔。
- 这是实际输出信号的功率，**不是** 1/(aᴴR⁻¹a) Capon 扫描谱，也不是加载目标函数；不按理论名称混标。
- PSD 数值单位是输入单位²/Hz，积分功率是输入单位²。输入 unknown 时保持未知绝对单位，不标 Pa、声压级、SNR/SINR 或定位精度。

计算依据：[SciPy periodogram](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.periodogram.html)、
[SciPy Welch](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html)。
参考文档不是采用其默认参数的许可。

## 4. 显示与保存

结果保存在全新目录，数值为 float64 NPY；PNG 及本地 index.html 为查看入口。保留坐标、方向定义、算法、计算方法、线性单位、显示规则和内容摘要。

- {algorithm}_psd.npy：仅选择 psd 时保存；若同时选择 frequency_angle，则后者在清单中 alias_of=psd，不重复保存。
- {algorithm}_frequency_angle.npy：仅在选择 frequency_angle 而未选 psd 时保存；不生成逐束 PSD 图，也不列出不存在的 psd 别名。
- {algorithm}_time_frequency_psd.npy：仅选择 time_frequency 时保存，覆盖全部计算方向。
- {algorithm}_btr_power.npy：仅选择 btr 时保存。
- {algorithm}_scan_power.npy：仅选择 spatial_spectrum 时保存；内部计算频带积分不意味着额外保存 BTR。
- analysis_frequency_hz.npy、analysis_frame_start_sample.npy、analysis_time_seconds.npy。
- directions_deg.npy 保留所有计算方向；scan_beams 记录全部扫描列。
- {algorithm}_time.npy **仅当明确选了保留方向才存在**。beams 仅记录已保存的时域列，并逐列写出 scan_column；shape_per_algorithm 对无时域保存为 null。
- valid_sample_mask.npy、确认配置、result.json；新数值运行仍保存实际权重与诊断。
- figures/beam_XXXXXX.png：选 PSD 或时频图才生成。单选时只画所选内容；同时选中才上下组合。未选择二者时无逐束图链接。
- figures/{algorithm}_frequency_angle.png、{algorithm}_btr.png、scan_power.png：分别只随对应选择生成。
- index.html：离线图集只链接实际生成的图，始终保留方向表和选择说明；不访问外网、不自动抽取目标。
- result.json 的 spectral_products.requested_products/delivered_products 记录所选项；per_algorithm 只列实际交付，spatial_spectrum 沿用 scan_power 结果键。基础坐标、有效帧与来源信息属于必要元数据，不因未选时频图而省略。

PSD/频率—角度共享一个参考；时频 PSD 共享一个参考；BTR 与扫描功率各自共享相应参考。同一类量在所有请求算法、方向、时间/频率范围内取共同最大正值，仅用于 10log10(P/reference) 的显示。色标覆盖共同有限 dB 范围，不逐图峰值归一化，不改变线性矩阵。全零数据用灰色掩码并说明 dB 未定义；恒定显示量的 1dB 最小轴宽只为排版，不代表不确定度。全有限范围可能导致弱线条显示对比度不足；若需缩小色标范围，先明确显示规则再另作显示，不能剪裁原数值。

单个单调变化角度可用真实角度坐标；双角度网格或非单调指定列表暂以扫描索引展示，附完整角度表，绝不把二维网格展平后伪称单一地理方位轴。谱数值仍保留每个方向，当前未做二维方位/俯仰切片可视化。

对比图不自动找峰、筛选“最佳算法”、改指向或追踪。颜色强弱不能单独证明目标增强；不计算缺少真值/标签的准确率、SNR/SINR。

## 5. 已有结果补图入口

```bash
python3 <skill-dir>/scripts/analyze_results.py check <product-config.json>
python3 <skill-dir>/scripts/analyze_results.py digest <product-config.json>
python3 <skill-dir>/scripts/analyze_results.py run <product-config.json>
```

旧 product-config 使用 product_version="0.4.1"，必填显式、非空且无重复的 auxiliary_products；其余字段为 source_result={path,sha256}、output_directory、time_domain_beam_indices、analysis、max_working_bytes、max_artifact_bytes、title 和独立 approval（与 execute.py 同样的 status/scope_sha256/evidence/confirmation 结构）。可参考 [待确认补图模板](../assets/product-request.json)。补图入口仅处理请求了谱的任务；纯时域任务仍走原执行入口。

历史 product_version="0.4" 严格保留原先完整五项包的语义，不能新增 auxiliary_products，也不能通过旧版本规避新请求的选择确认。新任务使用下述0.4.2并明确算法、波束及所需项；更改旧任务选择时，显式升级版本并重新确认摘要，不能静默迁移。主执行器的 execution_version/plan.schema_version 仍为0.4，不需要改变其结构或已有整套输出语义。

check 读取完成清单及其 SHA256，不读时域数组、不执行 FFT。run 再验证全部源产物摘要、波形形状/类型、方向列序及有效掩码；源被修改则停止。范围确认必须来自真实用户，不复制测试中的 MOCK。

历史补图配置0.4/0.4.1仍要求源包保存所有计算方向时域且列序一致。新0.4.2可以只消费已保存子集，见下节。所有版本都不能从功率反推未保存方向的波形；如果确需该方向，须另行确认原始输入的波束计算，不绕过门禁。

没有目标自动选择、重新波束计算或旧文件删除。成功清单最后发布；绘图/写盘失败会留 failure.json，但没有 completed 清单，不能交付为完成结果。PNG 渲染需 Matplotlib；缺依赖报告，不自动安装或升级。输出预算包含矩阵与保守的图片估算，但不是操作系统硬资源配额。

### 仅对已保存波束补图：product_version=0.4.2

使用 [子集补图模板](../assets/subset-product-request.json)，命令不变。已通过 v0.4.3 合成与 VLA 子集补图回归；主 execute.py 的配置版本不变。

相较0.4.1，去掉 time_domain_beam_indices，增加三项显式列表：

- algorithms：cbf、mvdr 的非空唯一子集，必须确实存在于源包。
- analysis_beam_ids：非空唯一的稳定 beam_id 列表，每条必须有已保存时域；保持用户指定顺序，不自动选峰或按角度找最近项。
- time_domain_beam_ids：另存到新补图目录的时域子集，必须包含于 analysis_beam_ids。无下游时域需求时自主填写 []；null/缺失按任务目标解析，不作为单独提问。不会修改源包时域。

其余字段仍为 source_result={path,sha256}、output_directory、auxiliary_products（非空）、analysis、max_working_bytes、max_artifact_bytes、title 和独立 approval。可只选 CBF 和一个已保存 beam_id，auxiliary_products=["time_frequency"]；具体 ID、分析窗/步长/频带等仍需来自来源或真实确认，不能用示意当默认值。这是重新分析已合成时域，不重新波束形成。

源可为具有有效列映射的0.4主结果/补图结果，或0.3全方向同序旧结果；纯谱包、未保存请求束或列映射冲突阻断。对于每个 beam_id：

1. scan_column：原始完整计算方向编号。
2. source_column：来源时域文件中实际保存列。
3. spectral_column：此次选择后的谱矩阵列。
4. beams.column：如果另存时域，新文件中的保存列。

四者不能混用。result.json 保留原始 scan_beams / directions_deg，新增 spectral_beams 和 analysis_directions_deg.npy。谱轴标为 spectral_beam，spectral_products.directions_file 指向选择后的角度文件；coverage 记录本次选择与源覆盖。beams 仍只列此次明确另存时域，不表示全部分析方向都有新时域文件。

PNG文件 beam_XXXXXX.png 的编号是此次产物列，不是原扫描编号；标题/图集显示稳定 beam_id 和真实角度。子集角度图/BTR 使用离散产物列并附方向表，不把未选角度间隔涂成已有扫描覆盖；扫描功率只画所选点、不连成密集角度扫描。每种量在本次所选算法/波束中共用显示参考；不同补图任务的相对dB参考可能不同，跨包不能直接比较颜色。

保存完整样本轴、原始时间偏移和有效掩码，仍只使用完整有效帧；不拼接缺口。没有完整有效帧就停止，不自动缩窗、补零或改变预算。只选一束也保持二维时域/独立谱列。

此补图包仍不是当前主结果时域交接器的输入；交接可从原始主结果中选取对应已保存束。不要为了“接收成功”伪造主结果格式或静默追链。

## 6. 验证范围

2026-10-04 已实际运行 v0.4.3 回归：31种非空谱产物组合逐项核对、五类产物单独渲染、部分保存列/重排序/重复补图、缺失选择与来源变化阻断等。S59 VLA 重新执行37方向计算、仅保存0°，并从该波形补算五类谱；详情见 [本版证据](acceptance-v043.md)。

原 v0.4 测试本轮重新通过，不以旧计数代替新版验证。测试核对 SciPy periodogram/Welch、Parseval 能量、DC/Nyquist/奇数 FFT、有效区间和缺口、线性归约、共同 dB 参考、零值、缺参数阻断、显式保留顺序、仅保留单束仍二维、不保存时域、源摘要保护以及绘图失败不发布完成结果。

实测验证应另记输入、范围和结果清单，不以合成测试替代。水平阵列序问题仍单独阻断水平阵计算，不影响已有 VLA 结果的谱分析。本次已检查48张PNG解码、图库文件链接、6张代表图视觉显示、数值文件对应和产物摘要；浏览器交互未验证。
