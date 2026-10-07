# 字段结构与待确认模板（0.1.0）

本页描述五类对象的序列化结构、待确认模板及单文档只读检查，只描述结构检查，不执行检测。另有 [runtime v1](runtime-v1.md)，不改变本检查器权限。新增跨文档预检、文件摘要核对和确认记录另见 [preflight 0.1.1](preflight.md)，不改变本页检查器的原范围。结构检查不代选算法、不计算真实信号，也不会修改既有交接中的 prepared / accepted / can_detect=false。

## 文件与职责

| 对象 | JSON Schema | 待确认模板 |
|---|---|---|
| 输入 SignalInput | [字段结构](../assets/schemas/SignalInput.schema.json) | [空白草稿](../assets/templates/SignalInput.draft.json) |
| 算法说明 AlgorithmDescriptor | [字段结构](../assets/schemas/AlgorithmDescriptor.schema.json) | [空白草稿](../assets/templates/AlgorithmDescriptor.draft.json) |
| 检测请求 DetectionRequest | [字段结构](../assets/schemas/DetectionRequest.schema.json) | [空白草稿](../assets/templates/DetectionRequest.draft.json) |
| 检测结果 DetectionResult | [字段结构](../assets/schemas/DetectionResult.schema.json) | [空白草稿](../assets/templates/DetectionResult.draft.json) |
| 波束关联 AssociationRecord | [字段结构](../assets/schemas/AssociationRecord.schema.json) | [空白草稿](../assets/templates/AssociationRecord.draft.json) |

共用类型放在 [common.schema.json](../assets/schemas/common.schema.json)。五类对象的科学语义分别见 framework-input / algorithm / request / result / association 文档；主流程与边界见 [范围规范](framework-v01.md)。

