# Callout: an interrupted `mkplan.bash` now stops instead of finishing without its lock

**Plan**: 00474
**Audience**: operators

`mkplan.bash` (and the repository's own `mkroutine.bash`) serialise plan-number allocation with a lock. When a run holding that lock received Ctrl-C (SIGINT) or SIGTERM, it released the lock and then carried on: it created the plan folder, advanced the counter and exited 0, with no lock held. A second agent creating a plan at that moment could take the lock, read the same counter and get the same plan number.

An interrupted run now releases the lock and exits (130 for SIGINT, 143 for SIGTERM) without creating anything after the signal. The deployed `CLAUDE/Plan/mkplan.bash` is refreshed by the upgrade.

Nothing to do on upgrade. If an interrupted `mkplan.bash` left a numbered folder with no `PLAN.md`, remove it. The next run takes the number after the highest folder on disk either way.
