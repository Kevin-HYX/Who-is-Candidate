# Use a local config file for runtime settings

CLI and local server startup settings come from a local TOML config file rather than environment variables alone. The default real config path is `candidate-search.toml` at the project root, and the committed template is `candidate-search.example.toml`. The config file is the primary place for DashScope API key, preprocessing model name, embedding model name, and filesystem paths.

TOML is used because the config is hand-edited and benefits from named sections such as provider, models, and paths. Python can read it with `tomllib` in supported runtimes.

The local config file must not be committed; `.gitignore` must ignore `candidate-search.toml`. Code defaults may still provide non-secret model defaults, but missing required config files or required secrets should produce a clear process-level configuration error instead of falling back silently.

CLI commands support `--config <path>` to override the default file. MCP tools and resources do not accept a config parameter and must not expose local config paths, API keys, model names, or other local environment details to Agents.

Missing config and missing index are separate failure domains. If the config file or required config values are missing, CLI commands fail directly and `serve-mcp` does not start. Required values are `dashscope.api_key`, `models.preprocess`, `models.embedding`, `paths.raw_profiles`, and `paths.processed_dir`; empty strings count as missing. `candidate://index-status` is reserved for raw/preprocessed/index coverage and does not report configuration availability.

Search also requires `dashscope.api_key` and `models.embedding`, because query soft-preference texts are embedded at request time even when candidate-side embeddings already exist.
