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

- [x] ✅ **N1**: Two TRACKED documents link to an UNTRACKED file, so every
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
  **Decided on evidence, and only one branch was actually available.** Tracking
  the file is impossible, not merely unattractive: `.claude/ccy/.gitignore`
  records in its own comment that `CLAUDE.md` is deliberately not whitelisted
  because ccy's startup gate refuses to launch when anything in `.claude/ccy/`
  is tracked, and prescribes a history rewrite plus a force push as the only
  remedy (the defect report for the ccy maintainers is
  `untracked/fedora-desktop-ccy-CLAUDE-bug.md`). Rewriting the file in place was
  ruled out too — it is bind-mounted as `/root/.claude/CLAUDE.md`, the owner's
  GLOBAL instructions for every project, so editing it here would change
  unrelated projects' behaviour.
  So the repo side moved instead: the contract now lives at
  `CLAUDE/development/CcySupervisor.md`, registered in the development routing
  table, and both pointers target it. The `registered_module_docs` entry stays
  (it keeps R7d from reading the local file as a routing table) with its comment
  corrected — it no longer claims to be the canonical home.
  The general lesson, worth more than the fix: **a canonical home must be one
  the reader actually receives.** An untracked canonical is invisible exactly
  where the reader most needs it, and invisible to the checkout that would
  report it.
  No release-bound consequence: every file touched is repo-internal. The rule
  file is not a shipped artefact — nothing under `src/` references it, and the
  daemon restart left the edit intact rather than regenerating over it.

- [x] ✅ **N2**: A plan opened FROM a GitHub issue did not record the issue
  number, so the issue stayed open for three days after being fixed and the
  reporter was never told.
  `CLAUDE/Plan/CLAUDE.md` requires `**GitHub Issue**: #N` in the header of any
  plan that originates from an issue, and requires commenting and closing it on
  completion. Plan 00365's Delivery section says only "Filed from the field
  report the day after v3.63.0 shipped" — no number.
  The evidence is exact: issue #36 was filed at `2026-09-09T16:25:38Z`, the fix
  landed in `a8111e72` at `2026-09-09T16:43:34+00:00`, and the plan was archived
  at `17:02:27` the same day. Eighteen minutes from report to fix, then three
  days of silence, because the one field that closes the loop was never filled
  in. Found while triaging #36 under the issue-SDLC loop, which re-derived from
  scratch what the plan already knew.
  Nothing enforces the convention — it is prose in a directory `CLAUDE.md`, and
  a plan citing "a field report" in prose reads as compliant.
  **Fixed on both halves, and the systemic half needed no new guard.** The
  record is corrected: Plan 00365 now carries `**GitHub Issue**: #36` and says
  in its Delivery section why the omission mattered (an archived plan was edited
  deliberately, which `archive-immutability` advises on rather than forbids).
  Issue #36 is commented and closed.
  A plan-header lint was considered and deliberately NOT built. The systemic
  risk — a fixed issue sitting open because a plan forgot to name it — is
  already covered by the hourly issue-SDLC loop from Plan 00384, which re-triages
  every open issue against current `main`. That is not a theory: the loop is
  exactly what found this one, three days later, by re-deriving from scratch
  what Plan 00365 already knew. A heuristic guard on plan prose would be noisier
  and would still only fire at plan-write time, whereas the loop catches the
  case no matter how the issue was orphaned. The same sweep closed #27 and #28
  for the same reason.
  No release-bound consequence: nothing shipped changed. The only edits are a
  plan record and three GitHub issue closures.

## Success Criteria

- [ ] Every entry above is fixed, or graduated to a named plan with a pointer
  recorded in this ledger.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  the entry records why it has none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Successor to Plan 00381 (Completed), per the niggles SOP in
  `CLAUDE/PlanWorkflow.md`.
