# Candidate Search Help

This MCP server provides read-only candidate search.

## Resources

- `candidate://help`: this help document.
- `candidate://index-status`: current preprocessing and index coverage.

Read `candidate://index-status` before assuming the index is available or full. If `index_status` is `partial`, tell the user results are from a partial index.

## Tool

1. Read `candidate://index-status`.
2. Build complete `search_candidates` arguments by following the Candidate Query Guide below.
3. Call `search_candidates`.
4. If the tool rejects the QueryPlan, correct the invalid arguments instead of silently weakening the user's requirement.
5. Explain the returned candidates from `results[].raw_profile`.

## Results

Explain candidate facts only from `results[].raw_profile`. Use `soft_preference_scores` only to explain sorting, never as evidence of a candidate fact or as an absolute ability score.

Treat missing, empty, `unknown`, `not_provided`, and `insufficient_evidence` fields as unknown. Say that the profile does not provide enough evidence; do not claim the candidate lacks the attribute.

If hard filtering leaves too few candidates, suggest which explicit hard constraint the user could relax. Do not silently convert a hard constraint into a soft preference.

If `returned_count` is greater than `requested_top_k`, explain that all candidates sharing the boundary rank were returned.
