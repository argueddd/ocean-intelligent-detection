# KnowledgeCore（知核）· 运维手册（RUNBOOK）v0.3

## 1. 架构与部署拓扑（v2）

```
浏览器（127.0.0.1:3080 页面）
  └─ dsh-knowledge 客户端：3 tab 极简工作台（总览/知识/自动化）+ 反哺按钮 + 健康徽章
        │ fetch /kb/*
        ▼
DSH 宿主进程（profile: web，bundle: dsh-knowledge，link 指向本目录）
  ├─ /kb/* 路由 + 工具（lightrag_query / kb_ingest / kb_update / kb_status / kb_propose / kb_analyze / kb_report）
  ├─ 单一写入口 service.js：origin 策略链 + 同 source 409 + 审计
  ├─ 意图账本 lib/intent.js：WAL（intents.jsonl）+ 状态机 + 串行执行器；文件字节走 spool/
  ├─ 收敛器 lib/reconciler.js：启动对账 + 定时核验（收养/标缺失/补删）
  └─ 注册表+审计：${DSH_HOME:-~/.dsh}/storages/dsh-knowledge/{registry.json,audit.jsonl,intents/intents.jsonl}
        │ HTTP
        ▼
LightRAG 容器（lightrag-docker-0.6B，127.0.0.1:9623，workers=1）
  配置：/home/sjy-spark/Desktop/work/rag/lightrag/light-rag-docker/LightRAG/.env.0.6B
  rerank：RERANK_BINDING=null（D5 关闭，勿改回）
```

## 2. 切换上线（v2 重构后）

```bash
# profile 挂载不变（dsh-knowledge link + bundles）
# 1) 重启 DSH 宿主进程
# 2) 浏览器强制刷新 http://127.0.0.1:3080
# 3) 验证：
curl -s http://127.0.0.1:3080/kb/health    # 引擎健康 JSON
# 会话头出现「知识库」工作台（总览/知识/自动化 3 tab）
```

## 2.1 图文关联（原文档图片）上线

宿主进程环境需带（缺失自动降级，检索行为不变）：

```bash
KB_LIGHTRAG_INPUTS_DIR=/home/sjy-spark/Desktop/work/rag/lightrag/light-rag-docker/LightRAG/inputs
```

EMF/WMF 图片依赖 libreoffice（宿主机 `libreoffice` 在 PATH 即可，已确认 /usr/bin/libreoffice）。

验证（重启宿主后）：

```bash
# 图片端点：占位符替换出的 URL 应返回图片字节（doc/path 取自 lightrag_query_data 注入结果）
curl -sI 'http://127.0.0.1:3080/kb/image?doc=%E5%86%85%E9%83%A8%E5%AE%A1%E8%AE%A1%E8%B4%A3%E4%BB%BB%E8%BF%BD%E7%A9%B6%E6%B5%81%E7%A8%8B%E5%9B%BE.pdf&path=%E5%86%85%E9%83%A8%E5%AE%A1%E8%AE%A1%E8%B4%A3%E4%BB%BB%E8%BF%BD%E7%A9%B6%E6%B5%81%E7%A8%8B%E5%9B%BE.blocks.assets%2F41ad46bdc15a5ca9d41ca2d2da06ccdd8da6813514753c1e738df8e5142ff112.jpg' | head -3
# 期望 HTTP/1.1 200 + content-type: image/jpeg；越界路径 404
```

对话验收：问“内部审计责任追究流程”，`lightrag_query_data` 证据应出现 `![原文档图片](http://127.0.0.1:3080/kb/image?…)`，回答中模型复制的图片直接显示；点开答案里的图片 URL 能加载。

## 3. 一键验收（本地契约测试，零网络零真实引擎）

```bash
cd /home/sjy-spark/Desktop/work/dsh/dsh-knowledge
node dev/run-tests.mjs        # 11 套件：store/engine/intent/reconciler/service/curator/images/analyze/feedback/ops/render
# 单个：node dev/contract-intent.mjs 等
```

UI 人工验收清单（宿主重启后）：

| # | 操作 | 预期 |
|---|---|---|
| 1 | 会话头切「知识库」→ 总览 | 引擎健康绿点、体检分数（口语化三指标）、近 7 天检索、待办清单（点击直达） |
| 2 | 「知识」tab 拖拽 docx/pdf 或粘贴文本 | 入队（意图）→ 列表 pending → active；失败文档可一键重试 |
| 3 | 「知识」tab：替换/退役 | 版本链推进、状态 outdated/retired、确认框交互 |
| 4 | 「知识」tab：实体搜索→图谱 | 点节点可编辑描述/合并/删除（管道忙时入口禁用） |
| 5 | 对话中某条回复点「💾 沉淀到知识库」 | 内联表单 → 按钮「✓ 已沉淀」→ 检索可命中；重复沉淀自动替换 |
| 6 | 「自动化」tab | 提案流水（考试通过/已生效等口语化状态）、体检报告、stuck 意图可重试 |
| 7 | 停掉 LightRAG 容器再重启 | 徽章变红→恢复；重启后未完成意图自动续跑（WAL 恢复） |

## 4. 已知运维要点（实测）

1. **MinerU 当前异常（用户确认）**：PDF 沉淀暂时会失败（走 failed 状态，可从「知识」tab 重试）。建议暂用 docx/md/txt/xlsx。
2. **删除是分钟级异步**：本库图谱 10.9 万节点，每次删除触发全图重建；期间管道忙、图谱编辑 409。
3. **删除请求忙时可能被引擎静默丢弃** → 意图账本自动核验补发直至收敛；重试耗尽转 **stuck**（界面可见，手动重试即可恢复，绝不静默丢失）。
4. **重启不丢操作**：所有文档变更先落 `intents/intents.jsonl`（WAL）再执行；重启后 pending/issued/verifying 全部续跑；崩溃窗口（上传落地但 WAL 未记 issued）按 source 找回转核验。
5. **GraphML 不支持数组值** → 服务层已自动拍平；不要绕过 service 直接裸调引擎传数组。
6. **rerank 双保险关闭**：容器 `RERANK_BINDING=null` + 请求级 `enable_rerank:false`。启用时两处都要改。
7. **收敛器**：启动时全量对账（引擎孤儿→收养；注册表有引擎无→missing；retired 残留→补删意图），周期核验每 10 分钟；报告在 `/kb/curator/stats` 的 lastReconcile。

## 5. 故障排查

| 症状 | 排查 |
|---|---|
| 徽章红/工作台报"引擎不可达" | `docker ps \| grep lightrag`；`curl 127.0.0.1:9623/health`（忙时可能 60s 超时，稍后重试） |
| 文档卡 pending/processing | `/kb/documents` 看 intent 状态；track 15 分钟超时自动 stuck；`/kb/intents` 看账本明细 |
| 意图 stuck | 「自动化」tab 或 `GET /kb/intents?status=stuck`；多为引擎忙/删除被丢弃，确认引擎空闲后重试（重试计数清零） |
| 删除后文档仍在 | 正常（异步分钟级）；账本会自动补发；stuck 才需人工 |
| 文档标 missing | 引擎侧确实没有（外部删除/故障）——收敛器自动标记；从「知识」tab 重沉淀或按审计回溯 |
| 图谱编辑 409 | 管道忙，等 idle 再试（总览页可看 pipeline 状态） |
| 门控提案 stuck | 回滚失败（极少）：看 `proposal_stuck` 审计行 + 现场状态，人工修复后重提 |
| 宿主要回滚旧版 | 恢复 profile package.json 的 dsh-lightrag 条目（旧目录已改名，需先 `mv` 回） |
