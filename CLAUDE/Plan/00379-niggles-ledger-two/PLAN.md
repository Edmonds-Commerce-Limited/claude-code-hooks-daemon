# Plan 00379: niggles ledger two

**Status**: In Progress
**Created**: 2026-09-11
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The successor to Plan 00377, which closed with all eleven entries resolved.
Per the niggles SOP, closing a ledger does not stop the collecting: the next
niggle found opens a new ledger rather than being reported in passing. This is
that ledger.

A niggle is a small, specific, verified defect — something that is wrong now,
not something that could be nicer. Each entry is recorded the turn it is
found, with the evidence that makes it checkable by someone who was not there.
An entry that turns out to need real design work is graduated to its own plan
with a pointer, rather than being grown inside this one.

The first three entries share a theme worth naming: all were found by
VERIFYING a claim rather than by hitting a symptom. N1 surfaced when a test
failed on the third consecutive commit that had already broken the rule; N2
and N3 surfaced when the line numbers in a Not Started plan were checked
against the files they cite. A claim nobody rechecks is where these hide.

## Goals

- Every niggle found is recorded here in the turn it is found, with evidence.
- Each entry is either fixed here or graduated to a named plan with a pointer.

## Non-Goals

- Redesign. An entry needing design is graduated, not grown in place.
- A dumping ground for wishes. An entry must name something that is WRONG.

## Tasks

### Phase 1: Recorded niggles

- [ ] ⬜ **N1**: The plan-index retention window has no commit-time gate. The
  30-row ceiling is enforced only by
  `tests/integration/test_plan_index_navigability.py::test_completed_rows_stay_within_the_retention_window`,
  which runs in full QA. Plan QA has a COMMIT-stage `terminal_state_atomic`
  check that makes archiving atomic, and `CLAUDE/Plan/CLAUDE.md` names the
  age-out as part of that same atomic commit — but no check enforces it. Three
  consecutive archival commits (00375, 00377, 00378) each added a row without
  ageing one out, reaching 33 rows, and `plan-qa --sweep` reported 0 findings
  throughout. Evidence: fixed in `1f00eab8`; the gap that let it happen three
  times is what this entry is about, not the row count.

- [ ] ⬜ **N2**: Plan 00376 Task 3.1 describes a compound condition as if it
  were one branch. `scripts/upgrade_version.sh:808` reads
  `[[ "$*" == *"--skip-reading-confirmation"* ]] || [ ! -t 0 ]` — two skip
  paths. The explicit flag is a deliberate opt-out that should survive; only
  the `[ ! -t 0 ]` TTY inference is the bug. As worded ("the current
  `[ ! -t 0 ]` branch at `upgrade_version.sh:808` is the bug to fix"), an
  implementer could remove both and delete a legitimate escape hatch.

- [ ] ⬜ **N3**: Plan 00376 Task 4.3 states
  `.claude/skills/hooks-daemon/upgrade.md` "never mentions post-upgrade
  tasks". That is false: line 108 says "follow any referenced post-upgrade
  task". The SUBSTANCE of the task still stands — that mention is a passing
  reference inside the config-advisory step, and there is still no step
  directing the agent to read the post-upgrade tasks for the versions it just
  crossed. But an implementer grepping `post-upgrade` finds line 108, reads
  the claim as stale, and closes the task as already-done.

- [ ] ⬜ **N4**: The Plan Statistics reconciliation carried an arithmetic check
  that contradicted its own paragraph. It stated **365** distinct plan numbers
  and **13** folderless of **378** allocated, then verified with
  `364 + 13 = 377. ✅` — both terms off by one, and the ✅ asserting a sum that
  does not hold. The folder counts either side of it were correct
  (15 + 340 + 13 = 368 verified from disk), so the error was confined to the
  self-check that exists precisely to catch this. Found while updating the
  block for 00379's birth; the figures are corrected in the same commit, but
  `stats_recount` validates the counts and not the prose sum, which is why a
  wrong ✅ survived a clean `plan-qa --sweep`.

## Success Criteria

- [ ] Every entry above is fixed, or graduated to a named plan with a pointer
  recorded in this ledger.
- [ ] `CLAUDE/UPGRADES/UNRELEASED/` is current for any entry whose fix changes
  behaviour a user would notice.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Successor to Plan 00377 (Completed), per the niggles SOP in
  `CLAUDE/PlanWorkflow.md`.
