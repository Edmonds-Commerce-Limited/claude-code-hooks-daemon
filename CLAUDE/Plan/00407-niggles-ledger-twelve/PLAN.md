# Plan 00407: niggles ledger twelve

**Status**: In Progress
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The open niggles ledger. Small defects get recorded here the turn they are
found, so that noticing something and doing something about it are never the
same decision. Ledger eleven
([Plan 00405](../Completed/00405-niggles-ledger-eleven/PLAN.md)) is complete, so
this one opens.

An entry is either fixed in place, ruled NOT A DEFECT with the evidence that
settles it, or graduated to its own plan when the fix turns out to be a ruling
rather than an edit.

## Goals

- Every niggle found is written down with the evidence that makes it checkable
  by someone who was not there.
- Each entry reaches a terminal state: fixed, ruled not-a-defect, or graduated.

## Non-Goals

- Fixing anything that needs an owner ruling — that graduates to its own plan.

## Tasks

- [ ] ⬜ **N1**: two documents each claim the FIRST action of `/release`, and
  obeying them in the documented order makes the documented stop unreachable.

  **Found**: a human `/release` on a tree whose slate gate was not clean.

  `RELEASING.md` ("The release state file") says `/release` MUST write
  `untracked/release-state.json` as its **first action**. The skill's own
  `invoke.sh` output says Stage 0, the slate-clean gate, is what you
  `Run this yourself, in the main thread, first` — **before any agent is
  spawned**. Both say "first"; only one can be.

  Taking `RELEASING.md` literally writes the state file, and then Stage 0
  returns exit 2 with an explicit instruction: stop, show the human the report,
  end the turn with `STOPPING BECAUSE: [awaiting-human] the release slate is not clean`, and do NOT proceed. That stop is then **denied by the `release_blocker`
  Stop handler**, because a state file exists and its `last_completed_step` is 0.

  The handler's own route out is to DELETE the state file, which it correctly
  describes as *the abort action, not a pause button*. So the slate gate's
  documented outcome — "a human decides, and re-invokes `/release auto accept-wip`" — cannot be reported as written. It has to be reported as an
  ABORT, and the recorded authorisation is destroyed on the way.

  **Why it is worth an entry.** The two outcomes are not the same thing. "Paused
  at a gate that defers to you" and "aborted" read differently to whoever finds
  the transcript, and only one of them is what happened. The fix is a precedence
  sentence rather than new machinery: Stage 0 runs BEFORE the state file is
  written, because a release that never cleared the slate gate was never in
  flight, and writing the authorisation first is what manufactures the deadlock.

  A candidate remedy, NOT yet ruled on: make `release_blocker` stand down when
  `last_completed_step` is 0 — nothing has been changed at that point, so there
  is no half-done release to protect. That is the state the guard exists to
  prevent, and step 0 is definitionally not it.

## Success Criteria

- [ ] 🔄 Every entry above is in a terminal state: fixed, ruled NOT A DEFECT
  with the evidence, or graduated to its own plan.
- [ ] 🔄 Full QA passes and CI is green for every entry closed.

## Delivery & Milestones

- Opened by N1, which was found by USING the release pipeline rather than by
  reading it — the contradiction is invisible until both documents are obeyed
  in the same run, and each is correct read on its own.
