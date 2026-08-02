# Plan 00196: `absolute_path` acceptance tests assert an unreachable premise

**Status**: Complete
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

## Technical Decisions

### Decision 1: Neither original option is available; add a skip-with-reason field

**Context**: Task 1.1 offered two routes — retarget at a path form the harness
will not rewrite, or reclassify as VERIFIED_BY_LOAD. Investigation killed both.

**Options Considered**:

1. *Retarget at a surviving path form* — DEAD. Claude Code normalises
   `file_path` to absolute before PreToolUse dispatch. Verified for the plain
   relative form (v3.51.0 evidence below) and for `~/...`, which was expanded
   and read successfully rather than blocked. No relative form survives.
2. *Reclassify as VERIFIED_BY_LOAD* — DEAD. That bucket is not a `TestType`
   value; `playbook_generator` derives it from the EVENT TYPE (anything outside
   SessionStart/UserPromptSubmit/PostToolUse). A PreToolUse handler marked
   `TestType.CONTEXT` renders as "OBSERVABLE — check system-reminders", which is
   actively wrong.
3. *Delete the two tests* — FORBIDDEN. `Handler.get_acceptance_tests()`
   documents "Every handler MUST define at least one acceptance test. Returning
   an empty list is NOT ALLOWED and will be rejected during validation."

**Decision**: Add an `AcceptanceTest.harness_cannot_produce` field carrying the
reason. When set, the playbook renders the test as SKIP with that reason instead
of asking the tester to run it. This generalises the VERIFIED_BY_LOAD *idea*
(trust the daemon + unit tests) so it can apply to a handler whose event type
makes the existing bucket unreachable, and it puts the explanation where the
release tester actually looks. Rendering is shared with the existing
`required_tools` skip via one helper, so there is a single skip code path.

**Date**: 2026-08-02

## Tasks

### Phase 1: Retarget the tests

- [x] ✅ **Task 1.1**: Decide the correct classification for the two entries in
  `absolute_path.get_acceptance_tests()`. Resolved by Decision 1 — both offered
  routes are unavailable; a skip-with-reason field is the third path.
- [x] ✅ **Task 1.2**: Implement `harness_cannot_produce` (field, shared skip
  rendering, both playbook call sites) and set it on the two entries with a
  reason naming the harness normalisation, so this is not re-litigated.

### Phase 2: Keep the deny path covered

- [x] ✅ **Task 2.1**: Confirm unit coverage asserts deny-on-relative for both
  `Read` and `Write`; add it if missing. Already covered for Read, Write AND
  Edit (`matches()` + `handle()`) — nothing was missing.
- [x] ✅ **Task 2.2**: Consider a socket-level acceptance test (the probe used
  above) so the deny path is exercised end to end against a live daemon. Added
  `tests/acceptance/test_absolute_path_socket_deny.py` — 3 deny assertions plus
  3 absolute-path negative controls, so a deny-everything handler cannot pass.

### Phase 3: Verify

- [x] ✅ **Task 3.1**: Regenerate the playbook and confirm no `absolute_path`
  entry asserts an unreachable premise. Both render as SKIP with the reason;
  the unrunnable commands appear nowhere in the playbook.
- [x] ✅ **Task 3.2**: Full QA; daemon restart RUNNING. QA 14/14, 10,814 tests,
  coverage 95.3%.

## Dependencies

- Related: Plan 00193 / 00194 (the v3.51.0 release during which this surfaced).

## Success Criteria

- [x] A full acceptance run reports zero false failures for `absolute_path`.
- [x] The deny-on-relative behaviour is still asserted by a test that runs.
- [x] The harness-normalisation reason is recorded in the code.

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
- Delivered post-v3.51.0: `AcceptanceTest.harness_cannot_produce` +
  `_skip_block()` shared skip rendering, both `absolute_path` entries marked,
  `tests/acceptance/test_absolute_path_socket_deny.py` added. Two stale
  `$PYTHON` skip messages in `tests/acceptance/` fixed en route.

## Follow-up Raised (not actioned)

`check_python_var_guidance.py` does not scan `tests/`, which is how the two
`$PYTHON` skip messages survived the Plan 00193 sweep. Adding the root wholesale
would need ~10 whole-file exemptions for legitimate regression guards that quote
the banned pattern to assert against it — the checker's own notes warn that "a
path exemption silences a whole file; prefer a rule that can tell the two
apart". Open question for a future plan: whether a narrower rule (guidance
strings only, e.g. `pytest.skip`/`print` bodies) can cover `tests/` without the
exemption sprawl. Recorded rather than actioned unilaterally.
