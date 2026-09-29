# LightRAG 完整内部原理：实体关系抽取 → 建知识图谱 → 检索全流程

## 核心特点

- 只在单个 Chunk 内做实体关系抽取；跨文档关系不是索引阶段生成，是查询阶段图遍历拼接出来
- 没有 GraphRAG 的社区检测、全局摘要聚合

## 整体流水线

原始文档 → 文本分块 → LLM 按 Chunk 抽取实体/关系（结构化分隔符输出）→ 解析结构化输出 → 实体归一合并、关系合并 → 构建图（NetworkX/Neo4j）+ 实体/关系向量索引 + 原始 Chunk 向量索引 → 用户 Query → Query 解析提取高低层关键词 → local（实体路径）/global（关系路径）两路检索 + 图一跳遍历 → 根据 source_id 回溯原始 Chunk 二次精排 → 拼装上下文给 LLM 生成答案。

## 一、实体、关系怎么提取

### 1. 前置步骤：文档切分

文档切为 Chunk，默认 chunk_token_size=1200，overlap=100。每个 Chunk 独立调用一次 LLM 做抽取，不会跨 Chunk 抽取关系。

重要：如果 A 实体在 Chunk1，B 实体在 Chunk2，两个 Chunk 文本都没有写 A-B 关系，LLM 不会凭空抽取出 A-B 边。

### 2. 抽取提示词（entity_extraction，中文版本）

分隔符约定（解析强依赖，不能出现在字段内容）：

- `<|>`：字段内部分隔符，分割同一个实体/关系的各个字段
- `##`：记录分隔符，多条实体、多条关系之间分割
- `<|COMPLETE|>`：抽取结束标记

提示词结构：

```
---目标---
给定文本，识别全部实体以及实体之间的全部关系，输出语言：{language}
实体类型限定：[{entity_types}]
---步骤---
1、抽取实体，每个实体包含：entity_name 实体名称、entity_type 实体类型、entity_description 实体描述。
   格式：("entity"<|>实体名<|>实体类型<|>实体描述)
2、从上面识别出来的实体中，抽取实体两两之间的二元关系。
   字段：source_entity 源实体、target_entity 目标实体、relationship_keywords 关系关键词逗号分隔、
        relationship_description 关系详细描述、relationship_strength 关系强度 0-1。
   格式：("relationship"<|>源实体<|>目标实体<|>关系关键词<|>关系描述<|>关系强度)
3、多元关系必须拆解成多条二元关系；关系视为无向，避免同时输出 A→B、B→A；
4、实体、关系记录之间使用 ## 分隔；全部结束输出 <|COMPLETE|>
```

附带 few-shot 示例给大模型模仿输出格式。

- 实体字段：entity_name、entity_type、entity_description
- 关系字段：source_entity、target_entity、relationship_keywords、relationship_description、relationship_strength(0~1)

### 3. LLM 输出示例

```
("entity"<|>陕西投资集团<|>组织<|>陕西省属国有投资平台)##("entity"<|>陕投A公司<|>组织<|>陕投集团下属子公司)##("relationship"<|>陕西投资集团<|>陕投A公司<|>控股,下属<|>陕西投资集团控股陕投A公司<|>0.9)##<|COMPLETE|>
```

### 4. 解析输出

LightRAG 拿到 LLM 字符串，按 `##` 切分成一条条记录；每条记录按 `<|>` 切字段；过滤格式异常记录；重试抽取最多 N 次。

glean 模式：开启后，会再次喂回 Chunk + 已抽取结果，让 LLM 补漏没抽出来的实体关系，提升召回。

## 二、知识图谱构建完整流程

默认图存储：NetworkX 内存图；可替换 Neo4j、PG-Graph；同时维护三套存储：图存储、KV 存储、向量存储。

### 步骤 1：收集全部 Chunk 抽出来实体、关系

每个 Chunk 产出一批实体、关系，每条实体/关系携带元数据：source_chunk_id（来自哪个文本块，溯源用）。不同 Chunk 会抽取出同名实体。

### 步骤 2：实体归一化合并（非常关键，跨文档能力瓶颈）

默认：严格字符串相等才合并："陕投集团" 和 "陕西投资集团" 会被当成两个完全不同节点，图谱分裂，跨文档关系断裂。社区版本有使用编辑距离模糊匹配，但官方原版没有做别名消解，政企场景必须修改抽取 Prompt 强制输出标准实体名。

合并实体描述：同一个实体来自多个 Chunk 有多段 description。如果总 token 很小，直接拼接；如果 token 超标，调用 LLM 把多段描述做摘要合并，生成统一的实体描述；聚合 source_id 列表：保存所有来自哪些 chunk，用于后面溯源原文。

### 步骤 3：关系合并

