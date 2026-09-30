# Callout: `goal_injection` and `recovery_cron_advisor` no longer fire on any edit of an already-In-Progress/Complete plan

**Plan**: 00466
**Audience**: operators

Both handlers used to match a plan's post-write STATUS rather than a genuine TRANSITION to it, so any Write/Edit to a plan already In Progress or Complete spuriously re-fired their advisories. They now fire only on the write that actually moves the Status line, backed by a new `plan_status_snapshot` sensor (ships enabled) that records ground truth immediately before the write lands. Operators who have explicitly disabled `plan_status_snapshot` keep the pre-existing inference fallback instead of this ground-truth path; see that handler's own module docstring (`handlers/pre_tool_use/plan_status_snapshot.py`) for the mechanism.
