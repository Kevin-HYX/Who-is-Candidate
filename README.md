# Candidate Search

Candidate Search 是一个本地运行的候选人检索工具。它把原始候选人 JSONL 预处理为可筛选结构，构建候选人侧向量，并通过 CLI 或只读 MCP 接口执行硬条件过滤、软偏好排序和原始履历回查。

系统刻意分开两类职责：

- CLI 通过 `preprocess`、`build-index` 写入本地事实 artifact，也提供搜索、状态查询和评测闭环命令。
- MCP 只提供 `search_candidates` 查询工具，以及 `candidate://help`、`candidate://index-status` 两个只读资源；不会自动预处理或建索引。

系统不持久化动态状态文件。Raw、Preprocessed、Embedding、Mapping、Result 和 Error artifact 连同版本与 hash 是事实来源；readiness、`missing` / `partial` / `full`、覆盖率、计数、`source_ranges` 和 `next_actions` 在读取时实时计算。CLI、MCP、Browse、Search readiness 与 Retrieval Trial 前置检查复用同一套状态计算，避免不同入口产生互相矛盾的判断。

检索结果是结构化数据，不是最终招聘结论。候选人事实应以结果中的 `raw_profile` 为准；分数只用于解释排序。

## 快速开始

项目要求 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item candidate-search.example.toml candidate-search.toml
```

编辑本地 `candidate-search.toml`，填写 OpenAI 兼容服务的 API Key、base URL 和模型名称。模板中的六个字段均为必填；当前模板使用 `qwen3.7-max` 预处理候选人，使用 `text-embedding-v4` 构建候选人向量和查询向量。本地配置可能包含密钥，不要提交。

构建本地数据：

```powershell
python -m src.main preprocess --concurrency 3
python -m src.main build-index --concurrency 3
python -m src.main index-status
```

准备 `query.json`：

```json
{
  "query_plan": {
    "hard_constraints": [],
    "weighted_soft_preferences": [
      {
        "dimension": "skills_search_text",
        "text": "Use Python to build data-processing and retrieval systems.",
        "weight": 1.0
      }
    ]
  },
  "options": {
    "top_k": 10
  }
}
```

执行搜索：

```powershell
python -m src.main search --query query.json
```

完整的参数、产物和评测命令见 [CLI 运行手册](docs/operations/cli.md)。QueryPlan 的字段约束和生成规则见 [Candidate Query Guide](prompts/query-guide.md)。

## MCP 用法

以 stdio 方式启动 MCP Server：

```powershell
python -m src.main serve-mcp
```

MCP 客户端应先读取 `candidate://index-status`，再按 `candidate://help` 构造并调用 `search_candidates`。`candidate://index-status` 是从当前 artifact、版本和 hash 实时计算的只读视图；配置路径只在启动进程时通过 `--config` 指定，不属于 MCP tool/resource 参数。

## 文档地图

- [CLI 运行手册](docs/operations/cli.md)：安装、配置、生产构建、查询、产物和评测闭环。
- [领域语言](CONTEXT.md)：项目中的统一术语及应避免的混用名称。
- [架构总览](docs/architecture/overview.md)：稳定 module、数据流、seam 与权威来源。
- [Preprocess 架构](docs/architecture/preprocessing.md)：LLM 推断、代码公式字段、缓存与 prompt seam。
- [检索架构](docs/architecture/retrieval.md)：硬筛、软排序、SearchResult 与错误语义。
- [评测闭环架构](docs/architecture/evaluation-loop.md)：Test Sample、User Prompt Set、Retrieval Trial 与 Browse 生命周期。
- [架构决策索引](docs/adr/README.md)：已生效架构决策及其原始记录。
- [MCP 使用指南](prompts/mcp-guide.md)：`candidate://help` 的稳定工具使用规则。
- [QueryPlan 生成指南](prompts/query-guide.md)：自然语言需求到 QueryPlan 的映射约束。
- [候选人数据结构报告](data/desensitization_profiles/structure_report.md)：原始数据字段、类型和覆盖情况。
