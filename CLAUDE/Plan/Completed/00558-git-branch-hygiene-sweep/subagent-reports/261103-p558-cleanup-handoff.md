# Handoff: Plan 00558 Task 3.1 (cleanup), after steps 0 and 1

Brief: `/workspace/untracked/scratch/brief-558-cleanup.md`. Worktree
`/workspace/untracked/worktrees/worktree-558-cleanup`, branch `worktree-558-cleanup`,
pushed to origin. Its venv exists (`untracked/venv-*/bin`). The agent that wrote this stopped
on its context budget at a clean commit; nothing is uncommitted.

## Done

- **Step 0** (`3657326be`): finished the WIP tag-containment commit `27f4c76ce`.
  `_refs_hash(rows)` (the build call passed `repo` too and crashed every test), the unused
  `_TAGS` constant removed, `_CACHE_VERSION` 2 -> 3 so a stored verdict a tag vouched for is
  discarded, the `Containment` docstring no longer names a tag. New tests in
  `tests/unit/core/test_branch_inventory.py`: `containment_of` reports NOWHERE for a tip only a
  local tag holds, and a version-2 cache entry is not reused. RED-proven by running the new test
  file inside a detached worktree of `93a838b77` (5 failed there; 97 pass now).
- **Step 1** (`9d9cabaa1`): `daemon/branch_safety.py`.
  - `_unique_commit_count` is gone; `_patch_equivalent()` uses `cherry_unique_shas` (None =
    unproven) and `_has_merge_commits()` (`rev-list --merges target..tip`; non-empty or failed =
    not equivalent).
  - `classify_branch(..., targets: Sequence[str] | None = None)`; None means
    `(protected_ref,)`, empty raises `ValueError`. Every target goes through
    `_protected_base_ref`. Merged tier: ancestor of ANY target. Patch-equivalent: ANY target.
    Content-preserved: blobs reachable from the UNION of targets. New field
    `BranchClassification.proven_against` (resolved ref, e.g. `refs/heads/release/x`).
  - `delete_branches(..., targets=None)` passes through.
  - Tests: `TestPatchEquivalenceFailsClosed`, `TestIntegrationLineTargets` at the end of
    `tests/unit/daemon/test_branch_safety.py` (9 of 11 RED before; 89 pass now). The CLI
    delete-branch and branch-defaults tests also pass.

## Left (brief steps 2, 3, 4 and the wrap-up)

1. **Step 2**, PostToolUse cleanup-after-merge handler (DESIGN.md section 7). Design note for
   the implementer: `classify_branch` REFUSES a branch checked out in a worktree
   (`REFUSAL_WORKTREE`), so the order must be: classify; if the refusal is the worktree one,
   prove the tier first (call `classify_branch` from the main checkout is not enough; consider a
   small public helper that runs the tier proof without the worktree refusal, or classify after
   reading the worktree's cleanliness), `git worktree remove <path>` (no `--force`), then
   `delete_branches(..., targets=[HEAD's ref], bundle_path=...)`, which re-classifies with the
   worktree gone. Targets: HEAD (the checkout is on the default or a line). Config key
   `branches.cleanup_after_merge.mode` (`advise` model default, `act` in this repo's
   `.claude/hooks-daemon.yaml`, `off`), plus config-changes manifest entry.
2. **Step 3**, `branch-sweep --clean` / `--dry-run` in `core/branch_sweep.py` + the CLI verb.
   Candidates from the inventory states `merged`, `merged-into-line`, `patch-equivalent`;
   targets = inventory default ref + integration-line refs.
3. **Step 4**, `_remote_delete_note` in `handlers/pre_tool_use/destructive_git.py`: refuse
   default/line/exempt/protected names; prove by one `for-each-ref --merged` per target; keep
   the batched `ls-remote`; handler reads `branches:` config. Commit message must say
   "Addresses #152 and #153".
4. Wrap-up: tick Task 3.1 in PLAN.md, journal via `CLAUDE/Plan/mkplan.bash --journal 558 action <body-file>`, release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`, report to
   `subagent-reports/261103-task31-cleanup.md`, then
   `FULL_QA_LOCK_WAIT_SECONDS=5400 ./scripts/qa/llm_qa.py changed`.

## DESIGN.md corrections found so far

- Section 2 "Reuse" names `_unique_commit_count` as the patch-equivalence step 5 uses; it is
  removed, and both the inventory and `classify_branch` use `cherry_unique_shas`.
- Section 4 implied tags could contain a tip; containment is remote-tracking refs only.
