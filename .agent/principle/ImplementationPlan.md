# Implementation Plan — Candidate Search Tool

本文档记录候选人搜索系统的实现方案。对应设计见 [SystemDesign.md](./SystemDesign.md)、[ToolInterfaceDesign.md](./ToolInterfaceDesign.md)。

## 本期范围

- 优先构建 MCP Server，同时保留 CLI。
- 先完成 CLI 能力，再把查询能力封装成 MCP。
- CLI 负责状态改变：`preprocess`、`build-index`。
- MCP 只负责查询：一个工具 `search_candidates`，两个只读资源 `candidate://help` 和 `candidate://index-status`。
- Search Tool 返回简单检索元信息、软偏好分数和原始 profile；自然语言理解与候选人解释由未来 Agent 完成。

## 技术选型

- 语言：Python。
- 预处理：Qwen chat 模型，模型名必须由 `candidate-search.toml` 的 `models.preprocess` 提供；模板建议值为 `qwen-plus`。
- 向量化：Qwen embedding 模型，模型名必须由 `candidate-search.toml` 的 `models.embedding` 提供；模板建议值为 `text-embedding-v3`。
- 调用方式：使用 OpenAI 兼容 HTTP 接口，通过 `openai` Python SDK 调用；`base_url` 必须由本地配置显式提供，不做默认 endpoint 兜底。
- 配置：使用项目根目录的本地 TOML 配置文件 `candidate-search.toml` 保存 OpenAI 兼容 API Key、base_url、模型名和路径等运行参数；该文件不提交，提交 `candidate-search.example.toml` 作为填写模板。
- 本地缓存：文件制，按千级候选人规模设计，不引入数据库、向量数据库或 ANN 服务。

## 目录结构

减少文件数量，同一模块合并放在一个文件里：

```text
src/
  main.py          # CLI adapter + MCP server adapter
  evaluation.py    # Evaluation Loop：Test Sample、User Prompt Set、Retrieval Trial、Browse Page
  constants.py     # 硬筛白名单、枚举、搜索维度、版本号、配置字段名
  schemas.py       # QueryPlan、SearchResult、工具 schema、预处理结构、错误返回 schema
  preprocess.py    # 预处理：raw profile -> preprocessed profile
  retrieval.py     # embedding、索引构建、缓存加载、硬过滤、召回、排序

prompts/
  preprosess.md                 # 预处理 LLM prompt，属于 preprocess.py 的内部实现资源
  mcp-guide.md                  # MCP candidate://help 的第一段 Markdown 来源
  query-guide.md                # candidate://help 的第二段；离线调试 User Prompt -> QuerySchema/QueryPlan 的生成提示词

data/
  desensitization_profiles/
    1000_Desensitization_profiles.jsonl
  processed/
    preprocessed_profiles.jsonl
    embeddings.jsonl
    status.json
    preprocess_errors.jsonl
    index_errors.jsonl

test/
  data/
    prompts/
      preprocess_*.md             # Agent 自行管理版本命名的可复用预处理 prompt
      query_*.md                  # Agent 自行管理版本命名的可复用需求映射 prompt
    samples/
      <sample_id>/
        sample.json
        raw_profiles.jsonl
        sample_index.json
        prompt_snapshot/
          preprosess.md
        preprocessed_profiles.jsonl
        embeddings.jsonl
        status.json
        preprocess_errors.jsonl
        index_errors.jsonl
    user_prompt_sets/
      <set_id>/
        user_prompts.jsonl
        prompt_snapshot/
          query.md
        tool_schema.json
        generated_query_plans.jsonl
        mapping_errors.jsonl
        status.json
    retrieval_trials/
      <trial_id>/
        search_results.jsonl
        retrieval_errors.jsonl
        status.json

candidate-search.example.toml   # 可提交的本地配置模板
candidate-search.toml           # 本地真实配置，包含 API Key，必须被 .gitignore 忽略
requirements.txt                # 运行时依赖，包含 openai SDK
```

`evaluation.py`、`preprocess.py` 和 `retrieval.py` 可以各自接近 2000 行以内；不为了拆分而拆分。`main.py` 只作为 CLI/MCP adapter，不承载 Evaluation Loop 的实现细节。

## CLI 命令

