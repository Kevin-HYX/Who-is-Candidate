# 检索工具对外接口设计（给下游 Agent 用）

> 本文定义 Candidate Search Tool 暴露给下游 LLM Agent 的输入/输出接口。工具只负责确定性检索与排序，把候选人的原始 profile 数据返回给 Agent；解释、对比、推荐话术由 Agent 基于原始数据完成。
>
> 核心约束：本 API 无状态。每次请求都自带完整 QueryPlan，服务端不保存会话状态。多轮精修的状态由调用方自己保存和拼装。
>
> 相关：[SystemDesign.md](./SystemDesign.md)、[ScoringDesign.md](./ScoringDesign.md)、[SchemaDesign.md](./SchemaDesign.md)、[AgentSystemPromptDesign.md](./AgentSystemPromptDesign.md)。

---

## 1. 一个核心设计决定：谁来写 QueryPlan？

Agent 自己写 QueryPlan JSON，工具只执行 `search_candidates(query_plan, options)`。

Search Tool 不提供 `parse_query(text)`，也不在内部调 LLM 解析用户需求。Agent 负责理解用户意图、维护多轮上下文、向用户解释数据限制；如果工具再解析一遍自然语言，会引入第二个不可控解释层，导致难调试、难复现。

职责边界：

- Agent：理解自然语言、维护多轮状态、生成完整 QueryPlan JSON、解释返回的原始 profile。
- Tool：校验 QueryPlan、执行硬过滤与软排序、返回简单检索元信息、软偏好分数和原始候选人数据。

---

## 2. 主接口：`search_candidates(query_plan, options) -> SearchResult`

MCP 第一版只暴露这一个工具。CLI 可以提供 `search` 命令复用同一套入参和返回 schema。

MCP 接口不接受 `config` 参数，也不向 Agent 暴露本地配置路径、API Key、模型名或其它本地环境信息。配置只由本地 CLI 启动进程读取。

如果本地配置文件缺失或必填配置缺失，MCP server 不应启动。MCP 接口只处理已经启动后的 QueryPlan 校验、搜索和索引状态查询；配置缺失不等同于索引缺失。

`search_candidates` 运行时需要 embedding 模型配置和 API Key，因为查询侧 soft preference 文本必须实时生成向量。

### 2.1 输入：QueryPlan

```json
{
  "hard_constraints": [
    {
      "field": "seniority_level",
      "op": ">=",
      "value": "Senior",
      "rationale": "用户说'资深'"
    },
    {
      "field": "role_family",
      "op": "in",
      "value": ["Finance & Accounting"],
      "rationale": "用户要求财务方向"
    }
  ],
  "weighted_soft_preferences": [
    {
      "dimension": "domain_search_text",
      "text": "在医疗行业财务、账单、保险、合规或收入管理场景中工作",
      "weight": 1.2
    },
    {
      "dimension": "responsibilities_search_text",
      "text": "以外部审计、审计测试、审计底稿和审计合规检查为主的工作",
      "weight": -0.8
    }
  ]
}
```

QueryPlan 只有两个可执行部分：

| 部分 | 作用 | 关键点 |
|---|---|---|
| `hard_constraints[]` | 第一轮纯过滤 | 每条含 `field`、`op`、`value`、`rationale`。`field` 必须是 7 个硬筛白名单字段之一；只淘汰，不产生分数 |
| `weighted_soft_preferences[]` | 第二轮加权打分 | 每条是 `{ dimension, text, weight }`。数组不能为空；`text` 写成具体工作内容；`weight` 可正可负但不能为 0 |

硬条件不再提供单独的强弱标记字段。包含、排除、比较语义全部由字段对应的 `op` 表达。

Agent 可以在自己的对话状态里保存排序备注，但不要发送给 Tool；Tool 只接收可执行搜索条件。

### 2.1.1 硬筛字段白名单

哪些字段可以作为 hard constraints 是代码里的固定接口契约，不是运行时从样本里临时判断。实现必须在 `constants.py` 或等价位置定义白名单，并由 schema 校验直接引用：

```python
HARD_CONSTRAINT_FIELDS = {
    "years_of_experience",
    "highest_degree_level",
    "role_family",
    "seniority_level",
    "management_scope",
    "industries",
    "is_currently_working",
}
```

这 7 个字段的共同条件是：数据覆盖相对可支撑、值可枚举或可比较，并且候选人侧只有明确字段或 high confidence evidence 才能用于淘汰。`certifications`、`skills`、工作描述、地点、公司性质、分领域年限、团队规模、成果等字段本期不能硬筛。即使用户说“必须”，Agent 也应在生成 QueryPlan 前把它们改写为软偏好或说明数据限制。

### 2.1.2 硬筛操作符

操作符按字段限定，schema 校验阶段直接拒绝非法组合。

| 字段 | 允许的 `op` |
|---|---|
| `years_of_experience` | `>=`, `<=`, `>`, `<`, `=` |
| `highest_degree_level` | `>=`, `<=`, `=` |
| `seniority_level` | `>=`, `<=`, `=` |
| `role_family` | `in`, `not_in` |
| `industries` | `in`, `not_in` |
| `management_scope` | `>=`, `<=`, `=`, `in`, `not_in` |
| `is_currently_working` | `=` |

