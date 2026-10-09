# Callout: the plan fact-check feed names real files, checks only what changed, and no longer loses a check

**Plan**: 00474
**Audience**: operators

If you enabled `plan_fact_check_feed`, its owed-check instructions are now trustworthy. Edits inside a sub-agent's worktree no longer feed your session's debouncer, a plan archived to `Completed/` is named at its new path (or dropped if gone), and a plan's first sighting records a baseline instead of diffing the whole folder. The content counts as checked only once the session is seen dispatching `plan-fact-checker` with the diff path in its prompt; an unacted offer is re-offered after five minutes, up to three times. A small edit (20 lines or fewer) within ten minutes of a confirmed check is taken as a correction and absorbed, so fixing a finding no longer owes another check.
