# Callout: two `mkplan.bash` runs can no longer get the same plan number (Ubuntu 25.10+, and interrupted runs)

**Plan**: 00474
**Audience**: operators

`mkplan.bash` (and the repository's own `mkroutine.bash`) serialise plan-number allocation with a lock. Two defects let two runs hold it at once and get the same plan number.

**On Ubuntu 25.10 and later**, the lock was taken by running `mkdir` and trusting it to fail when the lock already existed. Those releases ship the Rust uutils coreutils as `mkdir`, and under a race two `mkdir` calls on the same path can both report success. Two agents running `mkplan.bash` at the same moment then both took the lock and both created the same plan number. The lock is now a file created by bash itself with an exclusive create (`set -C`, which opens with `O_CREAT|O_EXCL`), so it no longer depends on which `mkdir` is installed. The same fix covers the venv build lock's non-`flock` fallback in `scripts/install/venv.sh` (and its Python side in `hooks-daemon repair`) and the background-sync lock in `provision.sh`.

**On any system**, a run holding the lock that received Ctrl-C (SIGINT) or SIGTERM released the lock and then carried on: it created the plan folder, advanced the counter and exited 0, with no lock held. An interrupted run now releases the lock and exits (130 for SIGINT, 143 for SIGTERM) without creating anything after the signal.

The deployed `CLAUDE/Plan/mkplan.bash` is refreshed by the upgrade.

Nothing to do on upgrade. A lock left as a directory by the previous version is still honoured as held, so an old and a new run cannot both get in. If a timed-out run names a lock that no running `mkplan.bash` holds, remove it. If two plans already share a number, renumber one; if an interrupted run left a numbered folder with no `PLAN.md`, remove it. The next run takes the number after the highest folder on disk either way.
