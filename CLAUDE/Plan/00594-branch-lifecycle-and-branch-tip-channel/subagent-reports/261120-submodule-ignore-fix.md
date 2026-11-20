# Security review finding (Low): ignored submodule pointers read as no change

Branch `agent-a20c91c23eca4e56e-43e33957`. Strict TDD: the regression tests were written first and
failed for the reason the finding gives, then the fix made them pass.

## Finding, confirmed and widened

`_net_change` ran `git diff --raw` without `--ignore-submodules=none`. Git drops a gitlink row when
the tracked `.gitmodules` says `ignore = all`, or when any config level sets
`diff.ignoreSubmodules = all`. Probes on git 2.47.3 also showed the following:

- `git status --porcelain` drops it too. Two removal or stop gates read it:
  `branch_cleanup.worktree_blocker_groups` and `branch_stop_guard._is_dirty`.
- `git cherry` patch-ids drop it under `.gitmodules ignore = all`, and no flag (including
  `-c diff.ignoreSubmodules=none`) undoes that. As a result, the LOCAL `classify_branch` gave a branch
  `{add f + bump sub}` against a default `{add f}` the tier `patch-equivalent`, and that tier is safe
  to delete. The remote proof already checks the net change before it looks at patch-ids.
- `git log -- <path>` path limiting and `ls-tree` are not affected.

## Fix

- `utils/git_repo.SEE_SUBMODULES = "--ignore-submodules=none"`, one shared constant, now passed by:
  - `remote_branch_proof._net_change` (all three tiers: content-preserved, patch-equivalent via
    `_HELD_PER_PATH`, and surviving-content)
  - the `branch_cleanup` worktree status
  - the `branch_stop_guard` dirty check
- The new `remote_branch_proof.gitlink_change_held` returns True when the net change moves no
  pointer, or when the target's history holds the whole net change. It returns False when there is
  no merge base. `branch_safety.classify_branch` now requires it, through `_gitlinks_held` (any
  failure counts as False), before it accepts `patch-equivalent`. It is a gate in the classifier,
  not part of `patch_equivalent`, so the remote proof (already gated) pays no extra git calls:
  `TestGuardPathCost` holds.
- `branch_inventory._CACHE_VERSION` went from 5 to 6, so cached verdicts computed under the old diff
  are dropped.

## Tests

`tests/unit/core/test_submodule_ignore_proof.py` has 19 tests. The repos are real and the gitlink is
written with `update-index --cacheinfo`. Config is isolated: `GIT_CONFIG_NOSYSTEM` plus a temp
`GIT_CONFIG_GLOBAL`. Every case runs under both the `.gitmodules` and the global-config variant, and
one case sets both at once. The cases cover:

- the `_net_change` row
- `holds_net_change`
- the remote delete is refused and names `sub`
- the local tier is not safe
- worktree removal and the stop guard see a moved submodule
- the gate fails closed
- the controls still prove: the pointer is held on the default, and a cherry-pick with no gitlink
  stays `patch-equivalent`

RED: 13 failed, 3 passed. GREEN: 19 passed. Regression: 812 passed across the plan's
proof, cleanup, safety, stop-guard, inventory, destructive_git and remote-delete files, plus
`test_git_repo.py`. ruff, black and mypy are clean on the changed files.

## Out of scope (not a "nothing is lost" decision)

- `branch_inventory._shortstat_lines` (`diff --shortstat`, a size fact for display)
- `utils/merge_scope` (`diff --name-only`, QA scope)
- `utils/git_facts` diffs (commit-gate staged facts)
- `reference_repo_freshness`
