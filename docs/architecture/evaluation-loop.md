# Evaluation Loop module

Evaluation Loop 是 CLI 控制的 prompt 调优 module。它把 Test Sample、User Prompt Set、Retrieval Trial 和 Browse Page 分成独立生命周期，使采样/预处理、QueryPlan 生成、检索结果能在各自 seam 调试。生产检索 implementation 被复用，但 Evaluation Data Root 与生产 `data/processed` 隔离，从而同时获得 leverage 与 locality。

## 根目录与对象关系

Evaluation Data Root 固定解析为活动配置文件旁的 `test/data`，implementation 位于 [`src/evaluation.py`](../../src/evaluation.py)。

```text
test/data/
  prompts/                     # 可复用 Prompt Artifact，文件名表达版本
  samples/<sample_id>/         # Test Sample + Preprocess/Index artifact
  user_prompt_sets/<set_id>/   # User Prompt + Prompt Mapping artifact
  retrieval_trials/<trial_id>/ # SearchResult / retrieval error artifact
```

```text
Prompt Artifact(preprocess) -> snapshot -> Test Sample -> full build -----+
                                                                        |
User Prompt + Prompt Artifact(query) -> snapshot -> User Prompt Set     |
                                           -> Prompt Mapping ready -----+-> Retrieval Trial
                                                                                -> Browse Page
```

Prompt Artifact 是控制 Agent 直接管理的 Markdown 文件，不是 CLI 托管对象；Browse interface 只读取三个 managed object 及其 artifact。

三个 managed object 都遵循同一持久化边界：身份、输入快照、生成结果、精确错误、版本和 hash 落盘；readiness、覆盖率和统计在读取时从这些事实实时计算。Evaluation Loop 不维护需要与 artifact 同步的动态状态文件。

## Test Sample 生命周期

1. **Create**：以唯一 `sample_id`、样本大小、可选 Sample Seed 和显式 preprocess Prompt Artifact 创建；`sample.json` 只保存 `sample_id`、`sample_size`、seed、创建时间等身份与溯源事实。module 抽样后按原始 source row 排序，把候选集合与 Raw Profile Hash 写入 `sample_index.json`，并保存 `raw_profiles.jsonl` 与 `prompt_snapshot/preprosess.md`。
2. **Build**：可以只运行 Preprocess、只运行 Build Index，或按顺序运行两者。Test Sample 通过独立 Build Workspace 复用生产 module implementation。
3. **Cache**：默认跳过 prerequisites 未变化且已成功的生成项；`discard_cache` 显式要求重新生成。
4. **Resample**：替换候选 cohort，保留既有 preprocess snapshot，但删除全部预处理、embedding 和错误 artifact；实时状态视图随后自然回到 `missing`，不需要同步另一份状态。
5. **Ready**：共享 Live Status Projection 根据 sample 的 Raw、Preprocessed、Embedding、Error artifact、当前版本与 hash 计算 `preprocess_status` 和 `index_status`。Retrieval Trial 要求两者均为 `full`；partial Test Sample 必须先在自身 seam 调试，不能由 Trial 自动补建或 fallback 到生产索引。

Test Sample artifact 包括身份与溯源文件 `sample.json`、候选集合 `sample_index.json`、`raw_profiles.jsonl`、prompt snapshot，以及构建后产生的 `preprocessed_profiles.jsonl`、`embeddings.jsonl`、`preprocess_errors.jsonl` 和 `index_errors.jsonl`。`sample.json` 不保存 build status、覆盖率或计数。

## User Prompt Set 生命周期

1. **Create**：从非空、`prompt_id` 唯一的 User Prompt JSONL 创建唯一 `set_id`；`prompt_set.json` 只保存对象 ID、创建时间和输入溯源等不可变事实，同时复制 `prompt_snapshot/query.md`，并保存当时的 `tool_schema.json`。
2. **Map**：对每个 User Prompt 生成 QueryPlan，再通过生产检索 schema seam 校验。模型连接、超时、限流和服务端错误最多串行尝试三次；已经收到但不符合 Query schema 的输出不重试。成功项写入 `generated_query_plans.jsonl`，失败项写入最新 `mapping_errors.jsonl`，传输失败与 schema 失败使用不同错误代码。
3. **Generation Cache**：仅当 User Prompt、Query Guide Snapshot、tool schema、模型配置和 Query Schema Version 全部匹配，且缓存 Mapping 仍通过当前生产校验时复用；`discard_cache` 可显式放弃复用。
4. **Status**：`mapping_status`、mapped/failed 数量和 schema stale 状态在读取时根据 `prompt_set.json`、User Prompt、Prompt/Schema snapshot、生成结果、错误、当前版本与 hash 计算。只有全部 prompt 都有当前合法 QueryPlan 且无错误时才是 `ready`；partial 的成功与错误 artifact 仍可 Browse，但不能进入 Retrieval Trial。Trial 启动前使用同一计算 seam 再次复核所有前置 hash、ID 集合和 QueryPlan。

