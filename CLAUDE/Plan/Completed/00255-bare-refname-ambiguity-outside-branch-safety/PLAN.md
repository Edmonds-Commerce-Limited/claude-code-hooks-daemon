# Plan 00255: bare refnames outside branch_safety

**Status**: Complete
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
`utils/git_sync.py`. They are recorded here rather than left in a completed plan's
supporting doc, because a finding inside an archived folder is a finding that gets
lost.

The plan was filed calling those hits cosmetic — and they were. Executing the
sweep the plan asked for (Task 1.3) found a third site in the same function that
is not: the BASE the merged/not-merged comparison is measured against is also a
bare name, so a tag can make git answer about the tag and a branch holding unique
commits gets reported as safe to delete. The daemon still deletes nothing, but the
advisory tells a human to — so "nothing here can destroy data", as filed, was too
generous, and this plan is where that got corrected.

## Goals

- No branch listing outside `branch_safety.py` returns `heads/<name>` for a
  tag-shadowed branch, so no advisory names a branch that does not exist as typed.
- Decide, once, whether a QA check should reject bare-refname git invocations.

## Non-Goals

- Not revisiting `branch_safety.py`'s LOGIC — Plan 00254 fixed and tested it. Its
  `branch_ref`/`HEADS_PREFIX` did move into `utils/git_repo.py` so both callers
  share one copy (Task 1b.1); that is an extraction, not a re-litigation.
- Not fixing `_tree_of`: it is only ever called with `HEAD` and an `origin/...`
  ref, so it is not exposed. Checked, not assumed.

## Context & Background

