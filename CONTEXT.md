# Candidate Search

This context defines the domain language for the candidate search tool and its MCP/CLI boundary.

## Language

**Candidate Search Tool**:
The deterministic retrieval component that validates a QueryPlan, filters candidates, ranks survivors, and returns SearchResult data.
_Avoid_: Agent, recommender, parser

**MCP Query Surface**:
The MCP server interface for read-only candidate search operations. It can validate QueryPlans, search candidates, and expose static resources, but it must not preprocess profiles or build indexes.
_Avoid_: MCP builder, indexing server

**CLI Build Surface**:
The command-line interface for state-changing build operations such as preprocessing profiles and building the local search index.
_Avoid_: MCP build tool, background auto-build

**Local Config File**:
The required local, non-committed configuration file used by the local process at startup or CLI execution time to load model provider settings, API keys, model names, and filesystem paths.
_Avoid_: environment-only config, committed secret file, MCP-visible config

**Preprocess**:
The one-time build step that converts raw candidate profiles into preprocessed profiles with hard fields, search texts, derived fields, and evidence.
_Avoid_: parse query, search

**Preprocessed Profile**:
The structured profile produced by Preprocess from one raw candidate profile, containing search-ready fields and evidence for later retrieval.
_Avoid_: enhanced profile, enriched profile

**Build Index**:
The CLI build step that prepares all files needed for retrieval from preprocessed profiles, including embeddings and local index/cache files.
_Avoid_: embed only, runtime fallback

**In-Memory Brute-Force Retrieval**:
The retrieval strategy that embeds query soft-preference texts at search time, loads candidate embeddings from local files, and computes similarity against all indexed candidates in memory.
_Avoid_: vector database, ANN service, external retrieval service

**Versioned Build Cache**:
The file-based build cache produced by Preprocess and Build Index, valid only for the preprocess schema version and embedding index version that created it.
_Avoid_: timeless cache, fallback cache

**Raw Profile Hash**:
The content hash of a raw candidate profile, used to detect when a candidate must be preprocessed again even if the preprocess schema version did not change.
_Avoid_: version, row checksum

**Search Text Hash**:
The content hash of the embedding input texts for a candidate, used to detect when embeddings must be rebuilt even if the embedding index version did not change.
_Avoid_: vector id, profile hash

**Preprocess Schema Version**:
The version that invalidates preprocessed profile cache when the preprocess output structure or prompt semantics change.
_Avoid_: enhancement version, profile version

**Embedding Index Version**:
The version that invalidates embedding and index cache when the embedding model, embedding input construction, vector shape, or index format changes.
_Avoid_: vector version only, cache version

**Merge Write**:
The build behavior that updates cache entries for a selected source range while keeping compatible existing cache entries.
_Avoid_: overwrite-only build, append-only build

**Candidate ID**:
The `user_id` from the raw profile. It is present and unique in the current dataset and is the primary key for cache merge writes.
_Avoid_: source row id, array index

**Source Row Index**:
The zero-based row position of a candidate in the raw JSONL file. It is used for range builds and debugging, not as candidate identity.
_Avoid_: candidate id

**QueryPlan**:
The structured JSON request written by the Agent and executed by the Candidate Search Tool.
_Avoid_: natural-language query, prompt

**Soft Preference**:
A weighted ranking preference that compares candidates after hard filtering. Every valid QueryPlan must contain at least one Soft Preference.
_Avoid_: optional sorter, empty preference

**SearchResult**:
The structured JSON response containing search metadata, ranked result rows, soft preference scores, and raw candidate profiles.
_Avoid_: recommendation, explanation

**Hard Filter Status**:
The per-result status describing whether hard constraints were fully passed or whether the candidate was kept because some hard-constraint fields had insufficient evidence.
_Avoid_: hard score, hard explanation

**Absent Evidence**:
The absence of an explicit field or signal in a raw profile. It cannot prove that a candidate lacks an attribute; it means the attribute is unknown unless another explicit source states the negative.
_Avoid_: negative evidence, failed condition

**Official Classification**:
The canonical top-level LinkedIn classification vocabulary used by Preprocess for role families and industries. Preprocess must output only these canonical labels for hard-filterable classification fields, not source-specific child categories or free-text labels. A non-canonical classification label is a Preprocess parse error, not something Search maps later.
_Avoid_: sample-only enum, raw source label, free-text category

**Classification Absence State**:
The only allowed non-classification values for Official Classification fields: `unknown`, `not_provided`, or `insufficient_evidence`.
_Avoid_: child category, translated label, typo, free-text fallback

**Index Status**:
The read-only MCP resource that reports current raw data, preprocessed profile, embedding, and index coverage so the Agent can understand whether search is ready, partial, or missing.
_Avoid_: data completeness tool, build trigger

**Top K**:
The requested result count that the system makes a best effort to stay within. It is not a hard cap because candidates sharing the boundary rank must be returned together.
_Avoid_: max returned, hard limit

**Test Sample**:
A managed sampled candidate cohort for prompt-loop evaluation. The controlling Agent can create it, replace its sampled candidates, configure its preprocessing prompt snapshot, and ask the system to produce preprocessed profiles and embeddings for that sample.
_Avoid_: evaluation environment, query set, retrieval trial

**Sample Seed**:
The random seed used to choose the candidate cohort for a Test Sample. It may be supplied by the operator or generated by the CLI, but it must be stored so the cohort can be audited or reproduced.
_Avoid_: hidden randomness, unrecoverable sample choice

