# Plan 00243: Make the Acceptance Playbook Deterministically Executable

**Status**: In Progress
**Created**: 2026-08-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

RELEASING.md Step 12 is the most expensive gate in the release process: a
human executes ~169 playbook tests by hand, in a real Claude Code session, and
any fix forces a full restart from Test 1.1. Step 12.0 already carries a
deterministic sub-gate (23 pytest cases against the production install and
diagnostic paths), so the pattern is established — it just stops well short of
the playbook itself.

During the v3.53.0 release an ad-hoc script drove the playbook against the
PRODUCTION hook wrapper (`.claude/hooks/pre-tool-use`) as a subprocess, with
the event JSON on stdin — the same technique
`tests/acceptance/test_stop_hook_hard_block.py` already uses for the Stop
wrappers. It exercised the real bash forwarder to socket to daemon to
handler-chain path. Measured against a freshly generated playbook: **207 blocks
parsed, 38 skipped as load/observable, 169 executed, 120 matching the
playbook's own Expected Decision.**

The 49 that did not match are **not daemon failures**. They are tests whose
`command` field is English prose rather than a shell command — "Use the Write
tool to write file_path='...' with content '...'". The script tried to
reconstruct a `Write`/`Edit` payload from that prose with regexes, and where
the phrasing differed (`with content '...'` vs `content='...'`) it fell back to
sending the prose as a Bash command, which of course nothing denies.

That distinction is the whole plan. A harness that reports 49 false failures
gets switched off within a day — the same fate Plan 00241 Phase 2 explicitly
avoided when its first guard flagged 23 handlers.

## Goals

- Shrink the manual Step 12 surface to only the tests that genuinely require a
  human in a real session
- Make a non-executable test report as SKIPPED with a reason, never as FAILED
- Keep the harness on the PRODUCTION wrapper path, not a direct socket call

## Non-Goals

- Replacing Step 12 entirely — some tests need a real session and must stay
- Changing what any handler decides
- Rewriting the playbook's human-readable rendering

## Context & Background

`AcceptanceTest` (`src/claude_code_hooks_daemon/core/acceptance_test.py`) has
five required fields — `title`, `command`, `description`, `expected_decision`,
`expected_message_patterns`. There is **no** structured payload field. So
`command` is overloaded: sometimes a literal shell command, sometimes an
English instruction describing a tool call. Nothing marks which, so a harness
must guess, and guessing is what produced the 49 false mismatches.

`harness_cannot_produce` already exists for a related purpose — a test Claude
Code cannot trigger at all — and its docstring is careful that it must not be
used for tests that are merely awkward. The gap here is different and needs its
own field: the behaviour IS triggerable, the `command` string just is not
machine-parseable.

**DBF — what should have caught this.** While verifying the above,
`CLAUDE/CodeLifecycle/Features.md` was found documenting
`AcceptanceTest(test_id=..., hook_input={...})` — two keyword arguments that do
not exist, and omitting three of the five required fields. An agent following
that documented example writes code that raises `TypeError` on construction.
The example was corrected by hand, but nothing would have caught it: no check
validates that a Python code block in `CLAUDE/**/*.md` constructs real symbols
with real keyword arguments. That guard is Phase 4, and it is the more durable
half of this plan.

## Tasks

### Phase 1: Make executability explicit rather than guessed

- [ ] ⬜ **Task 1.1**: Audit all `get_acceptance_tests()` implementations and
  classify each `command` as literal-shell or prose
- [ ] ⬜ **Task 1.2**: Convert to a literal command every prose test that can
  be one — the Write/Edit tests are the bulk, and a payload is expressible
- [ ] ⬜ **Task 1.3**: For the genuine remainder, add an explicit optional
  field declaring the tool and payload the test needs, so a harness reads it
  instead of regexing prose
  - [ ] ⬜ Keep it distinct from `harness_cannot_produce`, whose docstring is
    deliberately narrow
- [ ] ⬜ **Task 1.4**: Render the machine-readable form into the playbook
  alongside the prose, so `generate-playbook` stays readable for a human

### Phase 2: The harness

- [ ] ⬜ **Task 2.1**: Promote the ad-hoc script to `tests/acceptance/`
  - [ ] ⬜ `PROTOTYPE-playbook_exec.py` reads a playbook from
    `untracked/playbook.md`, which is a generated artefact and is NOT kept in
    the tree. Regenerate it first:
    `./bin/hooks-daemon generate-playbook > untracked/playbook.md`. The real
    harness should generate into a tmp path rather than depend on that file
  - [ ] ⬜ Drive the PRODUCTION wrapper as a subprocess, as
    `test_stop_hook_hard_block.py` does — never a direct socket call
  - [ ] ⬜ Skip cleanly when no daemon is running, matching the sibling file
- [ ] ⬜ **Task 2.2**: Report a non-executable test as SKIPPED with its reason
  - [ ] ⬜ A false FAILED is worse than no coverage; this is the lesson from
    Plan 00241 Phase 2's discarded 23-handler guard
- [ ] ⬜ **Task 2.3**: Assert `expected_message_patterns` too, not only the
  decision — a deny for the wrong reason is a passing test today
