# Candidate Search Help

This MCP server provides read-only candidate search.

## Resources

- `candidate://help`: this help document.
- `candidate://index-status`: current preprocessing and index coverage.

Read `candidate://index-status` before assuming the index is available or full. If `index_status` is `partial`, tell the user results are from a partial index.

## Tool

Use `search_candidates` with a complete `query_plan`.

`query_plan` may only contain:

- `hard_constraints`
- `weighted_soft_preferences`

`options` may contain:

- `top_k`

## Hard Constraints

`hard_constraints` may only use these fields:

- `years_of_experience`
- `highest_degree_level`
- `role_family`
- `seniority_level`
- `management_scope`
- `industries`
- `is_currently_working`

Use hard constraints only when the user clearly states a must-have, exclusion, or numeric threshold. Do not hard-filter on certificates, skills, locations, company type, team size, achievements, or sparse evidence fields.

## Soft Preferences

`weighted_soft_preferences` must contain at least one item. Each item must use one searchable dimension:

- `responsibilities_search_text`
- `skills_search_text`
- `experience_search_text`
- `domain_search_text`
- `ownership_search_text`
- `achievements_search_text`
- `education_search_text`

Write soft preference `text` as concrete work content or business context, not just a title or keyword. Use negative `weight` for avoid-style needs by describing the unwanted work positively.

## Results

Explain candidate facts only from `results[].raw_profile`. Use `soft_preference_scores` only to explain sorting.