**User Prompt**:
A natural-language hiring need prompt authored by the controlling Agent or human for evaluation. It is managed independently from Test Samples.
_Avoid_: QueryPlan, search result, raw candidate sample

**User Prompt Set**:
A managed collection of User Prompts and their Prompt Mapping outputs. It must be debugged independently before it can be used in a Retrieval Trial.
_Avoid_: test sample, retrieval trial, candidate cohort

**Prompt Mapping**:
The QueryPlan generation result produced from User Prompts using a configured Query Guide Snapshot and tool schema. It belongs with the User Prompts it maps so raw prompts, generated QueryPlans, and mapping errors can be reviewed together.
_Avoid_: raw user request, retrieval result, explanation

**Prompt Mapping Status**:
The readiness state of a User Prompt Set after mapping. Mapping may partially succeed and still expose successful QueryPlans and precise errors, but only an all-success mapping is ready for Retrieval Trial.
_Avoid_: retrieval status, hidden failed prompts, all-or-nothing output

**Generation Cache**:
The reusable successful output of an LLM-generating stage when its prerequisites have not changed. By default the system skips already successful items, while the controlling Agent can explicitly discard cached outputs and force regeneration.
_Avoid_: silent fallback, immutable output, hidden retry state

**Retrieval Trial**:
The retrieval execution for a valid Prompt Mapping against a ready Test Sample. It refuses to run when the Test Sample or User Prompt Set is invalid, because those errors belong to their own debugging stages.
_Avoid_: preprocessing output, prompt snapshot, natural-language need

**Evaluation Loop**:
The CLI-controlled prompt-tuning workflow that combines Test Samples, User Prompt Sets, Prompt Mapping, Retrieval Trials, and Browse Pages so the controlling Agent and human can iteratively evaluate prompt changes.
_Avoid_: test environment, production search, MCP query surface

**Evaluation Object Browse Interface**:
A read-only CLI interface that lists and reads Test Samples, User Prompt Sets, and Retrieval Trials so the controlling Agent can inspect prompt-loop artifacts without treating reusable prompt files as managed CLI objects.
_Avoid_: prompt registry, prompt editor, write interface

**Browse Page**:
A bounded slice returned by an Evaluation Object Browse Interface, using `offset` and `limit` so the controlling Agent can inspect large JSONL artifacts without loading the entire artifact into context.
_Avoid_: full dump, hidden truncation, unbounded read

**Test Sample Build Mode**:
The way a Test Sample produces build artifacts. It may run preprocessing alone, embedding/index building alone, or both steps together while preserving those phases as separately inspectable outputs.
_Avoid_: retrieval trial, hidden build phase, automatic fallback build

**Evaluation Data Root**:
The local test-loop storage root at `test/data`, resolved next to the active config file. It separates prompt-loop artifacts from production `data/processed` cache and contains `samples`, `user_prompt_sets`, `retrieval_trials`, and reusable evaluation prompts.
_Avoid_: production processed cache, single test environment, hidden temp directory

**Build Workspace**:
The explicit file workspace used by build and retrieval code, consisting of a raw profile JSONL path and an artifact directory. Production uses the default workspace from local config; Test Samples use their own sample directory under the Evaluation Data Root instead of pretending to be a Runtime Config.
_Avoid_: fake runtime config, implicit output directory, shared test/prod cache

**Prompt Artifact**:
A reusable evaluation prompt Markdown file under `test/data/prompts`, managed directly by the controlling Agent. Only preprocess and query prompts belong here; MCP guide text is not part of this evaluation prompt artifact store. Prompt versions are expressed through file naming rather than through a separate prompt registry.
_Avoid_: database prompt version, hidden latest prompt, runtime-generated prompt, mcp-guide copy

**Prompt Snapshot**:
The exact prompt artifact copied into a sample or user prompt set before generation. Samples snapshot `preprosess.md`; User Prompt Sets snapshot `query.md`.
_Avoid_: latest prompt by reference, hidden system prompt

**Query Guide Snapshot**:
The copied `query.md` prompt artifact that teaches an Agent or LLM how to convert User Prompts into QueryPlan JSON for evaluation.
_Avoid_: MCP help text, raw tool schema only, mutable latest prompt

**MCP Guide Markdown**:
The first source Markdown file for the MCP `candidate://help` resource. It contains stable tool-usage rules and examples, while dynamic runtime state is queried through status resources instead of being embedded in the help text.
_Avoid_: hard-coded help, runtime status document, generated search result

**Query Guide Markdown**:
The second source Markdown file for the MCP `candidate://help` resource and the standalone prompt file for generating QuerySchema or QueryPlan JSON from User Prompts during evaluation. It is separate from MCP Guide Markdown so this isolated generation step can be debugged without a complete Agent runtime.
_Avoid_: MCP help text, runtime status document, generated search result

**Preprocess Prompt Snapshot**:
The explicit external preprocess prompt file copied into a Test Sample before preprocessing. Test Sample builds use this copied snapshot, not the project prompt path by reference.
_Avoid_: implicit latest prompt, mutable prompt reference

**Test Sample Build Invalidation**:
The rule that changing either the sampled candidate cohort or the Preprocess Prompt Snapshot invalidates all preprocessing and embedding artifacts for that Test Sample.
_Avoid_: partial reuse after prompt change, stale embeddings
