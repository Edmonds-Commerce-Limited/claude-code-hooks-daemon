# Plan 00625 adversarial review (security and correctness)

Status: IN PROGRESS. This file is pushed early and filled in as findings land.

Reviewed: branch `agent-a5947fd1e83f03452-ba288018` at `1ea9aa161`, against `main`,
from `git diff main...HEAD`. Reproducers live under `untracked/scratch/rv625/`
(not tracked); each is described below so it can be rebuilt.

## Verdict so far: FAIL (scope 5, the lock)

### F1 BLOCKER: a stale takeover file lets two processes hold the lock at once

`_upgrade_lock_takeover` breaks a `<lock>.takeover` file older than 60 s by
checking its mtime and then removing it BY PATH (`rm -f "$_take"`). Two
contenders that both saw the old mtime: the first removes it and creates its own
fresh takeover file, the second then removes THAT one and creates its own. Both
are now inside the "serialised" section; both re-read the dead token, both
`rm -f "$_lock"`, and both create the lock in turn (the first creates, the second
removes it and creates again). Each believes it holds the lock.

Reproducer (`race_takeover.sh`): a lock whose record names a dead pid in this
boot and pid namespace, plus a `.takeover` file touched 120 s into the past (what
a taker killed inside its critical section leaves), then 20 concurrent
acquirers each holding for 2 s. Result: **7 of 15 trials had two simultaneous
holders.** Without the stale takeover file: not reproduced in 10 trials (not a
proof of absence).

### F2 MAJOR: the lock is released while Layer 2 is still modifying the checkout

Liveness is keyed to Layer 1's pid (`upgrade.sh`), but Layer 2
(`upgrade_version.sh`, a child) does the writing. SIGTERM to Layer 1 alone runs
its EXIT trap, which releases the lock immediately; Layer 2 keeps running.
Reproducer (`term_parent.sh`): holder takes the lock, runs a 6 s child, receives
SIGTERM; 1.5 s later the lock file is gone, the child is still running, and a
second acquirer takes the lock. SIGKILL / OOM kill of Layer 1 opens the same hole
(pid gone => provably dead => takeover). Across pid namespaces the heartbeat also
dies with Layer 1, so the lock expires after 600 s whether Layer 2 finished or not.