### 2.1.3 软偏好约束

`weighted_soft_preferences` 禁止为空。搜索必须至少有一个可执行软偏好，否则返回 `EMPTY_SOFT_PREFERENCES`。

允许的 `dimension`：

- `responsibilities_search_text`
- `skills_search_text`
- `experience_search_text`
- `domain_search_text`
- `ownership_search_text`
- `achievements_search_text`
- `education_search_text`

`text` 必须写成具体工作内容或业务场景，不能只写职位名、裸关键词或只有否定词。负向需求不使用 `avoid` 字段，而是写成负权重软项，例如“不要纯审计”写成：

```json
{
  "dimension": "responsibilities_search_text",
  "text": "以外部审计、审计测试、审计底稿和审计合规检查为主的工作",
  "weight": -0.8
}
```

`weight` 范围为 `[-3.0, 3.0]`，不能为 `0`。正数表示越像越靠前，负数表示越像越靠后。

### 2.2 options

```json
{
  "top_k": 20
}
```

- `top_k` 默认 20，最大请求 75，超过直接返回 `TOP_K_TOO_LARGE`。
- `top_k` 是“系统尽最大努力限制在这个值之内”，不是硬截断。若边界同分，工具必须完整返回同 rank 候选人，允许 `returned_count > requested_top_k`。
- `normalization` 固定为 `percentile`，不是调用方可选项。
- `raw_profile` 固定返回，调用方不可关闭。

---

## 3. 输出：SearchResult

工具输出只保留简单检索元信息、软偏好数值贡献和原始候选人数据。不要返回复杂解释结构；Agent 自己读取 `raw_profile` 做解释。

```json
{
  "search_meta": {
    "total_raw_candidates": 1000,
    "indexed_candidates": 1000,
    "index_status": "full",
    "source_ranges": [[0, 1000]],
    "passed_hard_filter": 47,
    "requested_top_k": 20,
    "returned_count": 22,
    "normalization": "percentile",
    "returned_beyond_top_k_reason": "第 20 名与后续候选人 final_score 相同，完整返回同 rank 候选人",
    "score_formula": "final_score = sum(score_after_weight); score_after_weight = weight * score_before_weight"
  },
  "results": [
    {
      "rank": 1,
      "user_id": 218051274,
      "final_score": 1.41,
      "hard_filter_status": {
        "status": "passed",
        "insufficient_evidence_fields": []
      },
      "soft_preference_scores": [
        {
          "preference_index": 0,
          "dimension": "domain_search_text",
          "weight": 1.2,
          "score_before_weight": 0.83,
          "score_after_weight": 0.996
        },
        {
          "preference_index": 1,
          "dimension": "responsibilities_search_text",
          "weight": 0.6,
          "score_before_weight": 0.69,
          "score_after_weight": 0.414
        }
      ],
      "raw_profile": {
        "user_id": 218051274,
        "headline": "Administrator and Billing Manager",
        "summary": "...",
        "skills": [],
        "is_working": true,
        "active_experience_title": "Independent Contractor",
        "experience": [],
        "education": [],
        "awards": [],
        "courses": [],
        "certifications": [],
        "publications": [],
        "patents": []
      }
    }
  ]
}
```

### 输出字段说明

| 字段 | 含义 |
|---|---|
| `search_meta.total_raw_candidates` | 原始 JSONL 中候选人总数 |
| `search_meta.indexed_candidates` | 当前可搜索索引覆盖的候选人数 |
| `search_meta.index_status` | `missing`、`partial` 或 `full`。SearchResult 正常返回时只能是 `partial` 或 `full` |
| `search_meta.source_ranges` | 当前索引覆盖的原始 JSONL 行号区间，0-based、左闭右开，已合并相邻或重叠区间 |
| `search_meta.returned_beyond_top_k_reason` | 若因边界同分超过 `top_k`，在这里说明原因；否则为 `null` |
| `results[].rank` | 排名；同分使用相同 rank，例如分数 `9.0, 8.5, 8.5, 8.0` 对应 rank `1, 2, 2, 4` |
| `results[].user_id` | 候选人 ID，也是缓存主键 |
| `results[].final_score` | 内部排序分，只用于排序和同分解释 |
| `results[].hard_filter_status` | 结构化硬过滤状态，说明候选人是完全通过，还是因证据不足被保留 |
| `results[].soft_preference_scores` | 每条软偏好的数值贡献；与 `weighted_soft_preferences[]` 按 `preference_index` 对齐 |
| `results[].raw_profile` | 原始候选人 profile，对象结构与 JSONL 原始数据一致，不塞入工具分数字段 |

`soft_preference_scores[].score_before_weight` 是该 preference 在幸存池内归一化后的 percentile 分数，不暴露 raw cosine。`score_after_weight = weight * score_before_weight`，`final_score = sum(score_after_weight)`。

`hard_filter_status` 取值示例：

