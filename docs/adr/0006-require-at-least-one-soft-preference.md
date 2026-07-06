# Require at least one soft preference

Every valid QueryPlan must include at least one `weighted_soft_preferences` item. This prevents searches that only apply hard filters and then return an arbitrary or misleading default ordering. The Agent must ask for or infer a ranking preference rather than sending an empty soft preference list.

