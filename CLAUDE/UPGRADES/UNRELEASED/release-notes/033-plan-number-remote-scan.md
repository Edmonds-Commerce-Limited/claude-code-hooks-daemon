# Callout: mkplan now fetches before allocating, so two clones stop taking the same plan number

**Plan**: 00562
**Audience**: operators

`mkplan.bash` and the daemon's plan numbering now consider the plan folders other clones have pushed, not just the local counter and disk.

- **What changes**: before allocating, `mkplan.bash` fetches the default remote (`origin`, else the first remote) within the 30 second fetch budget, reads the plan folder names on every remote branch (the plan root, `Completed/` and `Cancelled/`) without a checkout, and allocates above the highest of counter, disk and remote.
- **Read-only**: it never pushes. The fetch happens before the scaffold lock is taken.
- **Offline**: with no remote, a failed fetch, or a timeout, allocation falls back to the local answer and prints `remote could not be checked` on stderr once.
- **Only mkplan fetches**: hooks run under a 5 second handler budget and perform no network I/O. The daemon's `next_plan_number_for_target` applies the same rule by reading the remote-tracking refs already fetched (by `mkplan.bash`, a session-start sweep or your own `git fetch`), never fetching itself. The check that validates a hand-created `PLAN.md` stays local.
- **Unchecked remote**: on the daemon side the fallback and its reason, including git's own error text, are logged as a warning. If any remote branch's tree cannot be listed, both scanners treat the remote as unchecked.
- **Known limit**: nested archive folders below `Completed/` and `Cancelled/` are not read on the remote.

Run `bin/hooks-daemon upgrade` (or redeploy plan workflow) to refresh the deployed `CLAUDE/Plan/mkplan.bash`.
