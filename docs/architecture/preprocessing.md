# Preprocess module

Preprocess module 将一个 Raw Profile 转换为一个带证据、可缓存、可构建索引的 Preprocessed Profile。其外部 seam 是 CLI Build Surface；内部以模型调用 adapter 处理必须推断的内容，以确定性代码处理公式字段。这样调用方只学习一个构建 interface，推断、公式、重试与 Merge Write 都留在 module implementation 内，形成 leverage 与 locality。

## Interface 与职责

当前可执行入口是 [`preprocess_profiles`](../../src/preprocess.py)，由 [`src/main.py`](../../src/main.py) 的 `preprocess` CLI adapter 调用。输入包括 Runtime Config，可选 Build Workspace、左闭右开的 source row 范围、并发度和显式 cache 丢弃开关；输出包含本次处理、跳过、失败数量，以及从当前 artifact 实时计算的状态视图。

该 module 不属于 MCP Query Surface。MCP 不得预处理 profile，也不得触发任何 artifact 写入，这一 seam 由 [ADR-0001](../adr/0001-mcp-query-cli-build-boundary.md) 固化。

## 从 Raw Profile 到 7 个硬字段

```text
Raw Profile
  -> LLM adapter：推断 4 个硬字段
     role_family
     seniority_level
     management_scope
     industries
  -> code merge：写入 3 个公式硬字段
     years_of_experience
     highest_degree_level
     is_currently_working
  -> Preprocessed Profile.hard_fields：共 7 个硬字段
```

这里的“4 个 LLM output 字段”和“7 个 Preprocessed Profile 字段”专指 `hard_fields`，不是顶层 JSON 字段数。可执行 prompt 同一次还要求模型返回 `embedding_search_texts`、`derived_fields`、`keyword_signals` 与 `risk`；完整 prompt interface 只在 [`prompts/preprosess.md`](../../prompts/preprosess.md) 维护，不在本文复制。

三项硬字段公式以 [`src/preprocess.py`](../../src/preprocess.py) 为机器契约：

- `years_of_experience`：优先读取 `total_experience_duration_months` 并整除 12；缺失时按当前 implementation 汇总可用的 `experience[].duration_months`，置信度降为 `medium`。
- `highest_degree_level`：取 `education[].degree_level` 中的最大整数。
- `is_currently_working`：优先读取布尔 `is_working`；否则，任一 `experience[].is_current == true` 可高置信判定为 `true`，全部经历都显式为 `false` 才可高置信判定为 `false`，缺失或不完整时必须返回 `unknown`。

implementation 还会把 `current_role_tenure_months` 与 `avg_tenure_months` 写入 `derived_fields`。它们是代码公式派生字段，不计入七个硬字段。

## Current Position Level

`seniority_level` 表示候选人 Primary Current Position 的 Current Position Level，只使用六档 LinkedIn-aligned 顺序：

```text
Internship < Entry level < Associate < Mid-Senior level < Director < Executive
```

Preprocess 只考虑 `is_current == true` 的经历；多个当前职位优先按顶层 `active_experience_title` 选择主要职位，无法匹配时选择 `order_in_profile == 1` 的当前经历。没有当前职位时返回 `unknown + low`，历史职位不得补位。

标准化来源映射固定为：`Intern -> Internship`、`Specialist -> Associate`、`Senior/Manager -> Mid-Senior level`、`Director -> Director`、`President/Vice President` 与 `C-Level -> Executive`。`Founder`、`Owner`、`Partner` 和 `Head` 本身不决定职级；所有者身份写入 `ownership_search_text`。工作年限、证书、专业能力和缺失的管理描述均不得用于授予 `seniority_level + high`。

## Hard-Filter Confidence

所有硬字段统一使用 `high`、`medium`、`low` 三档 Hard-Filter Confidence，无论字段来自 LLM 还是代码公式。它不是概率，也不是模型对自己回答的主观把握：

- `high` 表示证据直接、明确、无冲突，允许 Tool 根据该值执行硬淘汰；
- `medium` 表示存在相关证据，但仍依赖映射、上下文不完整、存在歧义或冲突，不能硬淘汰；
- `low` 表示证据很弱、稀疏或缺失，不能硬淘汰。

`medium` 和 `low` 不影响过滤、排序、权重或 tie-break，只用于证据审计、Browse 和 prompt 评测。`unknown` 是 value 的缺失状态，不再是 confidence 值：冲突或多解证据可形成 `unknown + medium`，缺失或极弱证据形成 `unknown + low`，`unknown + high` 非法。四个 LLM 推断字段分别在 executable prompt 中定义 `high` 的证据门槛；未达到对应门槛时，即使某个 value 看起来很可能，也不得标为 `high`。

