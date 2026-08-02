# Plan 00196: `absolute_path` acceptance tests assert an unreachable premise

**Status**: Not Started
**Created**: 2026-08-02
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Found during the v3.51.0 acceptance gate. Two of `absolute_path`'s
`get_acceptance_tests()` entries tell the tester to call `Read`/`Write` with a
RELATIVE `file_path` and expect the handler to deny. Neither can happen in
current Claude Code: the harness normalises `file_path` to an absolute path
before dispatching PreToolUse, so the daemon never receives the relative form.

The handler itself is correct and must stay — a direct socket probe of both
tools with a relative `file_path` returns `permissionDecision: deny` with the
right message. It remains valid defence-in-depth for any client that does send
a relative path. The defect is in the TEST, which asserts behaviour the harness
cannot produce.

This matters because the acceptance gate is BLOCKING. Left alone, every future
release run hits two apparent failures, and whoever runs it must re-derive this
whole diagnosis before deciding it is safe to proceed — exactly the kind of
false signal that erodes trust in a blocking gate.

## Goals

- The acceptance playbook produces no false failures for `absolute_path`.
- The handler's deny behaviour stays covered by something that actually runs.
- The reason is recorded in the code, so the next person does not re-derive it.

## Non-Goals

- Changing `absolute_path`'s matching logic. It is correct.
- Removing the handler. It still guards clients that send relative paths.

## Context & Background

Evidence gathered during the v3.51.0 run:

- Real `Write` with `file_path='some/relative/path.txt'` was ALLOWED and created
  `/workspace/some/relative/path.txt`.
- Real `Read` with a relative path returned Claude Code's own
  "File does not exist", not the handler's block.
- Writing relative `untracked/relpath_probe.py` produced a `qa_suppression`
  block reading `File: /workspace/untracked/relpath_probe.py` — proving the
  daemon receives the ABSOLUTE form.
- Socket probe of `Read` and `Write` with a relative `file_path` returns
  `deny` with the correct message in both cases.

## Tasks

### Phase 1: Retarget the tests

- [ ] ⬜ **Task 1.1**: Decide the correct classification for the two entries in
  `absolute_path.get_acceptance_tests()` — either retarget them at a path form
  the harness will not rewrite, or reclassify as VERIFIED_BY_LOAD with the
  reason recorded inline.
- [ ] ⬜ **Task 1.2**: Implement the decision, with a comment naming the
  harness normalisation so this is not re-litigated.

### Phase 2: Keep the deny path covered

- [ ] ⬜ **Task 2.1**: Confirm unit coverage asserts deny-on-relative for both
  `Read` and `Write`; add it if missing.
- [ ] ⬜ **Task 2.2**: Consider a socket-level acceptance test (the probe used
  above) so the deny path is exercised end to end against a live daemon.

### Phase 3: Verify

- [ ] ⬜ **Task 3.1**: Regenerate the playbook and confirm no `absolute_path`
  entry asserts an unreachable premise.
- [ ] ⬜ **Task 3.2**: Full QA; daemon restart RUNNING.

## Dependencies

- Related: Plan 00193 / 00194 (the v3.51.0 release during which this surfaced).

## Success Criteria

- [ ] A full acceptance run reports zero false failures for `absolute_path`.
- [ ] The deny-on-relative behaviour is still asserted by a test that runs.
- [ ] The harness-normalisation reason is recorded in the code.

## Risks & Mitigations

| Risk                                                   | Impact | Probability | Mitigation                                                                             |
| ------------------------------------------------------ | ------ | ----------- | -------------------------------------------------------------------------------------- |
| Reclassifying hides a future regression in the handler | Medium | Medium      | Task 2.1/2.2 keep the deny path asserted at unit and/or socket level before reclassing |
| Harness behaviour reverts and the test is wrong again  | Low    | Low         | Comment names the dependency, so the reason is visible when it next changes            |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Activity log lives in JOURNAL/. -->

- Raised by the v3.51.0 acceptance gate; handler verified correct by socket
  probe at the time of discovery.
