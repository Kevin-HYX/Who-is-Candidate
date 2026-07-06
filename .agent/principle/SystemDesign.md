# System Design

## 目标

构建一个可审计的候选人搜索 Agent。用户用自然语言描述招聘需求，系统从候选人 profile 中检索并排序候选人。Search Tool 本期只返回简单检索元信息和排序后的原始候选人 profile；匹配理由、对比和风险解释由 Agent 基于原始字段完成。

## 核心思路

系统分两层：

- Candidate Search Tool：确定性检索层，负责解析候选人数据、硬条件过滤、多维度评分和排序，并返回原始候选人 profile。
- LLM Decision Agent：交互决策层，负责理解多轮用户意图，并在检索返回的 Top-K 内做解释、对比和继续筛选。

LLM 不直接从全量候选人里自由搜索，避免幻觉和不可复现；它只消费 Search Tool 返回的 Top-K 原始 profile 和简单检索元信息。

> **本期范围**：只实现第一层 **Candidate Search Tool**，且做成**无状态 API**——每次请求自带完整 QueryPlan，服务端不保存会话。第二层交互 Agent 不在本期，多轮筛选的状态由调用方（Agent）自己保存、拼装后重新调用检索工具（见 [ToolInterfaceDesign.md](./ToolInterfaceDesign.md)）。

## 如何实现

候选人预处理为预处理结构（完整契约见 [SchemaDesign.md](./SchemaDesign.md)），主要包含：

- `hard_fields`：7 个够格硬字段（年限、学历等级、职能族群、职级、管理范围、行业、是否在职），用于第一轮过滤。
- `embedding_search_texts`：responsibilities、skills、experience、domain、ownership、achievements、education 等分维度检索文本，用于第二轮软打分。
- `derived_fields`：原始数据没有、但可算出的派生指标（分领域年限、任职时长、地点等），本期作软用途与解释。
- `keyword_signals` / `risk`：关键词信号与风险文本。
- 每个推断字段都带 `confidence` / `source_field` / `evidence`，可回溯原始字段。

## LLM 数据转换与优化

原始 profile 字段比较散，不能直接把整段 JSON 丢进 embedding。预处理阶段先由 LLM 把每个候选人转换成统一的预处理结构，但所有推断必须保留证据。

LLM 需要做的转换：

1. 归一化职位：从 `headline`、`active_experience_title`、`experience.title` 中提取当前职位、历史职位、岗位族群和 seniority。
2. 归一化技能：清洗 `skills` 中的噪声词，把标准技能、工具、行业词、软技能拆开，并用 `experience.description` 验证技能是否真的用过。
3. 提取经验事实：从 `experience` 中总结做过什么、在哪些业务场景做、是否负责交付、是否管理团队、是否有结果产出。
4. 提取硬条件字段：把工作年限、学历、当前是否在职、管理层级、行业、岗位族群等转成结构化字段；证书、技能、地点、公司性质、分领域年限等本期只进入软打分或解释，不进入第一轮硬筛。
5. 生成多个检索文本：分别生成 `responsibilities_search_text`、`skills_search_text`、`experience_search_text`、`domain_search_text`、`ownership_search_text`、`achievements_search_text`、`education_search_text`。
6. 生成风险文本：生成 `role_boundary_risk_text`、`research_only_risk_text`、`skill_stuffing_risk_text`，用于处理“看起来像但职责边界不匹配”的候选人。

LLM 输出约束：

- 每个推断字段必须带 `confidence`、`source_field` 和 `evidence`。
- 没有证据的字段只能标为 `unknown`、`not_provided` 或 `insufficient_evidence`。
- 缺失字段不能被当作负面证据，也不能被强行推断成满足条件。
- 原始 profile 必须保留，最终解释必须能回溯到原始字段。

## 候选人检索与排序

采用**两段式**：第一轮硬条件纯过滤（只淘汰、不打分），第二轮软条件加权打分（只打分、不淘汰）。硬与软彻底解耦。详细评分机制见 [ScoringDesign.md](./ScoringDesign.md)，对外接口见 [ToolInterfaceDesign.md](./ToolInterfaceDesign.md)。

用户查询由 Agent 解析并写成固定 `QueryPlan` JSON（两块），Search Tool 不解析自然语言：

- `hard_constraints`：第一轮过滤条件，每条包含 `field`、`op`、`value`、`rationale`；包含、排除和比较语义由字段对应的 `op` 表达，只用于淘汰。
- `weighted_soft_preferences`：第二轮打分项，每条 `{ dimension, text, weight }`，weight 可正可负。

