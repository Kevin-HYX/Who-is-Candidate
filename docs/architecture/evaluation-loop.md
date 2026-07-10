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

## Test Sample 生命周期

1. **Create**：以唯一 `sample_id`、样本大小、可选 Sample Seed 和显式 preprocess Prompt Artifact 创建；module 抽样后按原始 source row 排序，保存 seed、Raw Profile Hash 与 `prompt_snapshot/preprosess.md`。
2. **Build**：可以只运行 Preprocess、只运行 Build Index，或按顺序运行两者。Test Sample 通过独立 Build Workspace 复用生产 module implementation。
3. **Cache**：默认跳过 prerequisites 未变化且已成功的生成项；`discard_cache` 显式要求重新生成。
4. **Resample**：替换候选 cohort，保留既有 preprocess snapshot，但删除全部预处理、embedding、错误和 status artifact，使 build 状态回到 missing。
5. **Ready**：Retrieval Trial 要求 `preprocess_status == full` 且 `index_status == full`；partial Test Sample 必须先在自身 seam 调试，不能由 Trial 自动补建或 fallback 到生产索引。

Test Sample artifact 包括 `sample.json`、`sample_index.json`、`raw_profiles.jsonl`、prompt snapshot，以及构建后产生的 `preprocessed_profiles.jsonl`、`embeddings.jsonl`、`status.json` 和最新错误 JSONL。

## User Prompt Set 生命周期

1. **Create**：从非空、`prompt_id` 唯一的 User Prompt JSONL 创建唯一 `set_id`；同时复制 `prompt_snapshot/query.md`，并保存当时的 `tool_schema.json`。
2. **Map**：对每个 User Prompt 生成 QueryPlan，再通过生产检索 schema seam 校验。成功项写入 `generated_query_plans.jsonl`，失败项写入最新 `mapping_errors.jsonl`。
3. **Generation Cache**：仅当 User Prompt、Query Guide Snapshot、tool schema、模型配置四类 hash 全部匹配时复用成功输出；`discard_cache` 可显式放弃复用。
4. **Status**：全部 prompt 成功才是 `ready`；部分成功为 `partial`。partial 的成功与错误 artifact 仍可 Browse，但不能进入 Retrieval Trial。

Prompt Mapping 与 Test Sample 相互独立。修改 query prompt 不应重建候选 embedding；修改 sample preprocess snapshot 也不应重做 QueryPlan 映射，这种 seam 分离减少无关重算并提高调试 locality。

## Retrieval Trial 生命周期

1. **Prerequisites**：引用一个 full Test Sample 和一个 mapping `ready` 的 User Prompt Set；无效 prerequisite 直接失败。
2. **Run**：为每条已验证 mapping 调用同一 [`search_candidates`](../../src/retrieval.py) implementation，当前 Trial implementation 显式把 `top_k` 固定为 `10`。
3. **Persist**：成功结果写入 `search_results.jsonl`；逐 prompt 失败写入 `retrieval_errors.jsonl`；`status.json` 记录引用对象、成功数、错误数与 `complete` / `partial`。
4. **Identity**：`trial_id` 不可覆盖。要比较新的 snapshot 或 artifact，应创建新的 Retrieval Trial，保留旧 trial 作为可审计记录。

Retrieval Trial 不负责修复 Test Sample 或 Prompt Mapping。错误留在其真正发生的 module seam，避免一个总控流程用 fallback 隐藏上游问题。

## Browse Page 生命周期

Evaluation Object Browse Interface 提供 `list`、读取 metadata/status，以及对 JSONL artifact 的分页读取；CLI adapter 定义在 [`src/main.py`](../../src/main.py)。

- Page 使用 `offset` 与 `limit`；默认 `limit=20`，最大 `200`。
- 返回 envelope 包含 object 类型与 ID、artifact 名、artifact 状态、总数、分页位置、返回数和 `items`。
- artifact 尚未产生时返回 `artifact_status=missing` 与空 items；这表示明确的生命周期状态，不是从其它 artifact 获取数据的 fallback。
- artifact 存在但 JSON/JSONL 损坏时返回 `ARTIFACT_READ_FAILED`，不得当成 missing。
- Browse 只读，不修改 snapshot、cache 或 object 状态。

## Snapshot 与失效规则

Snapshot 是生成发生前复制进去的不可变输入证据：Test Sample 使用 `prompt_snapshot/preprosess.md`，User Prompt Set 使用 `prompt_snapshot/query.md`。后续修改 `test/data/prompts` 下的 Prompt Artifact 不会追溯改变已创建对象。

更换 Test Sample cohort 或 preprocess snapshot 必须使该 sample 的预处理与 embedding artifact 全部失效；更换 User Prompt、query snapshot、tool schema 或模型配置必须使对应 Prompt Mapping cache 失效。当前可执行的 snapshot、hash 和 readiness 判定以 [`src/evaluation.py`](../../src/evaluation.py) 为准；领域对象名称与禁止混用关系以 [`CONTEXT.md`](../../CONTEXT.md) 为准。