```json
{
  "status": "kept_with_insufficient_evidence",
  "insufficient_evidence_fields": ["management_scope"]
}
```

`insufficient_evidence_fields` 只列出本次 QueryPlan 涉及、且候选人无法高置信判断的硬筛字段。

### 明确不返回的复杂解释字段

本期 SearchResult 不返回以下候选人级复杂解释：

- `soft_contributions`
- `hard_constraint_report`
- `matched_evidence`
- `missing_or_weak`
- `risk_flags`
- `raw_profile_summary`
- 任何同分分组字段

这些解释由 Agent 基于 `raw_profile` 和 `search_meta` 自行完成。这样可以避免 Tool 输出过厚，也避免让 Agent 被工具生成的解释牵着走。

---

## 4. 错误返回

业务和契约错误返回结构化 JSON，不进入检索，也不返回部分结果。

```json
{
  "error": {
    "code": "INVALID_HARD_CONSTRAINT_FIELD",
    "message": "hard_constraints[0].field is not allowed",
    "field": "certifications",
    "allowed_fields": [
      "years_of_experience",
      "highest_degree_level",
      "role_family",
      "seniority_level",
      "management_scope",
      "industries",
      "is_currently_working"
    ]
  }
}
```

主要错误码：

| code | 含义 |
|---|---|
| `INVALID_HARD_CONSTRAINT_FIELD` | 硬筛字段不在 7 个白名单内 |
| `INVALID_HARD_CONSTRAINT_OPERATOR` | 字段与操作符组合不合法 |
| `INVALID_HARD_CONSTRAINT_VALUE` | 硬筛字段的 value 类型或枚举值不合法 |
| `EMPTY_SOFT_PREFERENCES` | `weighted_soft_preferences` 为空 |
| `INVALID_SEARCH_DIMENSION` | 软偏好维度不在白名单内 |
| `INVALID_SOFT_PREFERENCE_TEXT` | 软偏好文本为空、过短或只有否定词 |
| `INVALID_WEIGHT` | 权重超出范围或为 0 |
| `TOP_K_TOO_LARGE` | `top_k` 超过 75 |
| `PREPROCESS_AND_INDEX_NOT_BUILT` | 没有可用预处理结构和索引 |
| `SEARCH_INDEX_NOT_BUILT` | 有可用预处理结构，但没有可用索引 |
| `RAW_PROFILE_NOT_FOUND` | 缓存里的 `user_id` 在原始 JSONL 中找不到 |
| `RAW_PROFILE_HASH_MISMATCH` | 原始 profile 已变化，预处理结构失效 |
| `SEARCH_TEXT_HASH_MISMATCH` | 当前预处理检索文本与 embedding 缓存不一致，需要重新 build-index |

不提供单独的 `validate_query_plan` 接口。校验发生在 `search_candidates` 内部；Agent 如果需要知道索引和数据状态，必须读取 MCP 资源 `candidate://index-status`。

---

## 5. MCP 资源

MCP 资源只做只读说明和状态查询，不触发构建。

| 资源 | 用途 |
|---|---|
| `candidate://query-guide` | Agent 的使用说明书：QueryPlan schema、搜索词书写规则、示例、SearchResult 解读方式 |
| `candidate://index-status` | 当前原始数据、预处理结构和索引覆盖状态；状态来自 `data/processed/status.json` |

`candidate://query-guide` 不硬编码实时覆盖数字。Agent 每次需要判断是否已建立预处理或索引时，必须读取 `candidate://index-status`。

MCP 资源不得返回本地配置路径、API Key、模型名或其它本地环境信息。

`candidate://index-status` 只表达原始数据、预处理结构和索引覆盖状态，不表达配置文件是否存在。

---

## 6. 给 Agent 的使用契约

1. Agent 自己写 QueryPlan，再调用 `search_candidates`。
2. Agent 必须在写 QueryPlan 前理解字段完备性：只有 7 个白名单字段可以写入 `hard_constraints`，低完备性字段必须写成软偏好或向用户说明限制。
3. Agent 应通过 `candidate://index-status` 判断当前是否有可用索引；如果状态是 `missing`，需要提示用户先用 CLI 建立预处理结构和索引。
4. Agent 解释候选人时，只能引用 `raw_profile` 里真实存在的字段。
5. 对 `raw_profile` 中缺失或为空的字段，只能说“简历未写 / 无法确认”，不能说“没有”。
6. Tool 返回的 `final_score` 和 `soft_preference_scores` 只表示本次 QueryPlan 下的排序依据；Agent 不应把它包装成绝对能力分。
7. 同分候选人会使用相同 `rank`；如果结果超过 `top_k`，要说明是为了完整返回同 rank 候选人。
8. 如果 Tool 返回 QueryPlan 校验错误，Agent 必须修正 QueryPlan；无法修正时，再向用户解释哪些需求不能按硬筛执行。

---

## 7. 一句话总结

Search Tool 的接口是：Agent 输入完整 QueryPlan，Tool 返回简单元信息、软偏好数值贡献和排序后的原始 profile 列表。Tool 不输出长解释，Agent 负责读原始 profile 并向用户解释。
