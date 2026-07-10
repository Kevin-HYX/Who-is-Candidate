# Candidate Search Tool 检索 module

Candidate Search Tool 是无状态、确定性的检索 module：调用方提交完整 QueryPlan，module 校验请求、读取可用 artifact、执行硬筛和软排序，并返回 SearchResult。自然语言理解与候选人解释不在该 interface 内；这让 CLI 与 MCP adapter 复用同一 implementation，获得 leverage，并把检索规则集中在一个 locality 内。

## 外部 seam

核心入口是 [`search_candidates`](../../src/retrieval.py)。CLI `search` 与 MCP `search_candidates` adapter 均在 [`src/main.py`](../../src/main.py)，但 MCP Query Surface 只读，不能触发 Preprocess 或 Build Index。QueryPlan 每次必须完整携带：

- `hard_constraints`：第一轮只过滤、不计分；
- `weighted_soft_preferences`：第二轮只排序、不淘汰，且至少有一项。

具体字段、操作符、维度、权重与 `top_k` 的机器契约由 [`src/constants.py`](../../src/constants.py) 和 [`validate_search_request`](../../src/schemas.py) 唯一定义。本文不复制完整枚举表，避免文档与 implementation 漂移。

## 执行数据流

```text
QueryPlan + options
  -> request validation
  -> shared live readiness projection(artifact + version + hash)
  -> Raw Profile、Preprocessed Profile、embedding 一致性校验
  -> 硬筛：fail 淘汰；证据不足保留并结构化标记
  -> 查询侧文本实时 embedding，或使用 Retrieval Trial 保存的同模型查询向量
  -> 候选人侧向量内存暴力 cosine
  -> 幸存池内 percentile
  -> 连续输入权重按绝对值总和归一化
  -> effective_weight * percentile 求和
  -> 排名 + Top K 同 rank 扩展
  -> SearchResult
```

In-Memory Brute-Force Retrieval 由 [ADR-0012](../adr/0012-use-in-memory-brute-force-retrieval.md) 固化。候选人侧向量由 Build Index 预先生成；普通搜索实时生成查询向量，Retrieval Trial 会保存并可重放同一查询向量。候选与查询向量必须是非空、同维且只包含有限数值；embedding provider/model identity 不匹配时索引视为 `missing`。

Search readiness 不读取独立状态记录。它与 CLI `index-status`、MCP `candidate://index-status`、Evaluation Browse 和 Retrieval Trial prerequisites 共用 Live Status Projection：从 Raw、Preprocessed、Embedding、Error artifact、当前 schema/model/index 版本与 hash 计算 `missing` / `partial` / `full`、覆盖率、计数、`source_ranges` 和 `next_actions`。

## 第一轮：硬筛

硬筛白名单只有代码定义的七个字段。每项由 `field`、`op`、`value`、`rationale` 构成，字段与操作符组合在进入检索前校验。

对每个候选人，implementation 只把 `confidence == high` 且值不是缺失状态的硬字段视为可裁决证据：

- 明确不满足任一硬条件：候选人被淘汰；
- 无法高置信裁决：候选人保留，`hard_filter_status.status` 为 `kept_with_insufficient_evidence`，相关字段进入 `insufficient_evidence_fields`；
- 全部明确满足：状态为 `passed`。

`seniority_level` 的比较顺序固定为 `Internship < Entry level < Associate < Mid-Senior level < Director < Executive`。它只表示主要当前职位的组织层级；Manager 需求映射到 `Mid-Senior level`，实际管人要求必须另用 `management_scope` 表达。

`medium` 与 `low` 在检索阶段行为完全相同：二者都不能硬淘汰，也不参与软分、权重或 tie-break。其区别只保留在 Preprocessed Profile 中供证据审计和 prompt 评测；`unknown` 是 value 状态而不是 confidence 档位。

证据不足不扣分，也不通过 fallback 猜测成满足或违反。这一结果语义由 [ADR-0009](../adr/0009-return-structured-hard-filter-status.md) 固化；字段提取的当前机器行为见 [`_evaluate_hard_constraints` 与 `_extract_hard_value`](../../src/retrieval.py)。

## 第二轮：软排序

每个软偏好选择一个可检索维度，提供具体工作内容文本与连续实数权重。输入权重必须位于 `[-2.0, -0.1]` 或 `[0.1, 2.0]`；正权重把相似候选人前推，负权重把相似候选人后移，不存在单独的 `avoid` interface。输入权重只表达 QueryPlan 内部的相对比例，检索层负责公式计算，不要求 Agent 自行凑总和。

```text
score_before_weight_i =
  count(other cosine < candidate cosine) / (survivor_count - 1)

effective_weight_i =
  input_weight_i / sum(abs(all_input_weights))

score_after_weight_i =
  round(round(effective_weight_i, 6) * round(score_before_weight_i, 6), 6)

final_score = sum(score_after_weight_i)
```

归一化后 `sum(abs(effective_weight)) == 1`，因此总分尺度不会随偏好数量或输入权重整体放大。单候选人幸存池的 percentile 为 `1.0`。候选人的某个软维度为 `not_provided` 时不生成该维度向量，该项 percentile 和加权贡献均为 `0`，候选人仍参与其他维度排序。raw cosine 不对外暴露；排名按 `final_score` 降序，并以 `user_id` 作为确定性排序键，同分采用 `1, 2, 2, 4` 形式的 rank。

## SearchResult 语义

SearchResult 只暴露足以审计检索的 interface：

- `search_meta` 描述 raw/index 覆盖、硬筛幸存数、请求与实际返回数、归一方式和公式；
- `results[]` 提供 `rank`、`user_id`、`final_score`、结构化 `hard_filter_status`、逐偏好的归一化实际权重与数值贡献，以及原始 `raw_profile`；
- `raw_profile` 始终返回，解释者只能据此陈述候选人事实；排序分不是绝对能力分。

部分索引允许搜索，但必须通过 metadata 暴露覆盖情况，见 [ADR-0004](../adr/0004-allow-partial-index-search-with-metadata.md)。`top_k` 是 best-effort：若第 K 位与后续候选人同 rank，完整返回该 rank，见 [ADR-0005](../adr/0005-top-k-is-a-best-effort-limit.md)。完整返回 shape 以 [`search_candidates`](../../src/retrieval.py) 为准，不在本文维护第二份字段表。

## 错误语义

契约错误与业务错误使用 [`CandidateSearchError`](../../src/schemas.py) 的结构化 `{error: {code, message, ...details}}`。错误发生时不返回部分 SearchResult：

- QueryPlan 或 options 非法时，在 schema seam 直接拒绝；
- artifact 缺失、版本或模型 identity 不匹配、Raw/Search Text Hash 失效时，按实时计算的真实可用性报告 `missing` / `partial` / `full`；
- cached `user_id` 找不到 Raw Profile、Raw Profile Hash 不一致、Search Text Hash 不一致时，搜索整体失败，不跳过候选人；见 [ADR-0011](../adr/0011-require-raw-profile-for-cached-candidates.md)；
- embedding 维度缺失、向量形状错误或包含 `NaN` / `Infinity` 时直接失败，不使用零向量、旧向量或其它维度作为 fallback。

所有错误码和附加字段以 [`src/schemas.py`](../../src/schemas.py) 与 [`src/retrieval.py`](../../src/retrieval.py) 为机器契约；MCP adapter 只负责把该结构序列化为 tool result，不改写语义。