`hard_constraints.field` 必须来自代码中固化的 7 个白名单字段：`years_of_experience`、`highest_degree_level`、`role_family`、`seniority_level`、`management_scope`、`industries`、`is_currently_working`。非白名单字段在 QueryPlan 校验阶段直接报错，不进入检索，也不由 Tool 临时降级。

## 第一轮：硬条件过滤（pass / fail）

硬条件只判断候选人是否有资格进入排序池，**不产生分数**。明确违反任一硬条件的候选人剔除；证据不足者**保留进池并在 `hard_filter_status.insufficient_evidence_fields` 中标记**，不淘汰也不扣分。

能挂硬条件的字段有限——必须数据充分、且值为**枚举或可比较数字**。够格的只有 7 个（详见 SchemaDesign）：

- `years_of_experience`：工作年限阈值。
- `highest_degree_level`：学历等级（0/1/2/3）。
- `role_family`：职能族群（18 类枚举）。
- `seniority_level`：职级（8 档，可比较）。
- `management_scope`：管理范围（none/lead/manage/decision）。
- `industries`：行业（24 类枚举，多值）。
- `is_currently_working`：是否在职。

硬条件只从明确字段或高置信 evidence 判断；低置信推断不能直接剔除候选人。

## 第二轮：软条件加权打分

对幸存池中每个候选人：

```text
score_before_weight_i = percentile_i
score_after_weight_i = weight_i × score_before_weight_i
final_score = Σ score_after_weight_i
```

- 每个软项 `{ dimension, text, weight }`：`dimension` 指向某个 `*_search_text` 检索维度，`text` 是"具体做什么"的工作内容描述，`weight` 可正可负。
- `score_before_weight_i`：`text` 与候选人该维度检索文本的 embedding 余弦相似度，**在幸存池内换算成排名百分位**（0~1），不对外暴露 raw cosine。
- `score_after_weight_i`：该软项实际计入总分的加权后贡献。
- 按 `final_score` 降序排序；同分候选人使用相同 `rank`，不再输出单独的同分标记字段。

两个关键设计：

- **池内排名百分位校准**：embedding 余弦分是压缩的（常挤在 0.4~0.7）、跨维度基线不同，直接加权会让基线高的维度无理由主导。改用池内百分位后，各维度摊成可比的 0~1 分布，且分数对应"在本次候选池里排多前"。
- **负权重取代 avoid**："不要 X" 直接写成一个负权重软项（正面描述那类工作 + 负 weight），与之越像总分越低。不再需要单独的负向画像改写和 penalty 机制。

## 暂不实现（未来工作）

以下"硬条件辅助软条件"的机制本期**不做**，从公式中移除：

- `agreement_boost`：语义 + 关键词双命中的一致性加分。
- `conflict_penalty`：职责边界 / 资历冲突扣分。
- `insufficient_evidence_penalty`：证据不足的分数惩罚（本期只标记不扣分）。

风险维度不进入 `final_score`，本期也不作为 SearchResult 的候选人级复杂字段返回。Agent 如需提示风险，必须基于返回的 `raw_profile` 原始字段自行判断并说明证据。

## 输出

排序后返回：

- `search_meta`：原始候选人数、已索引候选人数、索引状态、索引覆盖行号区间、硬过滤幸存人数、请求 top_k、实际返回数、是否因同分超过 top_k、分数公式。
- `results[]`：每个候选人的简单排序元信息（rank、user_id、final_score、hard_filter_status）、`soft_preference_scores` 数值贡献和 `raw_profile` 原始对象。

不返回候选人级复杂解释字段（如 `soft_contributions`、`matched_evidence`、`risk_flags`）。Agent 必须基于 `raw_profile` 原始字段自行解释，并遵守"缺失不等于没有"。

## 搜索流程

1. Agent 将用户自然语言解析为固定 `QueryPlan`（hard_constraints + weighted_soft_preferences），并把完整 QueryPlan 传给 Search Tool。
2. 第一轮：执行硬条件过滤，明确违反硬条件的剔除，证据不足者保留并标记 → 幸存池。
3. 第二轮：先为每个软项生成查询向量，再在内存中对已索引候选人的对应维度 embedding 做暴力相似度计算，并在幸存池内转成排名百分位。
4. `score_after_weight = weight × score_before_weight`，`final_score = Σ score_after_weight`，降序排序；同分使用相同 rank。
5. 返回 Top-K 候选人的简单排序元信息、软偏好数值贡献和原始 profile；若 top_k 边界存在同分，完整返回同 rank 候选人。
