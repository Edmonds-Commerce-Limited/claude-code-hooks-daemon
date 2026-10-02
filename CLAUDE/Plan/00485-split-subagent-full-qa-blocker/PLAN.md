# Plan 00485: split subagent full qa blocker

**Status**: Not Started
**Created**: 2026-10-02
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_full_qa_blocker.py` is one module of
about 5,300 lines and 14 classes. The handler class itself starts 94% of the way down. Review rounds
on a module that size miss defects: N302 (a generic inline-code flag list reaching `grep -c`) sat in
it unnoticed.

This plan carries out the owner-delegated Fable ruling on ledger 00466 N96
([RULINGS-owner-delegated-fable.md](../00483-threat-model-conformance-audit/RULINGS-owner-delegated-fable.md#n96--subagent_full_qa_blockerpy-is-one-5301-line-handler)):
split the module along the class seams it already has, as a pure refactor.

The dedupe scout checked 46 live plans and 415 archived ones and found none covering this. Plan 00464
(shared command-directory resolver) and Plan 00469 (QA package dependency direction) are related
but scoped elsewhere.

## Goals

- Move the recognisers (`_Runner`, `_Launcher`, `_Output`, `_PythonHeredoc`, `_OptionGrammar`) into a
  `utils/full_qa_recognition/` package beside `shell_segmentation`.
- Where a recogniser duplicates the Plan 00464 script walk or the shared wrapper peeling, replace it
  with the shared one instead of moving it.
- Move behaviour-free tables (flag grammars, interpreter lists) to `constants`.
- Keep `_Verdict`, `_Operands`, `_Event`, the messages and the handler class in the handler module.

## Non-Goals

- No behaviour change. A verdict that differs before and after is a defect in the refactor.
- No fixes to recogniser defects found along the way; they go to the open niggles ledger.
- No change to the handler's config surface, rule IDs or priorities.

## Tasks

### Phase 0: Start condition

- [ ] ⬜ **Task 0.1**: Confirm no open branch has a diff on `subagent_full_qa_blocker.py` or its
  tests (`git branch -r` against `main`, per branch `git diff --stat`). If one does, wait for it to
  merge. The split renames nearly every line, so a concurrent branch would become a whole-file merge.

### Phase 1: Baseline

- [ ] ⬜ **Task 1.1**: Record the baseline: the full
  `tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker*.py` set and the handler's
  acceptance tests, green on `main`, with pass counts.
- [ ] ⬜ **Task 1.2**: Build a verdict corpus by running every command shape in those tests and the
  dangerous-invocation corpus through `matches`/`handle` on `main`, and save it under
  `untracked/scratch/`. Phase 3 replays it against the branch.

### Phase 2: Split

- [ ] ⬜ **Task 2.1**: Move the behaviour-free tables to `constants`.
- [ ] ⬜ **Task 2.2**: Move each recogniser into `utils/full_qa_recognition/`, one class per commit,
  with the test set green after each move.
- [ ] ⬜ **Task 2.3**: Where a recogniser duplicates the 00464 script walk or the shared wrapper
  peeling, call the shared code instead. Each replacement is its own commit, and the verdict corpus
  is replayed after it.

### Phase 3: Verify

- [ ] ⬜ **Task 3.1**: The test set is unchanged and green, and the verdict corpus is identical
  before and after.
- [ ] ⬜ **Task 3.2**: An independent Opus review of the branch, focused on any verdict that could
  change.
- [ ] ⬜ **Task 3.3**: Merge with the coordinator's invariant suites run by hand (ledger 00474 N310).

## Success Criteria

- [ ] The handler module holds the handler class, `_Verdict`, `_Operands`, `_Event` and the messages.
  The recognisers live in `utils/full_qa_recognition/`.
- [ ] The test files are unchanged, apart from import paths, and green.
- [ ] Replaying the verdict corpus gives no differences.
- [ ] The module-size report from ledger 00474 N314 shows the handler module under its bound.

## Delivery & Milestones

- <!-- delivery commit hashes go here -->
