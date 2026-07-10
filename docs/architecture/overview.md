# Candidate Search 架构总览

本文只描述稳定的 module、数据流与权威来源。领域术语以 [`CONTEXT.md`](../../CONTEXT.md) 为准；具体 interface 与 implementation 分别下沉到同目录专题文档和可执行代码，避免总览再次成为重复契约。

## Module 地图

| Module | 职责 | 主要 seam | Implementation |
|---|---|---|---|
| 配置 module | 从 Local Config File 装配模型与文件路径 | 本地进程启动 / CLI 执行 | [`src/schemas.py`](../../src/schemas.py) |
| Preprocess module | 将 Raw Profile 变成可检索的 Preprocessed Profile，并维护 Versioned Build Cache | CLI Build Surface | [`preprocessing.md`](./preprocessing.md)、[`src/preprocess.py`](../../src/preprocess.py) |
| Build Index module | 将七个检索文本写成候选人侧向量 artifact | CLI Build Surface | [`src/retrieval.py`](../../src/retrieval.py) |
| Live Status Projection | 从事实 artifact、当前版本与 hash 实时计算 readiness、覆盖率、计数和下一步动作 | CLI、MCP、Browse、Search readiness 与 Retrieval Trial prerequisites 共用 | [`src/retrieval.py`](../../src/retrieval.py)、[`src/evaluation.py`](../../src/evaluation.py) |
| Candidate Search Tool | 校验 QueryPlan、硬筛、软排序并返回 SearchResult | CLI `search` 与 MCP `search_candidates` adapter 共用的检索 interface | [`retrieval.md`](./retrieval.md)、[`src/retrieval.py`](../../src/retrieval.py) |
| MCP Query Surface | 暴露只读搜索与资源，不触发构建 | MCP adapter | [`src/main.py`](../../src/main.py) |
| Evaluation Loop | 管理 Test Sample、User Prompt Set、Retrieval Trial 与 Browse Page | CLI adapter | [`evaluation-loop.md`](./evaluation-loop.md)、[`src/evaluation.py`](../../src/evaluation.py) |

这些 seam 把 artifact 写入集中在 CLI Build Surface，把只读检索集中在 MCP Query Surface。状态本身不是另一套持久化数据，而是由共享 implementation 对现有事实 artifact 的实时投影；构建、检索和评测知识分别留在各自 module，保持 locality。

## 数据流

```text
Raw Profile JSONL
  -> Preprocess
  -> Preprocessed Profile cache
  -> Build Index
  -> candidate embedding cache
  -> Live Status Projection(artifact + version + hash)

User Prompt
  -> 调用方生成完整 QueryPlan
  -> Candidate Search Tool
  -> hard filter
  -> in-memory brute-force soft ranking
  -> SearchResult(raw_profile + ranking metadata)

Prompt Artifact + sampled Raw Profile + User Prompt Set
  -> Evaluation Loop snapshots
  -> Retrieval Trial
  -> paged Browse Page
```

生产 Build Workspace 与 Test Sample Build Workspace 复用同一 Preprocess、Build Index 和 Candidate Search Tool implementation，但拥有不同 artifact 根目录；Evaluation Loop 不伪造 Runtime Config。

## 状态模型

系统遵循“持久化事实和输入证据，实时计算状态和统计视图”：Raw、Preprocessed、Embedding、Mapping、Result、Error、Prompt Snapshot 和各类 hash/版本是可审计事实；readiness、`missing` / `partial` / `full`、覆盖率、计数、`source_ranges` 和 `next_actions` 都在读取时计算，不另行同步到动态状态文件。

生产 `index-status`、MCP `candidate://index-status`、Evaluation Browse、Search readiness 与 Retrieval Trial prerequisites 必须调用同一个状态计算 seam。任何入口都不能维护自己的计数副本、信任历史状态，或在 artifact 不完整时使用 fallback 推断为 ready。

## 权威来源

| 优先级 | 权威来源 | 决定什么 |
|---|---|---|
| 1 | [`CONTEXT.md`](../../CONTEXT.md) | 领域语言、对象名称与禁止混用的概念 |
| 2 | [`docs/adr/`](../adr/) | 已接受的架构决定；专题文档不得重新争论 |
| 3 | [`src/constants.py`](../../src/constants.py)、[`src/schemas.py`](../../src/schemas.py)、[`src/preprocess.py`](../../src/preprocess.py)、[`src/retrieval.py`](../../src/retrieval.py)、[`src/evaluation.py`](../../src/evaluation.py)、[`src/main.py`](../../src/main.py) | 当前可执行 interface、校验、状态与错误行为 |
| 4 | [`prompts/preprosess.md`](../../prompts/preprosess.md)、[`prompts/query-guide.md`](../../prompts/query-guide.md)、[`prompts/mcp-guide.md`](../../prompts/mcp-guide.md) | 当前可执行 prompt 与 MCP 帮助资源 |
| 5 | 本目录专题文档 | 对上述来源的架构解释，不覆盖机器契约 |

若代码、prompt、ADR 与专题文档不一致，应先按上表确认事实，再在对应 seam 一次性修正，避免通过 adapter 或 fallback 隐藏漂移。被本目录取代的规划稿仍可通过 Git 历史追溯，不在当前文档树保留第二份现状说明。
