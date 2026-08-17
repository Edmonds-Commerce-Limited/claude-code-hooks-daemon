# Plan 00249: delete-branch crashes on a branch merged into main but ahead of its own upstream

**Status**: Complete
**Created**: 2026-08-17
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

A field bug report from a real client repo (`FIELD-REPORT.md` in this folder,
reproduced there against v3.53.1): `hooks-daemon delete-branch` crashes with a
raw traceback on a branch that is fully merged into `main` but sits one commit
ahead of its own remote-tracking ref.

The two halves of the tool contradict each other. `--dry-run` reports
**"merged — nothing can be lost"**; the real run then fails and deletes nothing.
A tool whose whole purpose is to decide safely, and to say so clearly, instead
produces a stack trace.

Reproduced here from first principles rather than taken on trust — a bare
"remote", a clone, a pushed branch, one unpushed commit, then a local
`merge --no-ff` into `main`:

```
$ git merge-base --is-ancestor feature main && echo "merged into main"
merged into main

$ git branch -d feature
warning: not deleting branch 'feature' that is not yet merged to
         'refs/remotes/origin/feature', even though it is merged to HEAD.
error: The branch 'feature' is not fully merged.
```

## The two predicates are not the same predicate

`classify_branch` proves `merged` as *"the tip is an ancestor of the protected
ref"* — a proof about RECOVERABILITY. `git branch -d` enforces *"merged into its
upstream if it has one, into HEAD otherwise"* — a heuristic about PUBLICATION.
Git's own warning says the quiet part out loud: *"even though it is merged to
HEAD"*. It knows the daemon's check passes, and refuses anyway.

`delete_argv_for_tier` chose the safe delete for the `merged` tier on the
explicit and well-argued grounds that *"git then re-runs its own merged-ancestry
check independently of ours, so a bug in `classify_branch` cannot cause a silent
loss"*. That reasoning is sound; the premise that git runs *the same check* is
not.

Note which way round the strength runs here. Ancestry to `main` means every
commit on the branch is reachable from `main`, so nothing can be lost — a
complete proof. The upstream ref being stale says only that a push did not
happen, which is not a fact about preservation at all. Any commit that is ahead
of the upstream and NOT in `main` would fail the ancestry test and never reach
this tier in the first place.

## Goals

- A branch of this shape is classified as what it is, so `--dry-run` and the real
  run agree — the contradiction is the substantive bug.
- No git refusal reaches a user as a traceback.
- The all-or-nothing promise in `delete_branches`'s docstring is either kept or
  corrected to what the code actually guarantees.
- A failed run does not leave a recovery bundle implying a deletion happened.

## Non-Goals

- Widening the `merged` tier to use `--force`. That erodes the guarantee the
  tier exists to provide; the shape gets its own tier instead, so the proof
  stays explicit.
- Any change to the human gate on abandoning unproven work.

## Tasks

### Phase 1: Make the diagnosis reproducible in the suite

- [x] ✅ **Task 1.1**: A fixture building the exact shape — a bare remote, a
  clone, a pushed branch, one unpushed commit, and a local `merge --no-ff`
  - [x] ✅ Assert the precondition git enforces, so the fixture cannot silently
    stop reproducing it: `-d` refuses while ancestry to the protected ref holds

### Phase 2: Model the upstream condition (the substantive fix)

- [x] ✅ **Task 2.1**: Detect "merged into the protected ref, but ahead of its
  own upstream" in `classify_branch` and give it its own tier
- [x] ✅ **Task 2.2**: `delete_argv_for_tier` handles the new tier, with the
  reasoning recorded: the ancestry proof is complete, so the obstacle is git's
  publication heuristic and not a gap in the proof
- [x] ✅ **Task 2.3**: The dry run names the tier and what will happen, so the
  two halves of the tool agree

### Phase 3: No refusal becomes a traceback

- [x] ✅ **Task 3.1**: Delete with `check=False` and report git's own stderr
  alongside the tier that was proven
