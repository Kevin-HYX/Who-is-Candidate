# Allow partial index search with explicit metadata

Search is allowed when the local index covers only part of the raw dataset, and the system does not add a `require_full_index` option. Instead, SearchResult metadata must report `index_status`, `total_raw_candidates`, `indexed_candidates`, and covered `source_ranges`, and the Agent must tell users when results come from a partial index. This keeps range-based debugging usable while preventing partial results from being presented as full-corpus search.