```text
python -m src.main preprocess --start 0 --end 20 --concurrency 3
python -m src.main build-index --start 0 --end 20 --concurrency 3
python -m src.main search --query query.json --top-k 20 --json
python -m src.main serve-mcp
python -m src.main test-sample-create --sample-id sample_a --sample-size 50 --seed 123 --preprocess-prompt test/data/prompts/preprocess_v1.md --json
python -m src.main test-sample-preprocess --sample-id sample_a --json
python -m src.main test-sample-build-index --sample-id sample_a --json
python -m src.main test-sample-build --sample-id sample_a --json
python -m src.main test-sample-list --json
python -m src.main test-sample-read-raw --sample-id sample_a --limit 20 --offset 0 --json
python -m src.main test-sample-read-preprocessed --sample-id sample_a --limit 20 --offset 0 --json
python -m src.main test-sample-read-errors --sample-id sample_a --limit 20 --offset 0 --json
python -m src.main user-prompt-set-create --set-id set_a --user-prompts user_prompts.jsonl --query-prompt test/data/prompts/query_v1.md --json
python -m src.main user-prompt-set-map --set-id set_a --json
python -m src.main user-prompt-set-list --json
python -m src.main user-prompt-set-read-prompts --set-id set_a --limit 20 --offset 0 --json
python -m src.main user-prompt-set-read-mappings --set-id set_a --limit 20 --offset 0 --json
python -m src.main user-prompt-set-read-errors --set-id set_a --limit 20 --offset 0 --json
python -m src.main retrieval-trial-run --trial-id trial_a --sample-id sample_a --user-prompt-set-id set_a --json
python -m src.main retrieval-trial-list --json
python -m src.main retrieval-trial-read-results --trial-id trial_a --limit 20 --offset 0 --json
python -m src.main retrieval-trial-read-errors --trial-id trial_a --limit 20 --offset 0 --json
```

- `--start` / `--end` 使用原始 JSONL 的 0-based 左闭右开行号区间。
- `preprocess` 和 `build-index` 都支持区间运行。
- `build-index --start/--end` 也按原始行号选取对应的预处理记录；如果缺少预处理记录，报错，不自动预处理。
- CLI 命令支持 `--config <path>` 覆盖默认的 `candidate-search.toml`。`serve-mcp` 作为本地启动命令也通过 CLI 读取配置。
- 缺失配置文件或配置必填项时，CLI 命令直接失败；`serve-mcp` 不启动。配置缺失不是 `candidate://index-status` 的状态，也不作为 MCP tool/resource 的业务错误返回。
- `candidate-search.example.toml` 中的字段均为必填字段：`openai.api_key`、`openai.base_url`、`models.preprocess`、`models.embedding`、`paths.raw_profiles`、`paths.processed_dir`。空字符串按缺失处理。
- `search` 和 MCP `search_candidates` 也需要 `openai.api_key`、`openai.base_url` 与 `models.embedding`，因为查询侧 soft preference 文本要在检索时实时生成向量。
- CLI 构建命令默认输出人类可读摘要，支持 `--json`。
- CLI `search` 与 MCP `search_candidates` 使用同一套返回 schema。
- 评测闭环命令只属于 CLI，不暴露为 MCP build/query 资源。评测闭环产物固定存放在配置文件同目录的 `test/data/`，按 `samples/`、`user_prompt_sets/`、`retrieval_trials/`、`prompts/` 四个维度分开存储，并通过各自 id 切换版本。
- Test Sample 支持分步预处理、分步建索引和一键 build；User Prompt Set 支持单独调试 User Prompt 到 QuerySchema/QueryPlan 的映射；Retrieval Trial 只接受 ready 的 Test Sample 和 ready 的 User Prompt Set。
- 两个调用大模型 API 的生成阶段都使用 Generation Cache：Test Sample 预处理和 User Prompt Set 映射默认跳过前置条件未变的成功项，`--discard-cache` 可强制重跑。
- 构建和检索代码通过 Build Workspace 读取原始 JSONL 并写入产物目录。生产默认 Build Workspace 来自 `candidate-search.toml`；Test Sample 使用 `test/data/samples/<sample_id>/` 作为自己的 Build Workspace，不通过伪造或重定向 `RuntimeConfig` 来运行。
- `test/data/prompts/` 只放闭环调优用的可复用 preprocess/query prompt artifacts。创建 Sample 或 User Prompt Set 时，系统把指定 prompt 复制到对象内部 `prompt_snapshot/`，后续运行只读 snapshot。
- Evaluation Object Browse Interface 只读，不管理 `test/data/prompts/`。`list` 命令只列当前 `test/data` 下已有对象，目录不存在则返回空列表，并按 `updated_at` 倒序返回。
- `read-*` 命令统一返回分页 envelope：`object_type`、`object_id`、`artifact`、`artifact_status`、`total_count`、`offset`、`limit`、`returned_count`、`items`。默认 `limit=20`，最大 `limit=200`，`offset>=0`。
- 对象存在但 artifact 文件尚未生成时，`read-*` 返回 `artifact_status="missing"` 和空 `items`；对象 id 不存在、分页参数非法、artifact 文件损坏时返回结构化错误。
- `test-sample-read-errors` 聚合读取 `preprocess_errors.jsonl` 和 `index_errors.jsonl`，并在每条错误上增加 `error_source`。