From the Plan 00254 sweep (see
[00254's FINDINGS.md §7](../00254-delete-branch-tip-recheck-before-delete/FINDINGS.md)):

| Site                                                | Effect with a tag-shadowed branch                                                        | Severity |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------- | -------- |
| `utils/git_sync.py:440` (`_local_branch_upstreams`) | Keys become `heads/<name>`, so the gone-branch advisory names a branch nobody can act on | Low      |
| `utils/git_sync.py:464` (`_merged_branch_names`)    | Same, and the `git branch -d <name>` the advisory offers would fail as typed             | Low      |

No data loss from those two: this is the SessionStart upstream advisory, which only
prints guidance. Both sides of the merged/not-merged comparison read the short name,
so they agree with each other — it is the NAME shown to the human, and the
copy-pasteable command under it, that are wrong.

The third site, found by the Task 1.3 sweep rather than filed with the plan, is a
different severity:

| Site                                                | Effect with a tag named after the DEFAULT branch                                                                                      | Severity |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| `utils/git_sync.py` `_merged_branch_names` base arg | `branch --merged main` answers about the TAG, so a branch with unique commits is reported merged and the advisory offers to delete it | Medium   |

## Tasks

### Phase 1: Fix the two sites

- [x] ✅ **Task 1.1**: RED — a test with a branch shadowed by a same-named tag,
  asserting the gone-branch advisory names `<name>` and not `heads/<name>`. No
  fixture in that suite creates a tag today, which is why this was never caught.
- [x] ✅ **Task 1.2**: GREEN — read `%(refname)` and strip `refs/heads/`, the same
  change Plan 00254 made to `local_branches` and to its test helper.
- [x] ✅ **Task 1.3**: Check the rest of `git_sync.py` for callers that compare
  these names against ref names from another source, since a half-fix would
  desynchronise two listings that currently agree with each other.
  - [x] ✅ `upstream` stays SHORT deliberately — it is compared against the short
    refs `git remote prune --dry-run` prints, so both sides must agree.
  - [x] ✅ `@{upstream}` (x2), `symbolic-ref refs/remotes/origin/HEAD` and
    `show-ref --verify refs/heads/<candidate>` are already unambiguous.
  - [x] ✅ `check_git_history.py:413` reads `%(refname:short)` and is NOT a
    defect: it scans ref names for blocked terms as SUBSTRINGS, and the
    disambiguating prefix never removes the term.
- [x] ✅ **Task 1.4** (found by Task 1.3, worse than the filed bug): the BASE
  passed to `git branch --merged` is a bare name from `default_branch`, so a tag
  named `main` makes git answer about the tag — a branch holding unique commits
  is reported MERGED and the advisory offers `git branch -d` on it. Fixed via
  `_merged_base_ref`, which qualifies to `refs/heads/<base>` and falls back to
  the bare name when no local branch of that name exists.

### Phase 1b: One home for the rule (DRY)

- [x] ✅ **Task 1b.1**: `branch_ref` + `HEADS_PREFIX` moved from
  `daemon/branch_safety.py` into `utils/git_repo.py` (which `branch_safety`
  already imports from), joined by a new `strip_branch_ref` for the read side.
  Both modules now share one copy instead of holding two that can drift.

### Phase 2: Decide whether a guard belongs here (DBF)

- [x] ✅ **Task 2.1**: Decided — YES for the READ side, NO for the write side.
  See Decision 1.
- [x] ✅ **Task 2.2**: Implemented as a semgrep rule,
  `scripts/qa/semgrep/short-refname.yaml`. The runner picks up any `*.yaml` in
  that directory with no wiring, so it joined the QA suite as a file.
- [x] ✅ **Task 2.3**: The write-side refusal is recorded in Decision 1 and
  restated in the rule file itself, where the next person meets it.

## Dependencies

- Follows: Plan 00254 (Complete), which found these and fixed the dangerous ones.

## Technical Decisions

### Decision 1: Guard the READ side only, and say so out loud

**Context**: Task 2.1 asked whether QA should reject a git invocation that
passes a bare branch name. The defect has now recurred once (00254 fixed it in
`branch_safety.py`; 00255 found three more sites in `git_sync.py`), and Core
Standard 15 says a defect fixed by hand recurs — so the question is not whether
a guard is warranted but which guard is possible.

**Options considered**:

1. **Reject bare branch names in git argv.** Measured against the real defects,
   this catches NOTHING. Every one of the 12 fixed call sites passes a
   *variable* (`base`, `name`, `rev`), and no syntactic rule can see whether a
   variable holds a branch name, `HEAD`, or `origin/main`. It would fire only on
   hardcoded literals — which in this tree are the already-correct ones
   (`show-ref --verify refs/heads/{candidate}`). A guard with no true positives
   and a live false-positive rate gets disabled within a day.
2. **Reject `%(refname:short)` in a git format string.** Mechanically checkable,
   a named replacement exists to point at (`strip_branch_ref`), and validated
   against the real pre-fix source: it flags both `git_sync.py` sites and would
   have flagged 00254's `local_branches`.
3. **Behaviour tests that shadow every branch with a same-named tag.** Catches
   both sides, because it exercises behaviour rather than syntax — but needs a
   fixture per call site rather than one rule.

**Decision**: Option 2 as the automated gate, Option 3 by hand where the
consequence is severe (the three tests added here, plus 00254's). Option 1 is
refused on evidence, not on taste. The rule file states its own scope so the
next reader is not misled into thinking the write side is covered — a guard that
overstates its reach is worse than one that admits a gap.

**Validation** (run before accepting the rule): 4/4 probe shapes flagged, the
docstrings that *describe* the defect not flagged, both real pre-fix sites
flagged exactly once, current tree clean across 388 files.

### Decision 2: `check_git_history.py` is excluded, with a reason

**Context**: the one remaining `%(refname:short)` in the tree.

**Decision**: excluded in the rule, not rewritten. It sweeps
`refs/heads` + `refs/tags` + `refs/remotes` together looking for blocked terms,
and a term is matched as a SUBSTRING — the disambiguating prefix adds
characters, never removes them, so the scan cannot miss. The name it prints is
for a human to read, not for a command to consume. Verified the exclusion is
load-bearing (the rule does fire on that line without it) rather than assumed.

## Success Criteria

- [x] A tag-shadowed branch is named correctly in the upstream advisory
- [x] A tag-shadowed DEFAULT branch cannot flip the merged/not-merged verdict
- [x] The guard question is answered either way, in writing
- [x] QA green, daemon restart RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed at the commit that adds this plan, from the Plan 00254 sweep.
- Delivered and archived in the commit that adds
  `scripts/qa/semgrep/short-refname.yaml`.