`generated_count` 和 `skipped_count` 只描述一次 `user-prompt-set-map` CLI 运行，不长期持久化，也不参与对象 readiness 的事实来源。

Prompt Mapping 与 Test Sample 相互独立。修改 query prompt 不应重建候选 embedding；修改 sample preprocess snapshot 也不应重做 QueryPlan 映射，这种 seam 分离减少无关重算并提高调试 locality。

## Retrieval Trial 生命周期

1. **Prerequisites**：引用一个 full Test Sample 和一个 mapping `ready` 的 User Prompt Set；无效 prerequisite 直接失败。
2. **Snapshot and Run**：先把实际使用的 Test Sample 与 User Prompt Set 全部复制到 Trial 的 `input_snapshot/`，然后只从该快照执行 [`search_candidates`](../../src/retrieval.py)；`top_k` 固定为 `10`。查询 embedding 串行执行，不使用线程池；模型传输错误最多尝试三次。
3. **Persist**：`trial.json` 只保存 `trial_id`、引用对象、创建时间、输入快照 hash、Schema/模型/Retrieval Version 和预期查询数等不可变溯源事实。成功结果同时保存 QueryPlan、effective options、查询向量和 SearchResult；逐 prompt 失败写入 `retrieval_errors.jsonl`。
4. **Identity**：`trial_id` 不可覆盖。要比较新的 snapshot 或 artifact，应创建新的 Retrieval Trial，保留旧 trial 作为可审计记录。

Trial 先写入同目录临时目录，全部快照、`trial.json`、结果和错误事实成功落盘后再原子发布为 `trial_id`；失败不会留下占用该 ID 的半成品目录。`trial_status`、`search_count`、`error_count` 和覆盖情况由 `trial.json`、结果与错误 artifact 实时计算。保存的查询向量允许在相同 Retrieval Version 下离线重放，而无需再次调用 embedding API。

Retrieval Trial 不负责修复 Test Sample 或 Prompt Mapping。错误留在其真正发生的 module seam，避免一个总控流程用 fallback 隐藏上游问题。

## Browse Page 生命周期

Evaluation Object Browse Interface 提供 `list`、读取 identity metadata 与实时状态视图，以及对 JSONL artifact 的分页读取；CLI adapter 定义在 [`src/main.py`](../../src/main.py)。Browse、Search readiness 和 Retrieval Trial prerequisites 复用同一状态计算实现，不维护入口专属判断。

- Page 使用 `offset` 与 `limit`；默认 `limit=20`，最大 `200`。
- 返回 envelope 包含 object 类型与 ID、artifact 名、artifact 状态、总数、分页位置、返回数和 `items`。
- artifact 尚未产生时返回 `artifact_status=missing` 与空 items；这表示明确的生命周期状态，不是从其它 artifact 获取数据的 fallback。
- artifact 存在但 JSON/JSONL 损坏时返回 `ARTIFACT_READ_FAILED`，不得当成 missing。
- Browse 只读，不修改 snapshot、cache 或 object artifact；其状态与统计来自读取时计算。

## Snapshot 与失效规则

Snapshot 是生成发生前复制进去的不可变输入证据：Test Sample 使用 `prompt_snapshot/preprosess.md`，User Prompt Set 使用 `prompt_snapshot/query.md`。后续修改 `test/data/prompts` 下的 Prompt Artifact 不会追溯改变已创建对象。

更换 Test Sample cohort 或 preprocess snapshot 必须使该 sample 的预处理与 embedding artifact 全部失效；更换 User Prompt、query snapshot、tool schema 或模型配置必须使对应 Prompt Mapping cache 失效。当前可执行的 snapshot、hash 和 readiness 判定以 [`src/evaluation.py`](../../src/evaluation.py) 为准；领域对象名称与禁止混用关系以 [`CONTEXT.md`](../../CONTEXT.md) 为准。
