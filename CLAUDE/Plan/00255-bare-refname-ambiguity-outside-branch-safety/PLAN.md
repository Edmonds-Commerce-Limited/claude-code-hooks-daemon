# Plan 00255: bare refnames outside branch_safety

**Status**: Not Started
**Created**: 2026-08-17
**Owner**: Claude (Opus 5)
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Plan 00254 found that a bare refname is AMBIGUOUS — git resolves a same-named tag
ahead of the branch, warning only on stderr — and fixed every branch-addressing git
call in `branch_safety.py`, where it was causing silent data loss.

The sweep of the rest of `src/` that followed found two more hits, both in
`utils/git_sync.py`, both advisory-only. They are recorded here rather than left in
a completed plan's supporting doc, because a finding inside an archived folder is a
finding that gets lost.

This plan exists to close that loop. It is small and low priority: nothing here can
destroy data.

## Goals

- No branch listing outside `branch_safety.py` returns `heads/<name>` for a
  tag-shadowed branch, so no advisory names a branch that does not exist as typed.
- Decide, once, whether a QA check should reject bare-refname git invocations.

## Non-Goals

- Not revisiting `branch_safety.py` — Plan 00254 fixed and tested it.
- Not fixing `_tree_of`: it is only ever called with `HEAD` and an `origin/...`
  ref, so it is not exposed. Checked, not assumed.

## Context & Background

From the Plan 00254 sweep (see
[00254's FINDINGS.md §7](../Completed/00254-delete-branch-tip-recheck-before-delete/FINDINGS.md)):

| Site                                                | Effect with a tag-shadowed branch                                                        | Severity |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------- | -------- |
| `utils/git_sync.py:440` (`_local_branch_upstreams`) | Keys become `heads/<name>`, so the gone-branch advisory names a branch nobody can act on | Low      |
| `utils/git_sync.py:464` (`_merged_branch_names`)    | Same, and the `git branch -d <name>` the advisory offers would fail as typed             | Low      |

No data loss: this is the SessionStart upstream advisory, which only prints
guidance. Both sides of the merged/not-merged comparison read the short name, so
they agree with each other and the classification stays right — it is the NAME shown
to the human, and the copy-pasteable command under it, that are wrong.

## Tasks

### Phase 1: Fix the two sites

- [ ] ⬜ **Task 1.1**: RED — a test with a branch shadowed by a same-named tag,
  asserting the gone-branch advisory names `<name>` and not `heads/<name>`. No
  fixture in that suite creates a tag today, which is why this was never caught.
- [ ] ⬜ **Task 1.2**: GREEN — read `%(refname)` and strip `refs/heads/`, the same
  change Plan 00254 made to `local_branches` and to its test helper.
- [ ] ⬜ **Task 1.3**: Check the rest of `git_sync.py` for callers that compare
  these names against ref names from another source, since a half-fix would
  desynchronise two listings that currently agree with each other.

### Phase 2: Decide whether a guard belongs here (DBF)

- [ ] ⬜ **Task 2.1**: Plan 00254 fixed 9 call sites by hand and left the rule in a
  docstring. Core Standard 15's corollary says a defect fixed by hand recurs.
  Decide whether `scripts/qa/` should reject a git invocation that passes a bare
  branch name where a ref is expected.
- [ ] ⬜ **Task 2.2**: If yes, implement it — and note the design problem up front:
  the check must distinguish a bare BRANCH name from `HEAD`, from an `origin/...`
  ref, and from `<name>@{upstream}`, which git only accepts in its short form. A
  guard that flags those is worse than no guard.
- [ ] ⬜ **Task 2.3**: If no, record why in writing, so the next person does not
  re-open the question from scratch.

## Dependencies

- Follows: Plan 00254 (Complete), which found these and fixed the dangerous ones.

## Success Criteria

- [ ] A tag-shadowed branch is named correctly in the upstream advisory
- [ ] The guard question is answered either way, in writing
- [ ] QA green, daemon restart RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed at the commit that adds this plan, from the Plan 00254 sweep.
