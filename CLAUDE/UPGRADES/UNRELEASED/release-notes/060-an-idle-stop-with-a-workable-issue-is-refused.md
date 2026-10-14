# Callout: an idle stop with a workable issue is refused

**Plan**: 00470
**Audience**: client projects

A coordinator that closed an issue and then stopped with "the next issue is for the hourly tick" was let through on the `STOPPING BECAUSE:` prefix, although workable issues existed and nothing was in flight. The new Stop handler `idle_workable_issue_stop_gate` (rule `R-STOP-IDLE-WITH-WORKABLE-ISSUE`) refuses that stop on facts: the `issue-sdlc` job is declared for this host and thread, the work queue has no `running` entry, and a fresh workable-issues cache lists an issue. The deny names the issue and says the cron is a safety net, not a scheduler. It stands aside for a sub-agent stop, a usage pause, a non-holder thread, a live or just-declared `[awaiting-human]`, a stale or missing cache, and a stop that re-enters after its own deny. It reads a local file and never calls GitHub.

`work-queue done NAME` now prints `next workable issue: #N - start it now` (or `no workable issue`, or that the next issue is unknown when GitHub could not be asked; the close never fails on that), and `issue-validity --list-eligible` also writes the cache. Workable means eligible and not labelled `agent-needs-human`. The handler is on by default and inert in any project that does not declare an `issue-sdlc` job; `options.job_id`, `options.max_cache_age_hours` (default 2) and `options.marker_expiry_hours` tune it.
