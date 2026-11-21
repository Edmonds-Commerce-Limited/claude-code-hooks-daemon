# Phase 6 handoff 7 (Task 0 and Task 6.1 done; Task 6.2 not started; 6.3 blocked)

## Done

- Task 0: `_scratch_pressure` tested directly (`TestScratchPressure` in
  `tests/unit/daemon/test_cli_scratch_worktrees.py`): no inventory gives None, an inventory at block (written by
  `_record_scratch_inventory`) gives a `Pressure`, `ttl_hours=None` gives None, below block gives None.
- Task 6.1 (`daemon/cli.py`):
  - `_scratch_worktree_reports`: a dry run from the main checkout (no `--root`) also classifies every other
    registered worktree's `untracked/scratch` (skips prunable, missing or symlinked roots, and roots
    `resolve_sweep_root` refuses); text prints a section per root, JSON adds a `worktrees` list. Creates nothing.
  - `_ScratchSources.store_checkout`: the store always lives in the main checkout.
  - `_scratch_store_refusal` now lets `--apply` (only) run from a registered linked worktree of the same repository
    (`_scratch_linked_apply_refusal`: checkout root, `is_worktree_of_repo`, main `.git` a directory). The root is
    still held inside the running checkout by `resolve_sweep_root`, so `--apply` never reaches another checkout.
    `restore`/`keep` stay main-only. The TTY gate is unchanged and still comes first for every apply.
  - The old test `test_apply_from_a_linked_worktree_is_refused` became
    `test_apply_from_a_linked_worktree_cannot_reach_the_main_root`.

## Needs an independent security review

- The relaxed refusal in `_scratch_store_refusal` (linked-worktree `--apply`).

## Next

- Task 6.2 (evacuate mode from `worktree-reap --reap` and `cleanup_after_merge`): not started. Constraints for the
  next agent: evacuation runs BEFORE the existing removal judgement and only returns blockers; anything not packed and
  verified (PROTECTED, KEPT, STUCK, and also LIVE) refuses the reap; add no exemption to the worktree-removal guard
  (if "an empty scratch root is not a blocker" needs a guard change, stop and hand off). Open question for the owner:
  `cleanup_after_merge` has no TTY, so evacuation there would pack and remove without a human's confirmation, which
  the `--apply` TTY gate otherwise forbids. Do not decide that silently.
- Task 6.3: blocked on Plan 00623.
- The module docstring of `tests/unit/daemon/test_cli_scratch_apply.py` still says `--apply` runs only in the main
  checkout; update it to "the store lives only in the main checkout".