## Preprocessed Profile 的最小可执行契约

当前 implementation 在写 cache 前至少验证：

- `hard_fields` 是对象，且包含上述七个对象字段；
- `embedding_search_texts` 是对象，且包含七个非空字符串；有正向检索内容时保存受控扩展文本，没有内容时必须使用 `not_provided`。维度白名单与缺失状态由 [`src/constants.py`](../../src/constants.py) 定义；
- 模型生成的自然语言必须使用英语和 Latin script；非 Latin 专名需要转写，运行时会拒绝非 Latin 字母；
- 推断结果必须遵守“缺失不是否定”：无法举证时使用 `unknown`、`not_provided` 或 `insufficient_evidence`，不得通过 fallback 编造事实。
- `confidence` 只能是 `high`、`medium`、`low`；unknown value 不能使用 `high`。`unknown + low` 的 `evidence` 只要求为非空英文，可以使用缺失状态词，也可以简要说明原始档案缺少什么证据。
- `seniority_level` 只能使用六档 Current Position Level 或 `unknown`；旧八档值会作为非法模型输出被拒绝。

`not_provided` 不会发送给 embedding 模型，Embedding Record 只保存实际可用维度的向量。候选人即使七个软维度均不完整，也不会因为软数据缺失而在 Build Index 阶段失败；缺失维度只在对应查询偏好上贡献 `0`，其他硬字段和软维度仍然可用。自然语言形式的缺失句和旧 `insufficient_evidence` 软文本会被拒绝，避免把“没有数据”本身嵌入为候选人语义。

每条成功 cache record 的 envelope 包含 `user_id`、`source_row_index`、`raw_profile_hash`、`preprocess_schema_version`、`preprocess_prompt_hash`、`preprocess_model_hash` 与 `preprocessed_profile`。字段校验与 record 形状以 [`src/preprocess.py`](../../src/preprocess.py) 为准；Versioned Build Cache 与 Raw Profile Hash 规则由 [ADR-0002](../adr/0002-versioned-merge-write-build-cache.md) 固化。

## Prompt seam

项目内生产 prompt 是 [`prompts/preprosess.md`](../../prompts/preprosess.md)。它是 Preprocess implementation 的内部资源，不是 CLI 或 MCP interface；这一决定见 [ADR-0015](../adr/0015-store-preprocess-prompt-as-internal-resource.md)。

Evaluation Loop 必须把显式 Prompt Artifact 复制为 Test Sample 的 `prompt_snapshot/preprosess.md`，再把 snapshot 路径注入同一个 Preprocess interface。生产构建和评测构建因此共用 implementation，但 prompt snapshot 的生命周期互不污染。

## Cache、失败与重试

- 未显式丢弃 cache 时，schema、Raw Profile、Prompt Snapshot 和模型配置 identity 全部匹配的候选人会被跳过；Prompt 或模型变化会同时使下游 embedding 失效。
- 每个待处理候选人独立尝试最多三次；初次与重试共享命令级并发上限。OpenAI SDK 内建重试被关闭，实际尝试次数只由该 module 控制。
- 待重建记录会在模型调用前从预处理和 embedding cache 移除；因此 `discard-cache` 重跑失败时不会继续使用旧成功结果。
- 成功项按 `user_id` Merge Write，并按 source row 顺序重写 JSONL；不使用 append-only 重复记录。
- 最终失败写入最新的 `preprocess_errors.jsonl`；成功项仍落盘，但命令以 `PREPROCESS_FAILED` 失败退出。全成功会删除旧错误 artifact。
- module 只持久化成功记录、输入 identity 和精确错误，不写动态状态文件。写入后由共享 Live Status Projection 根据实际 JSONL、当前版本、Prompt/模型 hash 与 Raw Profile Hash 重新计算覆盖和 readiness。
- 不允许静默降级为旧版本 cache，也不允许把 LLM 失败伪装成成功；错误 JSONL 是失败事实，不是需要与状态副本同步的计数来源。

## 维护 seam

修改推断语义或输出结构时，应同时核对 executable prompt、`_merge_formula_fields`、`_validate_preprocessed_profile`、下游 [`retrieval.md`](./retrieval.md) 与 `PREPROCESS_SCHEMA_VERSION`。把这些知识集中在同一变更中，才能保持 locality；在调用方增加兼容 adapter 或 fallback 只会扩大 interface 并降低 module depth。
