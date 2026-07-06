# Query index status at runtime

The MCP usage guide should not hardcode detailed runtime coverage numbers. Agents must use the read-only `candidate://index-status` resource to inspect current raw data, preprocessed profile, embedding, and index coverage before assuming search is ready or full. This prevents stale guide text from diverging from the actual dataset or rebuilt local artifacts, while keeping runtime status separate from the query-writing guide.
