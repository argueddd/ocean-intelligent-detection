# 双向索引、联合查看与一次性补算 v1

先读 [关联语义](framework-association.md)。本页的 `detection_associations.py` 实现三层协作；不进行效果评价、目标归并、自动选束、自动调参或后台循环。

## 双向索引

每次检测生成合法 AssociationRecord：run→task→signal→beam→source_result，candidate/artifact 归属对应 task。实际边方向以 sourced_from/derived_from 表示派生对象指向来源。只有来源中确实存在的波束身份才建 beam 节点；单阵元和未知波束 ID 不伪造节点。

query 只读取配置明确提供的 AssociationRecord，不自动建立全盘索引。配置含 associations=[{path,sha256}]、kind、完整 identity、direction=ancestors/descendants。

```text
python3 scripts/detection_associations.py query /absolute/query.json
```

身份包括包/运行摘要，不把相同名字或角度看成同一个对象。查询返回精确匹配根、沿来源关系可达节点和关系；无匹配就明确空结果，不替代来源。

## 已有证据联合查看

```text
python3 scripts/detection_associations.py joint-view /absolute/view.json
```

view 配置所有字段均明确：

- view_version=`1.0.0`。
- detections：[{directory,manifest_sha256,task_ids,product_ids}]，明确选择已保存完成任务及已保存产物；product_ids=[] 可只看来源/候选/覆盖。未保存图/谱则报告缺失，不偷偷重算。
- beams：显式列表，[] 表示这次不读波束谱。每项含 result_path、result_sha256、algorithm、beam_ids、products、plot_products、frequency_range_hz、time_range_seconds、display。
- beam products 支持已有 psd、time_frequency、frequency_angle、btr、scan_power；plot_products 是其中明确要画的子集。两者 [] 不代表自动全选；至少选择一个现有产品。
- 频率/时间范围 null 表示明确查看所选产品的全部原生覆盖；或给递增范围，只选择原坐标，不插值、不取最近点。时间是来源相对的帧中心。已平均的 PSD/频率—角度/扫描功率不能通过“显示范围”冒充新时间平均；已频带积分的 BTR/扫描功率也不能冒充新窄频带结果。
- 有 beam plot 时 display 显式给 reference_psd、reference_power、db_limits、title；无 plot 时必须 null。dB 图不标声压级。方向以明确 beam_id/原方向标签展示，不插值为连续方位估计。
- alignment_rule=`native_coordinates_exact_bin_lookup_no_interpolation`。
- max_read_bytes、max_artifact_bytes 为本次预算；output_directory=null 返回会话文件，或明确新的绝对目录以保存。

只读取所选包/产物并核对摘要、轴及原坐标；区分 spectral_column、scan_column 与保存时域 source_column。联合 HTML 可含已保存的检测图、按请求绘制的现有波束谱/时频/频率—方向/BTR/扫描功率和候选/覆盖信息。未请求图片不自动绘制。

候选到源束的数值查找必须原结果摘要、算法、beam_id 一致，频点完全相等才查现有均值 PSD，否则标记无精确频点。时间平均 PSD 只是背景上下文，BTR 是频带积分，二者都不证明某瞬间某条谱线的空间表现。需要更细的证据时提出补算。

多检测任务列出输入、覆盖、单位、采样率及参数差异，保留各自量纲和网格，不输出排名/真实误报/Pd。同源 CBF/MVDR 一致不能当独立真值。正式比较指标转独立评价 Skill。

## 提议与确认后补算

支持三种明确动作：detection（本模块）、beam_execute（原波束执行器）、beam_products（原波束产物执行器）。独立评价暂不在该调度枚举中；不要发明一个已有评价执行器。

先准备责任模块自己的完整、明确子配置，保留真实用户决定；提议本身不运行。

propose-followup 配置含 association_ref={path,sha256}、output_path（新 AssociationRecord 路径）、proposal：

```text
followup_id, parent_refs, question, reason, action,
config_ref={path,sha256}, context_ref={path,sha256} 或 null,
source_root, dependencies
```

parent_refs 必须引用真实、已完成的 DetectionResult 或波束执行结果 file_ref，并与父关联记录中的结果身份、摘要完全一致；不接受任意证据文件代替父结果。若针对某个候选补算，在 question/reason 中注明候选 ID，同时引用其所属父结果。dependencies 每项包含 description、status、evidence_ref。提议器从显式子配置提取资源/产物摘要，以配置 SHA256 绑定 scope 与 parameters，写 pending approval；不填任何科学默认参数。

```text
python3 scripts/detection_associations.py propose-followup /absolute/proposal-config.json
```

实际补算配置严格含 followup_version=`1.0.0`、association_ref、followup_id、action、config_ref、context_ref、source_root、child_receipt_ref、max_process_seconds、result_record_path。

- detection 必须传明确 context_ref、source_root、已确认的 child_receipt_ref，max_process_seconds 必须为 null（进程内执行，不承诺超时中断）；子请求必须明确保存新结果，不能运行完才发现临时结果无处交接。
- beam 动作的 context_ref/child_receipt_ref/source_root 均为 null，输入边界由原 beam config 的显式路径绑定；原 beam config 必须通过其自身确认。必须保留其方向/时域保留/输入/参数/产物选择。模块缺失就报告，不安装、不复制计算核心、不从谱重建时域。
- beam 动作的 max_process_seconds 必须显式给正整数；只调用固定同级脚本，无任意命令或插件加载。子配置的校验与执行使用同一已核对内容快照。
- 子结果、执行记录及其附属记录不得位于只读 source_root 或任何父结果包目录内；父结果元数据读取上限为 1 MiB，超出需报告而非绕过。
- result_record_path 是新的执行记录路径；同名前缀 `.receipt.json`、`.association.json` 为最小确认及新关联记录，均不得覆盖已有文件。

```text
python3 scripts/detection_associations.py review-followup /absolute/followup.json
python3 scripts/detection_associations.py confirm-followup /absolute/followup.json --evidence /absolute/real-user-evidence.json --receipt-output /absolute/new-followup-receipt.json
python3 scripts/detection_associations.py run-followup /absolute/followup.json --receipt /absolute/new-followup-receipt.json
```

本层 receipt.scope=followup，不能拿 detection receipt 顶替。方案与责任模块自身门禁都通过才调用一次；不自动循环或重试。查看旧图、接受建议、旧 task 的确认不构成新补算授权。

结果另存，新 AssociationRecord 中保留父结果、补算状态、真实新结果引用与 followup_of 关系；不改父检测结果或父波束结果。失败另记 failed，子任务 partial 不报全成功。进程被杀或清单未完成时只承认未完成状态，不自动清理或覆盖目录。

## 边界

这是有限范围的显式协作，不是全局数据库、自动目标联合推理或闭环搜索。已实现已有数据的来源/坐标联合查看；缺少细分时频空间矩阵时仍须经责任模块确认生成，不能把显示能力写成所有新物理量均已可算。