## 缓存与版本

缓存以 `user_id` 为主键；当前原始数据必须每行都有唯一 `user_id`，否则构建时报错。

`preprocessed_profiles.jsonl` 每行：

```json
{
  "user_id": 218051274,
  "source_row_index": 0,
  "raw_profile_hash": "...",
  "preprocess_schema_version": "2026-07-06.1",
  "preprocessed_profile": {}
}
```

`embeddings.jsonl` 每行：

```json
{
  "user_id": 218051274,
  "source_row_index": 0,
  "embedding_index_version": "2026-07-06.1",
  "search_text_hash": "...",
  "vectors": {
    "responsibilities_search_text": [0.01, 0.02],
    "skills_search_text": [0.03, 0.04]
  }
}
```

`status.json` 是 MCP `candidate://index-status` 的状态来源。每次 `preprocess` 或 `build-index` 更新本地产物后同步更新。若 `status.json` 不存在，等价于没有建立预处理结构和索引；MCP 返回 `missing`。

缓存失效规则：

- `preprocess_schema_version` 变化：预处理结构失效，下游 embeddings/index 也失效。
- `embedding_index_version` 变化：embedding/index 失效，预处理结构仍可复用。
- `raw_profile_hash` 不一致：对应候选人的预处理结构失效，搜索返回 `RAW_PROFILE_HASH_MISMATCH`。
- `search_text_hash` 不一致：embedding 缓存失效，搜索返回 `SEARCH_TEXT_HASH_MISMATCH`。

原始 profile 单独存储在原始 JSONL 中，不写入 `preprocessed_profiles.jsonl`。搜索时按 `user_id` 回查原始 profile；如果找不到，返回 `RAW_PROFILE_NOT_FOUND`，不跳过、不兜底。

## 写入策略

预处理和索引都采用 merge write：

1. 读取已有 JSONL 到 `user_id` map。
2. 替换本次区间内成功构建的候选人。
3. 按 `source_row_index` 重写整个 JSONL 文件。
4. 不使用 append-only，避免同一 `user_id` 出现多个缓存版本。

不加跨进程文件锁。`preprocess` 和 `build-index` 只保证单个命令进程内的并发控制；不要同时启动多个构建命令写同一套 `data/processed/` 产物。

错误日志只保留最新一次运行：

- `preprocess_errors.jsonl`：预处理失败记录。
- `index_errors.jsonl`：embedding/index 失败记录。
- 如果本次命令无失败，删除旧错误日志。

MCP 的 `index-status` 只暴露可用状态和覆盖范围，不暴露具体失败详情。具体失败由 CLI 输出和错误日志承担。

## 预处理

预处理只做一次，由 CLI 显式触发，不由 MCP 自动触发。

核心规则：

- 预处理 prompt 放在 `prompts/preprosess.md`，不硬编码在 Python 中；它属于 `preprocess.py` 的内部实现资源，不暴露给 CLI/MCP 调用方。
- 如果 prompt 语义变化导致原有预处理缓存不再可信，必须升级 `preprocess_schema_version`。
- 能用公式算的字段不用 LLM 算，例如总经验年限、最高学历、当前任职时长、平均任职时长。
- LLM 只处理需要判断、归一、转写的字段，例如 `role_family`、`seniority_level`、`management_scope`、`industries`、检索文本、风险文本。
- 每个非公式、非 unknown 的推断字段必须带 `confidence`、`source_field`、`evidence`。
- 无证据只能标 `unknown` / `not_provided` / `insufficient_evidence`，不得把缺失当作否定。
- 输出结构必须通过 schema 校验。

失败与重试：

- 每个候选人独立重试最多 3 次。
- 重试原因包括：非法 JSON、schema 不合法、枚举非法、缺少 required 字段、缺少 required evidence。
- 重试使用同一 prompt 和同一模型参数，不把上一次错误原因塞回 prompt。
- 成功记录仍然 merge write。
- 多次重试仍失败的候选人写入 `preprocess_errors.jsonl`，CLI 最终以失败退出。
- 初试和重试都计入同一个 `--concurrency` 限制；默认并发 3。
- 不做跨进程锁；并发限制只约束当前命令进程内的模型调用。