- [ ] ⬜ **Task 2.4**: Isolate every probe's `cwd` from the repo root
  - [ ] ⬜ Plan 00241 found two acceptance probes shadowed by `release_blocker`
    (terminal, priority 8) whenever the tree is dirty — which is exactly the
    state a release is in when Step 12 runs. Any new probe inherits that trap

### Phase 3: Shrink the manual gate

- [ ] ⬜ **Task 3.1**: Add the harness to RELEASING.md Step 12.0's pytest line
- [ ] ⬜ **Task 3.2**: Rewrite Step 12.4 to cover only what remains manual,
  and say plainly which tests the harness now owns
- [ ] ⬜ **Task 3.3**: State the residual honestly — no silent narrowing. If a
  test is neither automated nor manually executed, that must be visible

### Phase 4: The guard (DBF) — DELIVERED

- [x] ✅ **Task 4.1**: `scripts/qa/check_doc_snippets.py`, wired into
  `run_all.sh` (check 21) and `llm_qa.py`
  - [x] ✅ Ground truth is INTROSPECTED from the package, not restated — a
    renamed field changes what the check enforces on the same commit
  - [x] ✅ Four rules, each mechanically decidable: `unknown-keyword`,
    `positional-arg`, `unknown-import`, `missing-identifier`
  - [x] ✅ An unparseable snippet is SKIPPED, not failed — a doc written with
    `...` or `<placeholder>` cannot be judged, so no opt-out marker is needed
- [x] ✅ **Task 4.2**: Ran it across the docs; 8 real defects found and fixed
  - [x] ✅ Measured against those 8: the guard catches 5
  - [x] ✅ The 3 it misses are recorded in the check's own docstring as
    deliberately out of scope — a doc that re-declares a real class to
    describe its shape, a method call needing type inference, and missing
    required arguments generally (docs abbreviate, so that would fail on
    nearly every example in the tree)

### Phase 5: Remaining doc-snippet gap (optional, lower value)

- [ ] ⬜ **Task 5.1**: Decide whether a doc re-declaring a real class
  (`class HookResult:` under a heading naming `core/hook_result.py`) can be
  distinguished from an illustration without guessing. If it cannot, leave it
  — that is the correct answer, not a failure
- [ ] ⬜ **Task 5.2**: `Handler` has FOUR abstract methods. Measured across
  every scanned doc: **40 of 40** documented `Handler` subclass examples
  define only a subset, so NONE of them can be instantiated —
  `TypeError: Can't instantiate abstract class ... with abstract methods get_acceptance_tests, get_claude_md`. The canonical skeleton in `CLAUDE.md`
  is already fixed and verified by executing it verbatim; the remaining 39 are
  concentrated in `HANDLER_DEVELOPMENT.md` (13), `PROJECT_HANDLERS.md` (4),
  `ARCHITECTURE.md` (4) and `development/QA.md` (4)
  - [ ] ⬜ Decide per site: show all four, or state plainly that the example
    is partial. Blanket-editing 40 examples to add two stubs is mostly noise
  - [ ] ⬜ This is NOT catchable by `check_doc_snippets` — a partial example
    is legitimate documentation, so flagging it would be the "missing
    required arguments" false-positive trap in the check's own docstring

## Dependencies

- Related: Plan 00017 (created the manual playbook format), Plan 00025
  (`get_acceptance_tests()`), Plan 00040 (plugin handlers in the generator).
  All three are Complete and built the inputs; none built an execution harness
- Related: Plan 00241 (the `cwd` shadowing trap, and the precedent for
  rejecting a guard that reports false failures)

## Technical Decisions

### Decision 1: Drive the production wrapper, not the socket

**Context**: The harness could speak to the daemon socket directly, which
would be simpler and faster.

**Options Considered**:

1. Direct socket call — simpler, but skips the bash forwarder, which is where
   most of the end-to-end cost lives and where several past field bugs
   actually were.
2. Subprocess against `.claude/hooks/pre-tool-use` — slower, exercises the
   real path a user gets.

**Decision**: Option 2. An acceptance test that bypasses the production entry
point is an integration test wearing the wrong label.
**Date**: 2026-08-14

## Success Criteria

- [ ] Every playbook test is EITHER executed by the harness OR explicitly
  marked as needing a human, with a reason
- [ ] No test can silently fail to be covered by either route
- [ ] The harness reports zero false failures on a clean tree
- [ ] A wrong constructor keyword argument in a documented example fails QA

## Risks & Mitigations

| Risk                                                            | Impact | Probability | Mitigation                                                                      |
| --------------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------- |
| Harness reports false failures and gets disabled                | High   | Medium      | Task 2.2 — non-executable is SKIPPED, never FAILED                              |
| Automating the gate erodes the real-session testing it replaces | High   | Medium      | Task 3.3 — state the residual explicitly; the harness supplements, not replaces |
| A probe is shadowed by a terminal handler and passes vacuously  | High   | Medium      | Task 2.4 — isolate every probe's `cwd`, the exact Plan 00241 defect             |
| The doc-snippet check cannot pass on day one                    | Medium | Medium      | Task 4.1 — scope it to the dataclasses docs actually teach                      |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. -->

- Measured during the v3.53.0 release: 169 executed, 120 matching, 49 blocked
  on prose `command` strings rather than on daemon behaviour
