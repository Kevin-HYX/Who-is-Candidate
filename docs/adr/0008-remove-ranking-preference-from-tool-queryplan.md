# Remove ranking preference from Tool QueryPlan

The Tool QueryPlan contains only executable search instructions: `hard_constraints` and `weighted_soft_preferences`. `ranking_preference` is removed because the tool does not consume it, does not use it to break ties, and does not generate explanations. Agents can keep ranking notes in their own conversation state without sending them to the Candidate Search Tool.

