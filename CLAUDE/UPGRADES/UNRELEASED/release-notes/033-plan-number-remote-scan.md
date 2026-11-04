# Callout: mkplan now fetches before allocating, so two clones stop taking the same plan number

**Plan**: 00562
**Audience**: operators

`mkplan.bash` and the daemon's plan numbering now consider the plan folders other clones have pushed, not just the local counter and disk.

- **What changes**: before allocating, `mkplan.bash` fetches the default remote (`origin`, else the first remote) within the 30 second fetch budget, reads the plan folder names on every remote branch (the plan root, `Completed/` and `Cancelled/`) without a checkout, and allocates above the highest of counter, disk and remote.
- **Read-only**: it never pushes. The fetch happens before the scaffold lock is taken.
- **Offline**: with no remote, a failed fetch, or a timeout, allocation falls back to the local answer and prints `remote could not be checked` on stderr once.
- **Daemon side**: `next_plan_number_for_target` applies the same rule when a hook allocates a number. The check that validates a hand-created `PLAN.md` stays local.

Run `bin/hooks-daemon upgrade` (or redeploy plan workflow) to refresh the deployed `CLAUDE/Plan/mkplan.bash`.
