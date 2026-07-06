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

**Index Status**:
The read-only MCP resource that reports current raw data, preprocessed profile, embedding, and index coverage so the Agent can understand whether search is ready, partial, or missing.
_Avoid_: data completeness tool, build trigger

**Top K**:
The requested result count that the system makes a best effort to stay within. It is not a hard cap because candidates sharing the boundary rank must be returned together.
_Avoid_: max returned, hard limit
