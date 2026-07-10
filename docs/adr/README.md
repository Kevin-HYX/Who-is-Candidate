# 架构决策索引

本目录保存 Candidate Search 已记录的架构决策。编号只表示记录顺序；需要理解背景、约束和后果时，应进入对应原文，不要只依赖本索引的标题。

1. [ADR-0001：MCP 保持只读，构建步骤通过 CLI 执行](0001-mcp-query-cli-build-boundary.md)
2. [ADR-0002：使用带版本的 merge-write 构建缓存](0002-versioned-merge-write-build-cache.md)
3. [ADR-0003：统一使用 Preprocessed Profile 术语](0003-use-preprocessed-profile-terminology.md)
4. [ADR-0004：允许部分索引搜索并显式返回元数据](0004-allow-partial-index-search-with-metadata.md)
5. [ADR-0005：将 top_k 视为尽力满足的结果数量](0005-top-k-is-a-best-effort-limit.md)
6. [ADR-0006：QueryPlan 至少需要一个软偏好](0006-require-at-least-one-soft-preference.md)
7. [ADR-0007：移除硬条件 strictness](0007-remove-hard-constraint-strictness.md)
8. [ADR-0008：从 Tool QueryPlan 移除 ranking preference](0008-remove-ranking-preference-from-tool-queryplan.md)
9. [ADR-0009：返回结构化 Hard Filter Status](0009-return-structured-hard-filter-status.md)
10. [ADR-0010：在运行时查询索引状态](0010-query-index-status-at-runtime.md)
11. [ADR-0011：缓存候选人必须存在对应 Raw Profile](0011-require-raw-profile-for-cached-candidates.md)
12. [ADR-0012：使用内存暴力检索候选人](0012-use-in-memory-brute-force-retrieval.md)
13. [ADR-0013：不增加跨进程构建锁](0013-do-not-add-cross-process-build-lock.md)
14. [ADR-0014：使用本地配置文件保存运行设置](0014-use-local-config-file.md)
15. [ADR-0015：将 prompt 文件作为内部资源](0015-store-preprocess-prompt-as-internal-resource.md)

运行入口见项目根目录的 [`README.md`](../../README.md)，CLI、配置和产物说明见 [`docs/operations/cli.md`](../operations/cli.md)。
