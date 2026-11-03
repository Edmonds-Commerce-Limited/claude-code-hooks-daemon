# Callout: dormant branches now block new branches, and `branch-park` exempts one

**Plan**: 00558
**Audience**: operators

The branch creation guard now also enforces dormancy. While an unmerged, unparked branch is at the block stage (30 days idle under the default `standard` preset), creating a branch is denied with rule `R-BRANCH-DORMANT`; the deny lists the branches and the three ways out: finish and merge, park, or delete. A branch at the noisy stage (14 days) adds a context line to every allowed creation. `branches.dormancy.mode: warn` stops at the noisy stage and `off` disables the stages. Nothing else is denied, so commits, merges, pushes and deletes stay open.

- **Check before you upgrade.** A repository that already holds a branch idle for 30 days or more is blocked from the first session start after the upgrade: no new branch and no agent worktree until each such branch is merged, parked or deleted. Run `bin/hooks-daemon branch-sweep` first; anything listed as `block` under "Dormant" needs a decision. Set `branches.dormancy.mode: warn` if you cannot decide straight away.
- `bin/hooks-daemon branch-park <name> --reason "<text>"` writes an empty `Parked-Reason` commit at the branch tip without a checkout and pushes it with a plain fast-forward. A parked branch never trips a stage. `branch-park --clear <name>` writes an `Unparked` commit.
- `branches.dormancy.preset: strict` warns from 3 days and blocks at 7. It is never applied for you: `bin/hooks-daemon optimise-checklist` prints a non-scoring OPTIONAL line suggesting it to a project on the defaults, and the score is unchanged.
- The stages come from the SessionStart labels snapshot (`untracked/branch-inventory/labels.json`), so a branch ages as of the last session start; `branch-park` updates the snapshot at once.
