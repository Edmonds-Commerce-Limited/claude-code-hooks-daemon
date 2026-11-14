# Plan 00605 report: no-merge-base branches (GitHub #203)

## Red failure (before the fix)

`tests/unit/core/test_branch_inventory_no_merge_base.py`, orphan branch beside `main`:

```
AssertionError: the sweep budget ran out, or git failed, before this tip was measured against every target
FAILED ...TestNoMergeBase::test_orphan_branch_is_unmerged_work
6 failed, 2 passed
```

The budget was the default 3000 ms and unspent.

## Fix chosen

`_lines` in `core/branch_inventory.py`: the three-dot diff is tried first. If it fails and `git merge-base` positively
reports no common ancestor (exit 1, no output), lines come from a diff of the empty tree to the tip. Reasoning: with no
shared ancestor, all of the tip is its own work, so the empty tree is exactly the merge base the three-dot form lacks.
The two-tree diff `target tip` was rejected because it would count the target's own files as deletions and overstate the
work. Leaving lines unmeasured was rejected because it would show nothing for a branch that has content.

The two-dot log and `git cherry` already worked without a merge base. Containment still needs `ahead == 0`, so a
no-merge-base branch cannot become MERGED or PATCH_EQUIVALENT (a test pins this). It classifies LIVE with `ahead` = its
commits. Branches that share history take the unchanged first path.

## Reasons

`_UNMEASURED_REASON` is replaced. `_Pass.unmeasured` records the cause per (tip, target sha): `BUDGET_REASON` (names
`branches.sweep.budget_ms` and `--budget-ms`) or a git-failure reason naming the target. A separate "no merge base"
reason is not reachable after the fix, since such pairs are now measured; I did not add dead text. Tests cover budget
(`budget_ms: 0`), a `git cherry` failure and a failing `git diff`.

## `--budget-ms N`

`cmd_branch_sweep` copies `branches` with `sweep.budget_ms` replaced before either the report or the `--clean` path, so
the config model and the SessionStart handler are untouched. The existing `_positive_int` argparse type rejects 0,
negatives and non-integers. Tests: parse, rejection, override reaches `build_inventory` and `clean_sweep`, and the
configured value is used without the flag.

## Docs

Release note `073-branch-sweep-classifies-branches-with-no-merge-base.md`; `sweep.budget_ms` row in
`docs/guides/CONFIGURATION.md` mentions the flag. No doc quoted the old reason text.

## Notes

- `/workspace/.venv` is broken here (its interpreter points at Python 3.13 while the packages are for 3.11), so I ran
  tests from a throwaway venv at `untracked/scratch/venv` (gitignored).
- No disagreement with the brief.

## Review fixes

All five review findings were accepted; no disagreement.

1. Critical: `_pair_facts` now asks `_has_no_merge_base` once, before the cherry step. With no merge base it skips
   `git cherry` and sets `unique = ahead`, so the branch is always unmerged (LIVE). Lines for the default target come
   from the new `_empty_tree_lines`. Regression tests: matching-root-patch orphan (default branch and, via
   `_pair_facts` with `want_lines=False`, an integration line) and the metadata-only `filter-branch` rewrite (both
   targets).
2. Release note 073 now states these branches are never merged, contained or patch-equivalent.
3. Git-failure reason now reads "raising branches.sweep.budget_ms will not help" (covers the exit-124 case); tested.
   The cherry-failure and failing-diff tests assert "git failed" and the target name. The cherry-failure tests now use
   a shared-history branch, since orphans no longer reach cherry.
4. Shallow clones: `_is_shallow` (`git rev-parse --is-shallow-repository`) turns a no-merge-base pair in a shallow
   repository into a returned `HistoryNotFetched` value (not an exception: the error_hiding checker rejects a
   `return None` or fallback assignment inside an `except`); `_Pass.facts` records a "history not fetched" reason and the tip stays
   UNCLASSIFIED. Tested with `clone --depth 1 --no-single-branch`.
5. `BUDGET_REASON` pyright error: the attribute exists (`branch_inventory.py:108`); it appears to be a stale editor
   diagnostic; QA pyright reports 0 errors.

Final targeted QA: `QA: 43/43 PASSED`.

Process note: the source change was written before the new tests, so no separate red run was recorded for them.
