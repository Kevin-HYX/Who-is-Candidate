# CLI 运行手册

本文档描述当前 `python -m src.main --help` 暴露的运行接口。命令参数以 CLI 的 `--help` 为最终准则，运行配置以仓库根目录的 `candidate-search.example.toml` 为模板。

## 安装与配置

项目要求 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item candidate-search.example.toml candidate-search.toml
```

配置文件包含以下必填项，空字符串也视为缺失：

| 配置项 | 用途 | 当前模板值 |
| --- | --- | --- |
| `openai.api_key` | OpenAI 兼容 API Key | 需要本地填写 |
| `openai.base_url` | OpenAI 兼容 endpoint | 需要本地填写 |
| `models.preprocess` | 候选人预处理模型 | `qwen3.7-max` |
| `models.embedding` | 建索引与查询向量模型 | `text-embedding-v4` |
| `paths.raw_profiles` | 原始候选人 JSONL | `data/desensitization_profiles/1000_Desensitization_profiles.jsonl` |
| `paths.processed_dir` | 生产构建产物目录 | `data/processed` |

默认读取项目根目录的 `candidate-search.toml`。所有子命令都可用 `--config <path>` 指定其他配置；相对配置路径按命令执行时的工作目录解析，配置内的相对数据路径按配置文件所在目录解析。配置文件或任一必填项缺失时命令直接失败，不会读取环境变量或其他 endpoint 作为兜底。

## 生产构建与查询

### 预处理

```powershell
python -m src.main preprocess --start 0 --end 20 --concurrency 3 --json
```

`--start` / `--end` 是原始 JSONL 的 0-based 左闭右开行号区间；省略时处理全量。`--concurrency` 默认是 `3`。`--discard-cache` 会先使目标旧记录及下游向量失效，再强制重跑。预处理调用配置中的 chat 模型并读取内部资源 `prompts/preprosess.md`。

### 构建索引

```powershell
python -m src.main build-index --start 0 --end 20 --concurrency 3 --json
```

区间语义与预处理一致，`--discard-cache` 会先移除目标旧向量再强制重建。请求区间缺少预处理记录时命令失败，不会自动执行预处理。不要同时启动多个构建命令写入同一个 `processed_dir`；项目不提供跨进程写锁。

预处理和建索引均采用 merge write：本次成功记录替换对应候选人的旧记录，兼容的其他候选人记录保留，最终按 `source_row_index` 重写文件。

### 查询状态与搜索

```powershell
python -m src.main index-status
python -m src.main search --query query.json --top-k 20
```

`index-status` 不读取持久化状态副本，而是根据当前 Raw、Preprocessed、Embedding、Error artifact、版本和 hash 实时计算 readiness、`missing` / `partial` / `full`、覆盖率、计数、`source_ranges` 与 `next_actions`。同一计算实现也供 MCP、Search readiness、Evaluation Browse 和 Retrieval Trial prerequisites 使用。

`search` 接受两种 JSON：直接的 QueryPlan，或包含 `query_plan` 与 `options` 的完整参数对象。`--top-k` 会覆盖文件中的 `options.top_k`。工具默认 `top_k=20`，最大为 `75`；边界候选人同 rank 时会完整返回同 rank 结果，因此实际返回数可能超过请求数。

每个 QueryPlan 必须至少包含一个 `weighted_soft_preferences` 项。完整 schema 和生成约束见 [`prompts/query-guide.md`](../../prompts/query-guide.md)。搜索会实时调用 embedding 模型生成查询向量，因此即使候选人索引已存在，仍需要有效的 API 配置。

### 启动 MCP

```powershell
python -m src.main serve-mcp
```

该命令启动 stdio MCP Server。输入输出采用 MCP 标准的 newline-delimited UTF-8 JSON-RPC，每条消息独占一行，并暴露：

- Tool：`search_candidates`
- Resource：`candidate://help`
- Resource：`candidate://index-status`

MCP 是只读查询面，不提供预处理、建索引、自动修复缓存或配置参数。缺少配置时 Server 不启动；缺少索引时通过 `candidate://index-status` 和搜索错误显式报告。

## 生产构建产物

产物写入 `paths.processed_dir`：

| 文件 | 内容 |
| --- | --- |
| `preprocessed_profiles.jsonl` | 预处理结构、源行号、原始 profile、Prompt、模型 hash 和 schema 版本 |
| `embeddings.jsonl` | 各检索文本向量、search text hash、embedding 模型 hash 和索引版本 |
| `preprocess_errors.jsonl` | 最近一次预处理运行的失败记录 |
| `index_errors.jsonl` | 最近一次建索引运行的失败记录 |

错误日志只保留最近一次运行的精确错误事实；本次无错误时会移除对应旧日志。系统不写动态状态文件，所有状态与统计都从上述事实 artifact 实时计算。原始 profile 不复制进预处理缓存，搜索时按 `user_id` 回查原始 JSONL。hash、版本或原始 profile 不一致时搜索显式报错，不跳过、不降级。

## 评测闭环