使用 JSON Schema [Draft 2020-12](https://json-schema.org/draft/2020-12/json-schema-core)。结构检查器使用固定的本地 Schema 注册表，不从文档中的路径或 URL 自动下载 Schema；实现依据见 [python-jsonschema 引用说明](https://python-jsonschema.readthedocs.io/en/stable/referencing/)。

## 共同信封与两种填写状态

每份文档必须包含：

- schema_version：当前为 0.1.0，与上游包、算法版本分开。
- record_type：上述五个名称之一。
- document_status：draft 或 specified。
- payload：本类对象的业务字段。
- unresolved_items：待解决项；逐项包含 field（JSON Pointer）、reason、affected_actions、question。

draft 表示草稿，不是“允许带默认值执行”。模板所有 payload 顶层字段均为 null，保留待填写问题，不预填采样率、方向、检测器、谱估计、阈值或用户同意。已知字段可以填写；未确定字段继续为 null。顶层字段组一旦填写，必须满足该组完整结构；组内信息尚不齐全时，可保留整组 null，将已有事实与缺口记在问题中，不补假值。草稿至少有一条待解决记录。

specified 只表示字段按照完整结构填写，unresolved_items 必须为空；不表示所有现实属性都已知。例如 units.status=unknown、validity.status=unknown 可以保留真实未知状态，其是否适合检测需要后续依赖核对和用户处理决定。没有解决必需信息时不得通过把状态改成 unknown 来规避条件。

draft 检查填写的字段组类型/枚举等，不做完整对象的跨字段语义检查；specified 额外执行本文列出的本地一致性检查。草稿阶段没有检测方法时，不应为通过检查编造 detector_id。

空数组只表达明确的“没有/不选择”，不能代替尚未决定。例如 compute/view/save 必须分别明确；[] 不会自动扩大为全部，也不会补算显示依赖。

## 如何填写

1. 复制所需模板到用户指定工作位置；不要直接把 Skill 内模板当成真实运行记录修改。
2. 按对应接口规范继承有证据的事实，填写用户已明确的选择。未知、冲突、假设及其适用范围分开记录。
3. 每条问题指向具体字段并说明受影响动作。不因当前在填写格式就强迫用户选择尚未进入设计阶段的检测方法。
4. 对于拟计算请求，先保留 approval.status=pending、bound_plan_sha256=null、evidence_refs=[]。系统不得为自己制造确认；本页 validate_contract.py 不计算或核验方案确认摘要，需另用 preflight.py。
5. 填写完整后可将 document_status 改成 specified 并运行检查。真实来源、依赖、未知处理及用户确认还要由后续门禁核对，不能凭 valid=true 执行。
6. DetectionResult 模板只能用来设计结构；未运行不得填成 completed 或捏造候选。若将来运行失败，candidates=null 并说明原因，不用 [] 冒充零候选。

不进行 JSON 类型强制转换、默认值填充、参数建议自动采纳或静默修复。公共字段拒绝未知键；算法专属 resolved_parameters、processing_steps.parameters、extensions 等扩展区域由后续算法说明约束，不等于这些区域已通过科学参数检查。

## 检查命令

在本 Skill 目录运行；所用 Python 环境需有 jsonschema 与 referencing。此次验证环境为 jsonschema 4.25.1、referencing 0.36.2。缺少依赖时报告，不自动安装。

只检查自带草稿：

~~~bash
python3 scripts/validate_contract.py assets/templates/DetectionRequest.draft.json
~~~

检查明确指定的用户文档，并核对对象类型：

~~~bash
python3 scripts/validate_contract.py /absolute/path/request.json --kind DetectionRequest
~~~

命令输出 JSON 到标准输出，不保存报告或修改文档，不读取其所引用的波形/清单，不加载算法代码，不做谱分析，也不发网络请求。包内相对路径只作字符串检查；未来读取文件时仍须检查真实路径和符号链接边界。

退出码：0 表示本次结构检查通过（草稿也可能为0），1 表示字段/一致性检查失败，2 表示输入无法解析/读取。缺少校验依赖等运行异常也会报告失败，不产生可执行许可。不要用退出码0判断“已确认”或“可计算”。

报告始终包含 can_execute=false，并列出未检查项。源文件可用性、确认状态、质量状态等是文档的声明，结构检查不替这些声明背书。

## 已实现检查范围

JSON Schema 检查：

- 信封、版本、必填字段、类型、枚举与公共字段拼写；草稿待定状态与 specified 结构分开。
- 源身份、样本/单信号轴、明确未知、不适用和方向约定的表达形式。
- approval 的 pending/confirmed 字段组合；这不是验证真实同意。
- 失败/受阻需原因，只有 completed 可以携带候选数组；completed 至少有实际处理区间。
- 候选频率、分析支持、未估计/已估计事件范围分开；measurements=[] 合法。
- 声称概率需有0至1的值及校准证据引用，声称质量 evaluated 需证据引用；证据是否真实有效未验证。
- 已保存产物需文件定位/摘要及出处，包内路径不得直接包含上级越界或绝对路径。
- 关联实体的限定身份、关系枚举及补算状态字段；不提供 same_target 自动目标关系。

只读脚本额外检查 specified 文档内部：

- 严格 JSON：重复键、NaN/Infinity 及数值溢出被拒绝；不读取隐含配置。
- 样本数与形状声明一致，区间有序、不重叠、不越声明样本数；已知频带顺序和实信号 Nyquist 范围。
- 任务/步骤/候选/产物等本对象内 ID 唯一，未知处理指向本请求的任务。
- 结果候选归属、频带与分析支持不超出本任务已声明覆盖；已完成任务的处理区间与排除区间解释全部请求范围，不能相互重叠。
- 关联引用不悬空，比较和映射不引用未声明实体。
- 算法嵌入参数/扩展 Schema 的格式检查与受限本地引用检查。

为核对覆盖，脚本可在内存中求区间集合的并集；这不拼接波形、不改写输入区间、不授权跨缺口分析。

算法嵌入 Schema 当前只支持 Draft 2020-12、文档内 JSON Pointer $ref；不支持外部 $ref、$id、动态锚点、自定义词汇等。只审查定义格式，不执行其 default，不把检测请求自动套入这些定义。实际参数/产物依赖及能力声明的匹配现由 preflight.py 的受限子集检查；算法参数/有效支持/来源与执行门禁另由 runtime v1 核对，统计假设真实性仍需外部证据。

## 本页结构检查器明确不检查的内容

- 真实文件是否存在、摘要是否正确、上游内容和轴是否符合声明；只读源在运行期间是否变化。
- 上游交接对象到 SignalInput 的实际适配与自动提取。
- 算法是否已登记、实现是否可信可用、请求与输入/算法/结果之间是否一致。
- 实际搜索范围是否满足某个算法，帧是否跨无效样本，未知项能否被某个任务接受。
- 用户是否真正确认该方案，确认摘要与实际输入/参数/输出是否绑定，版本变化后是否失效。
- 资源预算是否可行、保存目的地是否安全、产物是否真正生成，以及运行与质量声明是否真实。
- 检测执行、双向检索服务、联合查看、波束补算调度、数值效果与工程验收。

上述未检查项仅描述 validate_contract.py。preflight.py 已覆盖其中明确文件的摘要/头部和一部分请求、输入、算法声明及确认摘要绑定，并可显式启用 input_adapter.py 的真实主/旁路包适配核验；这些额外能力不改变本页结构检查器的范围。仍不覆盖身份认证、科学/资源运行核验或检测执行。请依 [适配器](input-adapter.md) 和 preflight.md 解释，不把它们混为完整执行器。

因此：结构有效 ≠ 信息真实 ≠ 参数适用 ≠ 获准执行 ≠ 已执行 ≠ 效果合格。

## 验证记录

已运行 [结构测试](../tests/test_contract_schema.py) 原有40项，使用程序内构造的合成 JSON 记录；包括五类完整结构和五类草稿、反例、CLI退出码、输入未改写及无副产物检查。测试中的哈希、算法ID、波形引用与“确认证据”均是隔离的假数据，不得复制成真实请求或授权。

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
~~~

这不是 S59 实测、算法效果测试或公共执行门禁验收。已有独立检测脚本与交接脚本未作功能修改，未因本次格式测试扩大其验证结论。
