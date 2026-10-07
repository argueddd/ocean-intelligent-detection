# 波束时域 → 线谱 Skill 交接

当前波束数值执行器版本仍为0.4.2，算法、配置与已有结果均未改变。交接契约仍为 v0.1，主结果交接实现修订为 v0.1.2（另有旁路契约0.1）；本次已完成合成与 S59 VLA 数据交接回归，未运行线谱检测；范围见 [验证记录](acceptance-v043.md)。

## 从本模块如何交付

1. 找到本次主 execute.py 成功写出的 result.json。当前适配器仅支持 execution_version=0.4 主结果，不接旧0.3格式或补图包；不自动追链找其他数据。
2. 核对用户需要的算法和方向是否已保存。beams 的 column 是保存列，scan_column 是计算方向列；两者不一定相同。
3. 进入同级 underwater-line-spectrum-detection Skill，完整阅读其 references/beamformed-input.md。使用 scripts/beamformed_input.py review 查看已保存波束、单位、频带和有效区间。
4. 明确算法 + beam_id 选择、完整样本轴/掩码保留策略、上游限制、新目录与资源预算，确认后 prepare。若没有保存时域，报告不能交接；另行确认重新生成时域的范围，不能从功率谱还原或偷偷选择其他目录的波形。
5. 接收方用 receive 核对交接包并获得信号身份、元数据、有效掩码路径及完整上游配置引用。交接工作到此结束，不确认或运行检测；未选择检测方法/阈值不阻断数据交接。

## 当前完成与未完成

- 已编码：显式选束、每束 [N,1] 无幅值变换复制、共用有效掩码、算法/波束/列映射、采样率、原始时间与频带/处理历史的保留、来源摘要核对、独立接收入口及 handoff-report.json 交接说明。
- 已运行验证：合成交接导出、便携接收，以及 S59 VLA 读取导出→波束形成→指定方向信息交接→接收。数据链路之外的检测没有运行。
- 不属于本交接模块：线谱方法选择、检测参数确认、谱估计、线谱计算和检测结果评价。此次不开发检测执行器，也不把它列为交接模块未完成项。
- 新交接不再生成 detection-draft.json 或检测参数 questions.json；旧包不改写、不删除，旧草稿不作为执行授权。

波束 result.json 的 handoff_status=blocked / downstream_integration=not_integrated 不被新交接流程改写。新 handoff.json 的 prepared 只表示数据输入准备；receive 的 accepted 只表示输入检查通过。参数齐全、输入就绪、检测完成和工程质量通过须分别报告。

单阵元或来自其他处理来源的已有波束另走 [旁路交接](bypass-handoff.md)，经明确读取检查导出后由 bypass_handoff.py 生成专用包；接收方使用 receive-bypass / load_bypass_signal，不与本页主结果格式混用。旁路的未知有效性保持null，不生成全有效掩码；仍只传数据与信息。两条路径都不增加目标自动选择或跟踪，也不删除历史时域文件。
