# Callout: the idle housekeeping report also names old scratch files and changed-green refs of deleted branches

**Plan**: 00470
**Audience**: operators

`idle_housekeeping_advisory` (beta, opt-in, off by default) now has two more report-only sections. Neither deletes anything; each prints the command a person may choose to run.

- **Old scratch files.** Files under `untracked/scratch/` not modified for `stale_scratch_days` (default 14, an integer of at least 1) are summarised as a count, a total size and the oldest age, with a suggested `find ... -delete`. The scan stops at an entry limit or a time budget, never follows a symlink, and says `SCAN INCOMPLETE` when it stopped early. `report_stale_scratch: false` turns it off.
- **Changed-green refs of gone branches.** The QA `changed` tier writes `refs/integration/changed-green/<branch>` when a branch goes green and nothing prunes it, so each one pins its commit against `git gc`. A ref is listed (at most 5 are named, with one `git update-ref --stdin` command that deletes them all) only when no local branch and no remote-tracking branch has that name. `report_gone_branch_refs: false` turns it off.

`hooks-daemon disk-usage` no longer says the supervisor's `decision.log` is bounded on daemon start: the supervisor caps it at 4 MiB itself, when it writes.

Nothing to do on upgrade. A bad `stale_scratch_days` is reported at session start and the default is used.
