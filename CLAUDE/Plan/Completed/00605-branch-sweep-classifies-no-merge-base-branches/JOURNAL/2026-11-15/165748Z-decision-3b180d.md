## 16:57 · decision · — — Stand-in ruling: parked slot, fourth pass

Stand-in ruling (automated one-off, NOT the owner). No owner message arrived on this question since the awaiting-human stop.

Pending question, fourth pass: the three Plan 00605 follow-up fixes, plus dependency updates (19 Dependabot alerts on main), need a new branch, and R-BRANCH-PARKED-POOL was reported as blocking creation because `worktree-476-ci-gate-trial` held the only parked slot (`branches.parked.cap: 1`). Options offered: (A) the branch's owner merges or deletes it; (B) the owner raises the cap to 2.

Ruling: DECLINED on both options, and neither is needed any more. The config was not edited; nothing was merged, cleared, parked, deleted or created by this stand-in.

The question as put is out of date. Checked on this pass (2026-11-15, after `git fetch origin`, origin/main at `6a356c764`):

- `bin/hooks-daemon branch-preflight`: exit 0, "A branch may be created: no pool refuses it."
- `bin/hooks-daemon branch-sweep`: Open work 0 of 10, Parked 0 of 1, Merged-not-deleted 0 of 10.
- `git ls-remote origin 'refs/heads/worktree-476*'`: no output. `git branch -r` lists no such branch. The trial branch is no longer on origin.
- `.claude/hooks-daemon.yaml` still reads `cap: 1  # Owner ruling: parked work is WIP; one parked branch blocks new branches`; the last commit to touch it is still `8ee4b5135`.

This stand-in did not establish who removed the trial branch or when, and no journal entry read on this pass records it. It was not removed by this stand-in.

Why both options are declined all the same:

- (A) is another person's action. Plan 00594's entry `160427Z-decision-5f74c3.md` (commit `eb5284129`) records the advisor ruling that `worktree-476-ci-gate-trial` is another developer's branch and stays blocked. A stand-in cannot choose it on that person's behalf.
- (B) reverses a recorded owner ruling, as the 10:55 entry (`105536Z-decision-ca8364.md`) set out. With the parked pool empty there is also no engineering reason left to raise it.

What this means for the waiting work:

- The three follow-up fixes (`work-queue done` re-caching the finished issue as workable; acceptance `_discover_socket` missing the `/tmp` fallback socket; `branch_creation_guard` missing `git worktree add` inside `scripts/setup_worktree.sh`) are no longer blocked by the parked pool. Creating their branch is ordinary engineering work under the existing guards. The coordinator should run `branch-preflight` again itself before acting, since this reading is a moment in time.
- The dependency updates are a separate matter. Upgrade approvals stay blocked for a stand-in, so this ruling does not approve them; that part still waits for the owner.

A later real owner message can overturn this ruling.
