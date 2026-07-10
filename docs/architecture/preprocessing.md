# Preprocess module

Preprocess module 将一个 Raw Profile 转换为一个带证据、可缓存、可构建索引的 Preprocessed Profile。其外部 seam 是 CLI Build Surface；内部以模型调用 adapter 处理必须推断的内容，以确定性代码处理公式字段。这样调用方只学习一个构建 interface，推断、公式、重试与 Merge Write 都留在 module implementation 内，形成 leverage 与 locality。

## Interface 与职责

当前可执行入口是 [`preprocess_profiles`](../../src/preprocess.py)，由 [`src/main.py`](../../src/main.py) 的 `preprocess` CLI adapter 调用。输入包括 Runtime Config，可选 Build Workspace、左闭右开的 source row 范围、并发度和显式 cache 丢弃开关；输出是处理、跳过、失败数量与最新 status。

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
- `is_currently_working`：优先读取布尔 `is_working`；否则判断是否存在 `experience[].is_current == true`。

implementation 还会把 `current_role_tenure_months` 与 `avg_tenure_months` 写入 `derived_fields`。它们是代码公式派生字段，不计入七个硬字段。

## Preprocessed Profile 的最小可执行契约

当前 implementation 在写 cache 前至少验证：

- `hard_fields` 是对象，且包含上述七个对象字段；
- `embedding_search_texts` 是对象，且包含七个非空检索文本；维度白名单由 [`src/constants.py`](../../src/constants.py) 定义；
- 推断结果必须遵守“缺失不是否定”：无法举证时使用 `unknown`、`not_provided` 或 `insufficient_evidence`，不得通过 fallback 编造事实。

每条成功 cache record 的 envelope 包含 `user_id`、`source_row_index`、`raw_profile_hash`、`preprocess_schema_version` 与 `preprocessed_profile`。字段校验与 record 形状以 [`src/preprocess.py`](../../src/preprocess.py) 为准；Versioned Build Cache 与 Raw Profile Hash 规则由 [ADR-0002](../adr/0002-versioned-merge-write-build-cache.md) 固化。

## Prompt seam

项目内生产 prompt 是 [`prompts/preprosess.md`](../../prompts/preprosess.md)。它是 Preprocess implementation 的内部资源，不是 CLI 或 MCP interface；这一决定见 [ADR-0015](../adr/0015-store-preprocess-prompt-as-internal-resource.md)。

Evaluation Loop 必须把显式 Prompt Artifact 复制为 Test Sample 的 `prompt_snapshot/preprosess.md`，再把 snapshot 路径注入同一个 Preprocess interface。生产构建和评测构建因此共用 implementation，但 prompt snapshot 的生命周期互不污染。

## Cache、失败与重试

- 未显式丢弃 cache 时，`preprocess_schema_version` 与 `raw_profile_hash` 均匹配的候选人会被跳过。
- 每个待处理候选人独立尝试最多三次；初次与重试共享命令级并发上限。
- 成功项按 `user_id` Merge Write，并按 source row 顺序重写 JSONL；不使用 append-only 重复记录。
- 最终失败写入最新的 `preprocess_errors.jsonl`；成功项仍落盘，但命令以 `PREPROCESS_FAILED` 失败退出。全成功会删除旧错误 artifact。
- module 每次写入后更新 `status.json`。不允许静默降级为旧版本 cache，也不允许把 LLM 失败伪装成成功。

## 维护 seam

修改推断语义或输出结构时，应同时核对 executable prompt、`_merge_formula_fields`、`_validate_preprocessed_profile`、下游 [`retrieval.md`](./retrieval.md) 与 `PREPROCESS_SCHEMA_VERSION`。把这些知识集中在同一变更中，才能保持 locality；在调用方增加兼容 adapter 或 fallback 只会扩大 interface 并降低 module depth。