## Build Index

`build-index` 基于已存在的预处理结构生成候选人侧 embeddings。

规则：

- 对每个候选人的 7 个 `*_search_text` 生成向量。
- 若请求区间内缺少预处理记录，报错，不自动预处理。
- 每条 embedding 记录保存 `search_text_hash`，用于检测预处理文本变化。
- 每个候选人或每段 search text 的 embedding 调用失败后最多重试 3 次。
- 成功记录 merge write；失败记录写入 `index_errors.jsonl`；有失败则 CLI 以失败退出。
- 初试和重试都计入同一个 `--concurrency` 限制；默认并发 3。
- 不做跨进程锁；并发限制只约束当前命令进程内的模型调用。

## Search

搜索阶段不使用线程池，不引入向量数据库或 ANN。

流程：

1. 读取 `status.json`。如果缺失，返回 `PREPROCESS_AND_INDEX_NOT_BUILT`。
2. 校验有可用预处理结构和索引。如果只有预处理结构没有索引，返回 `SEARCH_INDEX_NOT_BUILT`。
3. 读取原始 JSONL、预处理结构和 embeddings。
4. 校验 `user_id`、`raw_profile_hash`、`search_text_hash` 一致性。
5. 校验 QueryPlan：硬筛字段、字段操作符、软偏好维度、文本、weight、top_k。
6. 对每条 soft preference 的 `text` 生成查询向量。
7. 在内存中对所有已索引候选人做暴力相似度计算。
8. 第一轮硬过滤：明确违反者淘汰；证据不足者保留并在 `hard_filter_status.insufficient_evidence_fields` 标出。
9. 第二轮软打分：每个软项在幸存池内把 raw cosine 转成 percentile，输出 `score_before_weight`；再算 `score_after_weight = weight * score_before_weight`。
10. `final_score = sum(score_after_weight)`。
11. 按 `final_score` 降序排序；同分同 rank，采用竞赛排名。
12. 返回 top_k 附近结果；若边界同分，完整返回同 rank 候选人，不截断。

## MCP

MCP 第一版：

- Tool：`search_candidates`
- Resource：`candidate://help`
- Resource：`candidate://index-status`

`prompts/query-guide.md` 不作为单独 MCP resource 暴露。它用于闭环评测里单独调试 User Prompt 到 QuerySchema/QueryPlan 的生成效果，因为当前不能在完整 Agent 环境中直接测试这一环。
`candidate://help` 返回时先拼接 `prompts/mcp-guide.md`，再拼接 `prompts/query-guide.md`。

MCP 不提供：

- `preprocess`
- `build-index`
- `validate_query_plan`
- `config` 参数
- 自动建索引
- 自动修复缓存

MCP tool/resource schema 不暴露本地配置路径、API Key、模型名或其它本地环境信息。配置只在本地进程启动或 CLI 命令执行时读取。

如果本地配置文件缺失或配置必填项缺失，`serve-mcp` 启动失败，不进入 MCP 可服务状态。缺失索引才由 `candidate://index-status` 表达为 `missing`。

Agent 如果发现 `candidate://index-status` 是 `missing`，应提示用户使用 CLI 建立预处理结构和索引。状态是 `partial` 时可以搜索，但必须向用户说明结果来自部分索引，不代表全量候选库。

## 验证计划

- 全文检查可执行契约里不再保留旧的硬条件强弱标记、排序备注字段和同分分组字段。
- 检查 `weighted_soft_preferences` 为空会返回 `EMPTY_SOFT_PREFERENCES`。
- 检查 `top_k > 75` 返回 `TOP_K_TOO_LARGE`。
- 检查同分采用同 rank，且 top_k 边界同分不会被截断。
- 检查 `raw_profile` 来自原始 JSONL，不包含工具分数字段。
- 检查 `final_score = sum(score_after_weight)`。
- 检查缺失 `candidate-search.toml` 时 CLI 直接失败，`serve-mcp` 不启动。
- 检查配置必填字段缺失或为空时 CLI 直接失败，`serve-mcp` 不启动。
- 检查缺失 `status.json` 时 MCP index-status 报 `missing`，搜索报 `PREPROCESS_AND_INDEX_NOT_BUILT`。
- 检查本地 Markdown 链接可解析。
