# Treat top_k as a best-effort result limit

`top_k` is a requested result count, not a hard maximum. The search tool should make its best effort to keep results within `top_k`, but if the boundary rank contains tied candidates, all candidates with that rank are returned together. This preserves ranking correctness and avoids arbitrarily truncating candidates with the same score.

