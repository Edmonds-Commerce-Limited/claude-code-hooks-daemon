# Code Review: Plan 00605, branch `worktree-issue-203-no-merge-base` (ad489f6a8)

## Summary

The diff unblocks orphan branches, but the cherry step can still put them in the
MERGED pool as PATCH_EQUIVALENT. The intended behaviour forbids that, and the
change makes it newly reachable. Under the old code these branches stayed in the
fail-closed UNCLASSIFIED state. The reason split, the `--budget-ms` override and
the CLI tests are sound.

Reviewed: 7 files, +275/-18. Issues: 1 critical, 1 important, 3 suggestions.
New and changed tests pass (41 passed). Probes are in
`untracked/scratch/review-00605/` in this worktree: `probe_orphan_equivalent.py`,
`probe_shallow.py`, and `pytest.txt`.

## Critical Issues

### 1. A no-merge-base branch can be classified PATCH_EQUIVALENT, which puts it in the MERGED pool (Confidence: 95%)

**Location:** `src/claude_code_hooks_daemon/core/branch_inventory.py:582-590`
(`_pair_facts`), consumed at `:1245-1247` (`_tip_verdict`)

**Problem:** The fix only repairs `_lines`. When there is no merge base,
`git cherry <target> <tip>` still runs. It compares the patch-ids of every tip
commit against the target's whole history. Any tip commit whose patch matches a
target commit is marked `-`. If they all match, `unique == 0` and `merges == 0`,
so the branch becomes `PATCH_EQUIVALENT`. Nothing in the new code checks
`_has_no_merge_base` before the cherry step.

**Evidence (probe_orphan_equivalent.py, run against this branch):**
```
merge-base rc: 1
cherry: - e3054030...
same-root-patch orphan -> patch-equivalent ahead 1 lines 1 None
rewrite: merge-base rc: 1
rewritten-history branch -> patch-equivalent ahead 4 lines 4 None
```
Case 1 is an orphan whose root commit adds a file exactly as main's root
commit did. Case 2 is the scenario the release note names: a branch left on the
old history after `filter-branch` rewrites main (here only author/committer
metadata changes). Both reach PATCH_EQUIVALENT. Before this diff, both were
UNCLASSIFIED and so fail-closed.

**Why it matters:** `PATCH_EQUIVALENT` maps to `Pool.MERGED`
(`branch_inventory.py:171`). That makes the branch:
- count toward `R-BRANCH-MERGED-POOL`, which denies new branch creation until the
  branch is cleaned or kept;
- show up in `branch_stop_guard` (`core/branch_stop_guard.py:45`) as merged but
  undeleted;
- become a `branch-sweep --clean` candidate (`core/branch_cleanup.py:88`, `:648`).

This breaks the explicit requirement: "must never be classified as merged,
contained or patch-equivalent to that target". The new test
`test_orphan_is_never_contained_or_equivalent`
(`tests/unit/core/test_branch_inventory_no_merge_base.py:69-75`) does not catch
it. Its fixture orphan has content unrelated to main, so it passes whatever the
cherry step does.

**Suggested fix:** In `_pair_facts`, find out once whether a merge base exists,
before calling cherry. When `_has_no_merge_base` is true, skip cherry and return
`unique=ahead`. Pass that same answer into the lines computation so
`merge-base` does not run twice. Add a regression test using probe case 1: an
orphan whose root patch equals main's root patch, asserting `LIVE`, `ahead == 1`
and not `PATCH_EQUIVALENT`. Also run that fixture against an integration-line
target, because the non-default target path (`want_lines=False`) goes through
the same cherry step.

## Important Issues

### 1. The release note claims more than the code does (Confidence: 90%)

**Location:**
`CLAUDE/UPGRADES/UNRELEASED/release-notes/073-branch-sweep-classifies-branches-with-no-merge-base.md`

**Problem:** The note says a branch "left behind when the default branch's
history was rewritten ... is now measured and classified as unmerged work". As
Critical 1 shows, a metadata-only rewrite produces PATCH_EQUIVALENT (merged
pool), not unmerged work. The note becomes accurate once Critical 1 is fixed.

**Suggested fix:** Fix Critical 1, then keep the wording. If the fix is
deferred, the note must say these branches can land in the merged pool.

## Suggestions

- **Shallow clones are treated as orphans.**
  `branch_inventory.py:541-560`. `git merge-base` exits 1 when the fork point is
  beyond the shallow cut, so `_has_no_merge_base` cannot tell this apart from a
  real orphan. `probe_shallow.py` shows a feature branch with 1 commit and
  1 line reported as `live ahead 2 lines 51`: the grafted boundary commit's
  whole tree is counted. This fails in the safe direction (LIVE), but the
  metrics are wrong, and Critical 1's patch-equivalence can also fire here.
  Remediation: check `git rev-parse --is-shallow-repository` once per pass.
  When it is `true` and no merge base is found, leave the pair UNCLASSIFIED with
  its own reason ("shallow clone: the fork point is not fetched"). Add a test
  using `clone --depth`.
- **The git-failure reason overstates itself.**
  `branch_inventory.py:113-115`. `_GIT_FAILED_REASON` says "a larger time limit
  will not help". The same path is reached when `run_git` hits its per-command
  `GIT_CONTEXT` timeout (returncode 124, `utils/git_repo.py:236-237`). In that
  case time is exactly the cause, even though `budget_ms` will not fix it.
  Remediation: say "raising branches.sweep.budget_ms will not help", or record
  returncode 124 as its own reason ("git timed out measuring ...").
- **The failing-diff test asserts too little.**
  `tests/unit/core/test_branch_inventory_no_merge_base.py:102-119`. It only
  checks that the reason does not contain "budget". Assert
  `"git failed" in record.reason` and the target name, as the cherry test does.
  Otherwise an empty or wrong reason would still pass.

## Positive Observations

- `_has_no_merge_base` checks for a definite "no common ancestor" answer:
  exit 1 with empty stdout. A bad ref (128), a timeout (124) or a missing git
  (127) never falls into the empty-tree path, and
  `test_lines_helper_still_fails_on_a_bad_ref` covers this. ("No ancestor" from
  a shallow clone is the exception, see Suggestions.)
- The `unmeasured` map always has an entry before `_tip_verdict` reads it: both
  `None` returns in `_Pass.facts` record a reason first. No KeyError path was
  found.
- `--budget-ms` uses `model_copy` on a local `branches`. The loaded config and
  the SessionStart handler are not touched. The tests check the parser,
  rejection of non-positive values, and that both the report path and the
  `--clean` path receive the value.
- The tests use real git repositories, not mocked git. The central LIVE test
  would have failed before the change (UNCLASSIFIED).
- Branches that share history are unchanged: `_lines` returns the three-dot
  result before any new call is made.

## Verdict

[ ] APPROVE
[x] REQUEST CHANGES - Critical 1 must be fixed (and covered by a test) before merge
[ ] REJECT