源实体、目标实体对一致，则合并这条边；合并多条 relationship_description，同样可 LLM 摘要；relationship_strength 取平均值；聚合全部 source_chunk_id。

### 步骤 4：写入图存储

NetworkX 中：节点 node：key = 实体名，属性 entity_type、description、source_ids；边 edge：(source, target)，属性 keywords、description、strength、source_ids。

### 步骤 5：同时构建两套向量索引（检索核心）

- 实体向量库（local 模式使用）：对每个节点"实体名+实体描述"做 Embedding；用于根据问题语义召回实体。
- 关系向量库（global 模式使用）：对每条边 relationship_keywords + relationship_description 做 Embedding；用于召回关系边。
- 原始 Chunk 向量库（naive 传统 RAG）：保存原始文本块向量，兜底召回。
- KV 数据库：保存原始 chunk 文本，根据 source_id 可以拿到原始文档片段。

⚠️ 再次强调：索引阶段不会推理不同 Chunk 之间隐性关系，不会生成新边。所有边全部来自各个 Chunk 内部 LLM 抽取结果。跨文档链路是查询时动态图遍历拼出来的。

## 三、检索阶段完整流程（4 种 mode：naive/local/global/hybrid/mix）

官方默认 mix = local + global + naive 三路结果合并。

### 阶段 1：Query 关键词提取

用户输入 Query → LLM 提取两类关键词：

- low-level 关键词（低层，实体导向）：问题里面具体实体、专有名词，供给 local 检索。
- high-level 关键词（高层，主题、关系导向）：问题背后主题、抽象关系，供给 global 检索。

### 阶段 2：两路图检索

**路径 A：local 模式（实体优先，适合查询具体对象事实）**

使用 low-level 关键词向量，在实体向量库做相似度 Top-K 召回，拿到一批候选实体节点。在知识图谱做一跳图遍历：取出这些节点所有直接相连邻居节点、相连的关系边。local 只擅长：已知某个实体，查它直接相连的关系。跨多跳、跨文档弱。

**路径 B：global 模式（关系优先，跨文档核心）**

使用 high-level 高层关键词，在关系向量库做相似度 Top-K 召回，召回一批关系边。拿到边两端全部实体，同样做一跳扩展。global 专门面向："A 和 B 之间有什么关系？"，沿着关系边，把分散不同文档的实体链路串联，实现跨文档推理。

### 阶段 3：关键一步——回溯原始 Chunk，防止幻觉（LightRAG 非常重要设计）

图谱里的实体、关系是 LLM 摘要生成的二手信息，直接喂给 LLM 容易幻觉。将 local、global 召回全部实体、关系，取出它们绑定的全部 source_ids，收集全部涉及的原始 Chunk ID；去重；拿用户原始 Query 向量（不是关键词向量），对这些候选原始 Chunk 做向量二次精排，选出 top-M 原始文本片段。

### 阶段 4：拼装上下文

上下文包含两部分：图谱结构信息（召回到的实体描述、关系描述，子图）+ 原始证据文本（经过重排的原始 Chunk 片段，作为事实依据）。设置 token 预算，截断上下文，送入 LLM 生成最终答案。

### 各 mode 能力对照表

| mode | 行为 | 适用场景 |
| --- | --- | --- |
| naive | 完全不使用图谱，传统向量 RAG | 简单语义问答 |
| local | 只走实体召回 + 一跳遍历 | 已知实体，查直接事实 |
| global | 只走关系边召回 + 遍历 | 跨文档实体关系分析、多跳推理 |
| hybrid | local+global 合并结果 | 综合问答 |
| mix | hybrid + naive 三路合并 | 默认，效果最全 |

## 四、跨文档实体关系的真实能力边界

**✅ 可以做到：**

文档 1：陕投集团控股 A 公司；文档 2：A 公司投资 B 项目。索引阶段：分别在各自 chunk 抽两条边；不会自动生成陕投集团-B 项目边。查询："陕投集团和 B 项目的关系" global 检索：召回两条边，运行时做两跳遍历，动态拼接链路：陕投集团 → A公司 → B项目，输出跨文档结论。

**❌ 做不到：**

文档 1 只讲甲；文档 2 只讲乙；两份文档完全没有提到甲乙之间任何线索。索引：不会产生甲-乙边；查询：即使 global 模式，也无法凭空构造两者关系；如果 LLM 输出关系，属于大模型幻觉。

## 五、政企项目落地常见修改点

- 别名消解问题：原版仅字符串匹配，建议修改 entity_extraction 提示词，要求 LLM 统一输出标准全称，禁止简称
- 开启 gleaning 二次抽取，提高实体关系召回
- 大规模数据，把 NetworkX 替换 Neo4j，方便导出、可视化全部图谱
- 如果需要多跳，可修改代码把默认 1-hop 改成 2-hop/3-hop，注意 token 膨胀