评测数据固定存放在活动配置文件同目录的 `test/data/`，不写入生产 `processed_dir`：

```text
test/data/
  prompts/             # 可复用的 preprocess/query prompt artifacts
  samples/             # sample.json、候选集合、prompt snapshot、构建产物和错误
  user_prompt_sets/    # prompt_set.json、User Prompt、QueryPlan 映射和映射错误
  retrieval_trials/    # trial.json、输入快照、检索结果和检索错误
```

### Test Sample

创建、重采样和查看对象：

```powershell
python -m src.main test-sample-create --sample-id sample_a --sample-size 50 --seed 123 --preprocess-prompt test/data/prompts/preprocess_baseline_20260710_01.md --json
python -m src.main test-sample-resample --sample-id sample_a --sample-size 50 --seed 456 --json
python -m src.main test-sample-show --sample-id sample_a --json
python -m src.main test-sample-list --json
```

分步或一键构建：

```powershell
python -m src.main test-sample-preprocess --sample-id sample_a --concurrency 3 --json
python -m src.main test-sample-build-index --sample-id sample_a --concurrency 3 --json
python -m src.main test-sample-build --sample-id sample_a --concurrency 3 --json
```

这三个构建命令都支持 `--discard-cache` 强制重跑。创建时指定的 preprocess prompt 会复制进 Sample 的 `prompt_snapshot/`；后续运行只读 snapshot。`sample.json` 只保存 `sample_id`、样本大小、seed、创建时间等身份与溯源事实，不保存动态 build status。重采样会使该 Sample 已有的预处理和索引产物失效，后续状态由剩余 artifact 自动计算为 `missing` 或 `partial`。

分页读取产物：

```powershell
python -m src.main test-sample-read-raw --sample-id sample_a --offset 0 --limit 20 --json
python -m src.main test-sample-read-preprocessed --sample-id sample_a --offset 0 --limit 20 --json
python -m src.main test-sample-read-errors --sample-id sample_a --offset 0 --limit 20 --json
```

### User Prompt Set

```powershell
python -m src.main user-prompt-set-create --set-id set_a --user-prompts user_prompts.jsonl --query-prompt test/data/prompts/query_baseline_20260710_01.md --json
python -m src.main user-prompt-set-map --set-id set_a --json
python -m src.main user-prompt-set-show --set-id set_a --json
python -m src.main user-prompt-set-list --json
```

`user-prompt-set-map` 支持 `--discard-cache`。创建时指定的 query prompt 会复制进 Prompt Set 的 `prompt_snapshot/`；`prompt_set.json` 只保存 ID、创建时间和输入溯源等不可变事实，映射阶段同时保存 tool schema、生成的 QueryPlan 和精确错误。`mapping_status`、mapped/failed 数量和 schema stale 状态实时计算；`generated_count`、`skipped_count` 只出现在本次 map 命令结果中，不长期持久化。

Prompt Mapping 对连接、超时、限流和服务端错误最多串行尝试三次；Query JSON 或 schema 非法时不重试。两类失败使用不同错误代码，避免把网络故障误报为 prompt 输出错误。

```powershell
python -m src.main user-prompt-set-read-prompts --set-id set_a --offset 0 --limit 20 --json
python -m src.main user-prompt-set-read-mappings --set-id set_a --offset 0 --limit 20 --json
python -m src.main user-prompt-set-read-errors --set-id set_a --offset 0 --limit 20 --json
```

### Retrieval Trial

只有 ready 的 Test Sample 和 ready 的 User Prompt Set 可用于 Retrieval Trial：

```powershell
python -m src.main retrieval-trial-run --trial-id trial_a --sample-id sample_a --user-prompt-set-id set_a --json
python -m src.main retrieval-trial-show --trial-id trial_a --json
python -m src.main retrieval-trial-list --json
python -m src.main retrieval-trial-read-results --trial-id trial_a --offset 0 --limit 20 --json
python -m src.main retrieval-trial-read-errors --trial-id trial_a --offset 0 --limit 20 --json
```

所有 `read-*` 命令默认 `limit=20`，最大 `limit=200`，并要求 `offset>=0`。对象存在但目标 artifact 尚未生成时，返回 `artifact_status="missing"` 和空 `items`；对象不存在、分页非法或 artifact 损坏时返回结构化错误。

每个 Trial 的 `input_snapshot/` 冻结实际使用的 Test Sample 和 User Prompt Set。`trial.json` 只保存 `trial_id`、引用对象、创建时间、逐文件/聚合输入 hash、Schema/模型/Retrieval Version 和预期查询数等不可变溯源；每条成功结果保存 QueryPlan、effective `top_k`、查询向量与 SearchResult，精确失败保存到 `retrieval_errors.jsonl`。`trial_status`、搜索/错误计数和覆盖情况在读取时从这些 artifact 实时计算。

Trial 的查询 embedding 串行执行；模型传输错误最多尝试三次，不引入额外召回线程池。

## 命令自检

查看全部子命令或单个命令参数：

```powershell
python -m src.main --help
python -m src.main <command> --help
```
