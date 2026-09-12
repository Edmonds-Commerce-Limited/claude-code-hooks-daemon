# Plan 00385: niggles ledger four

**Status**: In Progress
**Created**: 2026-09-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet

## Overview

Successor to Plan 00381, which closed with its single entry graduated to Plan
00383\. Per the niggles SOP a closed ledger does not stop the collecting: the
next niggle found opens a new one rather than being mentioned in passing.

A niggle is a small, specific, VERIFIED defect — something wrong now, recorded
the turn it is found, with the evidence that makes it checkable by someone who
was not there. An entry needing real design work is graduated to its own plan
with a pointer rather than grown here.

## Goals

- Every niggle found is recorded here in the turn it is found, with evidence.
- Each entry is either fixed here or graduated to a named plan with a pointer.

## Non-Goals

- Redesign. An entry needing design is graduated, not grown in place.
- A dumping ground for wishes. An entry must name something that is WRONG.

## Tasks

### Phase 1: Recorded niggles

- [ ] ⬜ **N1**: Two TRACKED documents link to an UNTRACKED file, so every
  fresh clone and every new worktree gets two dead links.
  `.claude/rules/ccy-supervisor-dogfooding.md` points at `../ccy/CLAUDE.md` and
  `CLAUDE/DocumentationStrategy.md` points at `../.claude/ccy/CLAUDE.md`. The
  target exists in this working copy but `git ls-files .claude/ccy/` does not
  list it — the directory's tracked contents are `.gitignore`, `Dockerfile`,
  `ccy.env` and `claude-supervise.py` only.
  Found while triaging QA output for issue #34: the worktree's `docs_qa` run
  reported both as `pointer-resolves` findings while the main checkout reported
  zero, and the difference is precisely that the worktree is a clean checkout.
  Advise severity, so nothing blocks today; the cost is that the main checkout
  can never see it, which is the worst place for a defect to hide. Either the
  file should be tracked, or the two pointers should stop promising it.
  **Not yet decided which**, and that is the open question: the file reads as
  the supervisor's own contract, and whether it belongs in the repository or
  stays a per-machine artefact is an ownership call, not a typo.

## Success Criteria

- [ ] Every entry above is fixed, or graduated to a named plan with a pointer
  recorded in this ledger.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  the entry records why it has none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Successor to Plan 00381 (Completed), per the niggles SOP in
  `CLAUDE/PlanWorkflow.md`.
