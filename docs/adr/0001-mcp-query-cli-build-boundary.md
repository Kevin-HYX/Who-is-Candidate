# Keep MCP read-only and run build steps through CLI

The candidate search system separates read-only query operations from state-changing build operations. MCP exposes query tools and static resources only, while CLI commands perform preprocessing and build-index work. This prevents Agents from accidentally triggering expensive API calls or cache writes during normal conversations, while still allowing local operators to rebuild the index explicitly.

