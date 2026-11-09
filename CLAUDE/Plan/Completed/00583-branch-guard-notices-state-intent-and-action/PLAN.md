# Plan 00583: branch guard notices state intent and action

**Status**: Complete
**Created**: 2026-11-09
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #192

## Overview

The branch guards exist so that work FINISHES (`BRANCH_LIMIT_PRINCIPLE`, `constants/branch_guard.py:9`). The
stop-guard deny says so, but the surfaces that name idle branches do not. The main-thread Stop context line built by
`_noisy_line()` (`core/branch_stop_gate.py`) is only "Idle branches at the noisy dormancy stage or later:
<names>.", and `branch-sweep` lists the same branches under "Dormant:" with an age and no next action. An agent read
that as a status report and left unfinished work branches in place across many stops. The `wip.cap` deny's fix text
(`handlers/pre_tool_use/branch_creation_guard.py:64`) offers "or continue in one of them" as an exit, which reads as
a way past the cap rather than a demand to finish open work.

This is the first concrete case of the message standard Plan 00582 will write down: every guard surface says why it
fired and what to do next. Plan 00560 reuses the `BRANCH_LIMIT_PRINCIPLE` text in its own message shape, so the
principle's text is reused unchanged here.

## Goals

- The Stop-context dormancy line carries the principle, names each branch's next action (finish and merge, park with
  a reason, or delete when the guard proves nothing is lost), and says the session should take that work on.
- `branch-sweep`'s "Dormant:" section gives each branch its next command, and the section states the principle once.
- The `wip.cap` deny demands finishing open work first; "continue in one of them" is no longer offered as a way past
  the cap.

## Non-Goals

- No change to thresholds, presets, caps or which branches are judged (Plan 00582 covers grandfathering).
- No change to the text of `BRANCH_LIMIT_PRINCIPLE` itself (shared with Plan 00560).

## Tasks

### Phase 1: Fix

- [x] ✅ **Task 1.1**: RED tests on the wording of each surface (Stop context line, `branch-sweep` Dormant section,
  `wip.cap` deny)
- [x] ✅ **Task 1.2**: GREEN, reusing `BRANCH_LIMIT_PRINCIPLE` and the existing per-branch command builders
- [x] ✅ **Task 1.3**: release-notes callout

### Phase 2: Delivery

- [x] ✅ **Task 2.1**: targeted QA, merge, verify CI, close #192

## Success Criteria

- [x] The new tests failed before the fix and pass after it, on all three surfaces (3 failed before, per
  `subagent-reports/261109-issue-192-implementer-sonnet.md`)
- [x] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
  (`018-branch-guard-notices-state-intent-and-action.md`)
- [x] Merged to main with green CI; #192 closed (main CI run 42682133539, full suite on 3.11/3.12/3.13, success on
  `43f1a9a98`, which includes the fix)

## Delivery & Milestones

- `d60da0fda`: the fix on all three surfaces, tests and release note; the branch then merged main in
  (`7d954f213`) and main fast-forwarded to that merge commit (targeted QA 42/42 on the branch, recorded in the
  completion journal entry)
- The first `main` CI run after the merge (42676054890) failed on a `provision.sh` shellcheck finding from Plan 00581,
  not from this plan; fixed in `43f1a9a98`, whose run 42682133539 (full suite) is green. #192 closed
