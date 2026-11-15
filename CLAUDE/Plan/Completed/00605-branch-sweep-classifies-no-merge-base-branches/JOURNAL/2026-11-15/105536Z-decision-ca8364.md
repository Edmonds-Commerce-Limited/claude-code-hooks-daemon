## 10:55 · decision · — — Stand-in ruling: raise the parked cap?

Stand-in ruling (automated one-off, NOT the owner). No owner message arrived since the awaiting-human stop.

Pending question: the three Plan 00605 follow-up fixes need a new branch, and R-BRANCH-PARKED-POOL blocks creation: `branches.parked.cap` is 1 and `origin/worktree-476-ci-gate-trial` (10 days old, origin only) holds the slot. The earlier stand-in entry (2026-11-15 07:54, `075452Z-decision-c91b06.md`) declined (A) owner deletes the remote branch and (C) merge the trial branch anyway. The one new option is (B): raise `branches.parked.cap` from 1 to 2 in `.claude/hooks-daemon.yaml`.

Ruling: DECLINED, stays blocked. The config was not edited; nothing was merged, cleared, parked or deleted.

Reasons:

- The limit is the owner's, and the config says so in place. `.claude/hooks-daemon.yaml` line 1594 reads `cap: 1  # Owner ruling: parked work is WIP; one parked branch blocks new branches`. The value 1 is not a default nobody chose; it is a recorded owner decision.
- The situation the cap is producing now is exactly the one that comment describes: one parked branch is blocking new branches. The guard is doing what the owner ruled it should do. Raising the cap to 2 would not be tuning a setting to fit new facts; it would reverse that ruling at the moment it first bites.
- A stand-in may choose among engineering options only. Changing an owner-set guard limit so that the guard stops blocking is a policy change in substance, however small the edit. It is the same kind of move as the cap exits declined under Plan 00594.
- The guard's own instruction for this case is to stop and ask a human when the limit seems to force a choice between losing work and exceeding it. That is the present choice: the slot is freed only by deleting or merging the trial branch (both declined already), or by exceeding the limit. Anything a guard says to ask the user stays blocked for a stand-in.
- Waiting loses nothing. The three fixes are recorded as Plan 00605 follow-ups and the trial branch is safe on origin. The cost of declining is delay only, while raising the cap would leave a standing change to the owner's policy that outlives this one blocker.

Evidence read: the earlier stand-in entry; the `branches:` block of `.claude/hooks-daemon.yaml` (lines 1588 to 1596); `bin/hooks-daemon explain-rule R-BRANCH-PARKED-POOL`, which prints the rule's blocked condition and that it is an action guard.

What the owner can do to unblock, any one of: delete the remote trial branch; raise `branches.parked.cap` (or say the stand-in may); or say the trial workflow should be merged after all. The three fixes wait until then. A later real owner message can overturn this ruling.
