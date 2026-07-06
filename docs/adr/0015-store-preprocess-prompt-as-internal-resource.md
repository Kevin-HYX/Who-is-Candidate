# Store preprocess prompt as an internal resource

The preprocess LLM prompt is stored in `prompts/preprocess_profile.md` instead of being embedded directly in Python code. This makes prompt changes reviewable and keeps the large prompt text out of implementation logic.

The prompt file is an internal implementation resource owned by `preprocess.py`; it is not part of the CLI or MCP interface. If prompt semantics change in a way that makes existing preprocessed profiles untrustworthy, `preprocess_schema_version` must be bumped so stale cache is discarded.

