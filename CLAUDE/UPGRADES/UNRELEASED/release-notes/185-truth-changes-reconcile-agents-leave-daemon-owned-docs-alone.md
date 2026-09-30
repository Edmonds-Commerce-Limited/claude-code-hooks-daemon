# Callout: truth-changes reconcile agents now leave daemon-owned docs alone, and the core plan doc lists the correction category

**Plan**: 00474
**Audience**: operators

The reconcile rules that `check-truth-changes` hands to an upgrading agent now say never to edit the daemon-owned docs: `CLAUDE/core/*.core.md`, `.claude/HOOKS-DAEMON.md` and the generated `<hooksdaemon>` block in `CLAUDE.md`. An upgrade regenerates all three, so an edit there was lost and two parallel chunks could collide on the same file. The chunk list no longer promises that chunks touch disjoint documents; it tells each subagent to re-read a file just before editing it.

The deployed `CLAUDE/core/PlanWorkflow.core.md` (refreshed on upgrade) still listed six journal categories after v3.67.0 added `correction`. It now lists all seven, says a `correction` requires `--ref`, and names `failsafe_cron_session_advisor` as the SessionStart route to the failsafe cron. If your own docs or agent briefs copied the six-category list from that core doc, the v3.67.0 truth-changes entry `journal-correction-entry` already covers them; no new truth-changes entry is needed.

Truth-changes entries may now carry an optional `stale_phrases` list, and a release-time test fails while a shipped template still contains one. Addresses #63.
