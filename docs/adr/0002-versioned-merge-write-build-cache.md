# Use versioned merge-write build caches

Preprocess and Build Index support range-based runs that merge compatible results into local cache files instead of always overwriting the whole cache. Cache files are tied to `preprocess_schema_version` and `embedding_index_version`; when `preprocess_schema_version` changes, preprocessed profiles and downstream embeddings are discarded, and when only `embedding_index_version` changes, only embeddings and index files are discarded. Cache entries also record `raw_profile_hash` and `search_text_hash`, so changed source profiles or embedding inputs are rebuilt even when versions stay the same. Merge writes are implemented by reading the existing JSONL into a `user_id` keyed map, replacing affected candidates, and rewriting the JSONL file in source-row order; append-only duplicate records are not used. This keeps small range debugging practical without allowing stale preprocessed profiles or embeddings to survive incompatible model-contract changes.

Preprocess retries each candidate independently up to three times when the LLM output is invalid JSON, violates schema, uses invalid enum values, omits required fields, or lacks required evidence. Successful candidate results are still merged into the cache, but candidates that fail all retries are recorded in `data/processed/preprocess_errors.jsonl` and the CLI exits with failure so the run is visible and can be retried. The error log stores only the latest run: a successful run removes the old error log.

Build Index follows the same retry and visibility rule for embedding calls: each candidate or search text is retried independently up to three times, successful embeddings are merged into the cache, failed embedding records are written to `data/processed/index_errors.jsonl`, and the CLI exits with failure. Search and MCP use only successfully indexed candidates.

系统不为 Preprocess 或 Build Index 维护动态状态文件。持久化边界只包含 Raw 输入、成功的 Preprocessed/Embedding 记录、生成 identity、版本、hash 和精确错误；Agent-facing 状态是读取时从这些事实计算出的投影视图，只暴露真实可用的 `missing`、`partial`、`full` 与覆盖 metadata。

Preprocess and Build Index each own their own concurrency limit. Initial attempts and retries both count against the same command-level limit, with default concurrency of 3.

缓存 identity 还必须包含生成输入：预处理记录保存 Prompt 内容 hash 与 `{base_url, preprocess_model}` hash，embedding 记录保存 `{base_url, embedding_model}` hash。任一 identity 变化都会在调用模型前先移除受影响旧记录；因此显式丢弃缓存或重建失败后，旧成功结果不会继续被当作可用结果。OpenAI SDK 的内建重试被关闭，三次尝试只由本 module 的重试控制。

`index-status` 读取时复核当前版本、Prompt/模型 identity、Raw Profile Hash、Search Text Hash、实际 JSONL 覆盖和向量有限性，并实时计算计数、覆盖率、`source_ranges` 与 `next_actions`。CLI、MCP、Browse、Search readiness 和 Retrieval Trial prerequisites 必须复用这一计算 seam，禁止保存或同步另一份状态计数。
