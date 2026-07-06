# Remove hard constraint strictness

Hard constraints use `field`, `op`, `value`, and `rationale`; the separate `strictness` field is removed. Inclusion, exclusion, and comparison semantics are represented by field-specific operators such as `in`, `not_in`, `>=`, and `=`. This avoids contradictory QueryPlans such as an exclusion operator paired with a separate must-style strictness flag.

