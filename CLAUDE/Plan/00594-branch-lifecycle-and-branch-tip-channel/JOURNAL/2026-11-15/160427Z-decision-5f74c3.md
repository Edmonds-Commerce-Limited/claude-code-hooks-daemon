## 16:04 · decision · — — owner delegated to the advisor; advisor rulings

Owner delegated the pending decisions to the advisor (typed /advisor fable, "use fable advisor to unblock decisions"). These are the advisor's rulings, NOT the owner's per-item choices; the owner can overturn any of them.

1. `--allow-unproven`: remove it from `delete-branch` (an isatty gate is no real barrier to an agent; a hook deny only shape-matches). Find and update its callers first.
2. Recovery bundles: remove them as a delete path; a bundle must never be what lets a delete through. Check which proof tier in `daemon/branch_safety.py` accepts one; stop writing bundles if they only accompany already-proven deletes.
3. Cap exits: finish the work, or a confirmed-valueless delete where "confirmed valueless" is machine proof of no unique content or a human's confirmation, never the deleting agent's assertion. Parking stays a short bounded pause.
4. `wip.creation_grace`: keep the default 2 unless it can bypass the parked cap; if it can, exclude the parked pool from it.
5. The 53 bundle files: delete only the provably redundant ones, before removing the bundle code. Per file: `git bundle verify`, `git bundle list-heads`, and every head sha must exist locally and sit in an origin ref. Keep failures and list them. If a guard denies the delete, report it; no routing around.
6. `SSH_AUTH_SOCK`: read it per request from the connecting hook process, that variable only, in the shared remote-git path; validate an absolute path to a socket owned by the daemon uid; never log the value; fall back to the daemon env; never forward `GIT_SSH_COMMAND`.
7. `--allow-unmapped`: allowed for `[too-broad]` only, stated at handover; run changed_tests over `3802d032a~1` onward.

Still blocked: releases (human-typed /release only; unreleased fixes clients hit: 3802d032a, 46aab4db, d2e73d0e9), `worktree-476-ci-gate-trial` (another developer's branch), tasks 1.3, 4.6, 5.1 (second client seat).