- [x] ✅ **Task 3.2**: Pre-flight every branch before mutating any, so the
  all-or-nothing promise holds for the common case; report truthfully what was
  deleted if a later delete still fails, and correct the docstring to match
- [x] ✅ **Task 3.3**: Remove the recovery bundle when nothing was deleted — an
  orphaned 1.9 MB bundle reads as evidence a branch is gone

### Phase 4: Verify

- [x] ✅ **Task 4.1**: Full QA green, daemon restart RUNNING
  - [x] ✅ `12466 passed, 0 failed, 6 skipped | coverage: 95.1%`, every other
    check 0 violations; daemon RUNNING (PID 1757054) on the new code
- [x] ✅ **Task 4.2**: Verified against the reporter's scenario end to end, and
  moved the field report into this folder rather than leaving it in `untracked/`
  - [x] ✅ Built the shape in a throwaway repo and ran the production wrapper:
    the dry run names `merged-unpushed` and the condition, the real run deletes
    the branch, and the two now agree
  - [x] ✅ Also updated the resident guidance: `destructive_git`'s
    `get_claude_md()` and `docs/guides/HANDLER_REFERENCE.md` both described
    `git branch -d` as refusing only on severed ancestry, which is the exact
    misunderstanding this plan is about

## Dependencies

- Overlaps: Plan 00248 F1, which already stopped `cmd_delete_branch` turning a
  `CalledProcessError` into a traceback. That fix catches this crash at the
  outermost layer; this plan removes the cause and makes the report specific.

## Technical Decisions

### Decision 1: a distinct tier, not a wider `merged`

**Context**: the branch's content IS in `main`, so `--force` would lose nothing
here, and simply making the `merged` tier force-delete would fix the crash in
about one line.

**Decision**: give the shape its own tier. `delete_argv_for_tier` deliberately
reserves the force flag for tiers where ancestry is severed, and the value of
that is that a reader can see WHICH proof licensed the force. Widening `merged`
would silently convert the one tier that delegates to git's independent check
into one that overrides it — losing the property the tier was designed around,
for every branch, to fix one shape.

**Date**: 2026-08-17

### Decision 2: reproduce the git behaviour rather than cite it

**Context**: the report quotes git's warning but notes the manual could not be
re-read on the reporting machine.

**Decision**: build the shape locally and observe the refusal directly before
writing any fix — done, and it matches the report exactly. The regression test
then builds the same shape, so the fix is pinned to git's actual behaviour rather
than to a paraphrase of it that a future git could invalidate silently.

**Date**: 2026-08-17

## Success Criteria

- [x] `--dry-run` and the real run agree on a branch of this shape
- [x] The reporter's branch shape deletes cleanly, or refuses with a message
  naming git's condition and the remedy — verified through the production
  wrapper: the dry run names `merged-unpushed` and the condition, the real run
  deletes it
- [x] No traceback reaches a user from a git refusal
- [x] No bundle is left behind by a run that deleted nothing
- [x] QA green (12466 passed, 95.1% coverage), daemon restart RUNNING

## Risks & Mitigations

| Risk                                                       | Impact | Probability | Mitigation                                                                                |
| ---------------------------------------------------------- | ------ | ----------- | ----------------------------------------------------------------------------------------- |
| A new tier that force-deletes weakens the safety guarantee | High   | Low         | The tier requires the SAME ancestry proof as `merged`; it changes no proof, only the flag |
| Detecting the upstream adds a git call per branch          | Low    | Medium      | One `rev-parse` per branch, on a CLI command a human runs deliberately                    |
| Pre-flighting changes the human-gate ordering              | Medium | Low         | Classification already happens before any mutation; only the delete loop moves            |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed at the commit that adds this plan.
- Delivered at `a74b0489`, jointly with Plan 00248 — both touch
  `branch_safety.py`'s `_git` runner, so splitting by file would have left a
  commit whose own tests fail.
