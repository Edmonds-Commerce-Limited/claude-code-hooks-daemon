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

### Phase 0: The defects the audit surfaced — fix before building on them

Task 1.1 found four live bugs. Each one would corrupt the harness's own
results, so they are prerequisites, not follow-ups.

- [x] ✅ **Task 0.1**: `cmd_generate_playbook` never passed `project_handlers=`,
  so the generator's project-handler branch was dead on the CLI path and three
  declared tests reached no playbook at all
  - [x] ✅ The loading is now one shared helper, because `generate-docs` had a
    correct copy five lines away — two copies is how they drifted
  - [x] ✅ Verified live: the real playbook grew by 82 lines and now carries
    both of this repo's project handlers
- [x] ✅ **Task 0.2**: `generate_json` did not emit `harness_cannot_produce`,
  so a JSON-driven harness could not see a SKIP marker the markdown already
  shows — this blocked Task 2.2 directly
  - [x] ✅ Guarded by the property, not the instance: the expectation is derived
    from the dataclass, so the NEXT field added is caught on the same commit
- [x] ✅ **Task 0.3**: `SedBlockerHandler`'s test declared a FILE PATH as its
  `command` with the real instruction buried in `description`; it looked like a
  literal shell test and was not, and could not produce its expected deny
  - [x] ✅ Rewritten into the dominant Write-payload grammar, so Task 1.2
    converts it mechanically along with the other 76
  - [x] ✅ The hardcoded `/workspace` root proved to be a CLASS: **17**
    occurrences, not the 4 a grep of `handlers/` finds — 13 live in
    `strategies/security/` behind the five delegating handlers. All fixed to
    `$CLAUDE_PROJECT_DIR`
  - [x] ✅ Guarded in `test_generated_docs_are_path_agnostic.py`, which already
    owned this property for the other two rendered artifacts and simply never
    covered the playbook
- [x] ✅ **Task 0.4**: Verified whether `plan_number_helper`'s tests are answered
  by `pipe_blocker` (priority 17) rather than by themselves
  - [x] ✅ **REFUTED.** All four driven through the production forwarder against
    the live daemon: every one matches its declared decision, and the two denies
    carry `plan_number_helper`'s own reason with both patterns present. `sort`
    is whitelisted, so `pipe_blocker` never fires. Nothing to fix

### Phase 1: Make executability explicit rather than guessed

- [x] ✅ **Task 1.1**: Audit all `get_acceptance_tests()` implementations and
  classify each `command` as literal-shell or prose
  - [x] ✅ Findings: [AUDIT-task-1.1-command-field.md](AUDIT-task-1.1-command-field.md)
  - [x] ✅ 219 tests: 98 literal shell, 115 convertible prose, **6 genuinely
    needing a human**. Honest assertive-coverage figure is ~148/219 (68%),
    because 35 of the 98 are vacuous `echo` probes and ~30 of the 115 describe
    their payload in English rather than stating it
  - [x] ✅ Five string grammars cover 76 of the prose tests, all expressing the
    identical Write payload — that concentration is what makes Task 1.2 cheap
  - [x] ✅ Five handlers declare zero tests and inherit all of theirs from
    strategies, so a per-handler converter would miss them
- [x] ✅ **Task 1.3**: `ToolPayload` (`tool_name` + `tool_input`, frozen,
  rejecting a blank tool name) and `AcceptanceTest.tool_payload`. Field names
  are the hook event's own, so a harness copies them rather than translating.
  - [x] ✅ Kept distinct from `harness_cannot_produce` — and the two are now
    mutually exclusive at construction: one says the input cannot be produced,
    the other says exactly how to produce it, so declaring both is a claim the
    harness would act on
  - [x] ✅ **Done BEFORE Task 1.2, reversing the plan's order.** Task 1.2 as
    written ("convert to a literal command") is the wrong target for the bulk
    of these: a `Write`-tool guard is not reachable from bash at all, because
    a file written through Bash bypasses the content guards that run before a
    `Write`. Rewriting such a test as `echo … > f` would assert the opposite
    of what it means to assert. The audit's own bottom line already pointed
    here — the structured field is the fix, not string normalisation
- [x] ✅ **Task 1.2**: 97 of 119 prose tests now declare `tool_payload`. Not
  done by normalising five grammars into a sixth: `as_instruction()` renders
  the sentence FROM the payload, so a site states it once and the two cannot
  drift. The 22 remaining are deliberate, in three kinds — `harness_cannot_produce`
  (2), content a payload must never CARRY (3 `sensitive_content`, which would
  mean committing a live blocked term into tracked source), and stateful
  SEQUENCES whose assertion is an observation a one-call payload cannot express
  (17). Each is recorded where a reader will meet it
  - [x] ✅ All 97 dispatched in-process against their own handlers: 59 DENY
    confirmed, 27 ALLOW correct, 11 explained by two harness requirements
    (see Task 2.1), zero payload defects
- [x] ✅ **Task 1.4**: Rendered in both directions — `generate_json` emits
  `tool_payload` (caught on its own commit by Task 0.2's dataclass-derived
  coverage guard), and `_tool_payload_block` renders it in the markdown beside
  the prose, shared by the built-in and project-handler renderers so it can
  never show in one section and hide in the other

### Phase 2: The harness

- [x] ✅ **Task 2.1**: `tests/acceptance/test_playbook_harness.py` dispatches 94
  probes; the judgement calls live in `daemon/playbook_harness.py` (pure, 41
  unit tests) so they are pinned without a daemon
  - [x] ✅ Both measured requirements honoured: `$CLAUDE_PROJECT_DIR` expanded,
    and the write PERFORMED before a PostToolUse dispatch
  - [x] ✅ **Two more found by building it, both invisible until run.** A
    PostToolUse event needs `tool_response` — without it the daemon rejects the
    event before any handler runs, so every ALLOW probe passed on a validation
    error. And a `session_id` fixed per test made `lsp_enforcement`
    (`block_once`) pass on run one and fail on run two
  - [x] ✅ Generates the playbook itself rather than reading
    `untracked/playbook.md`, which nothing keeps current
  - [x] ✅ Drives the production wrapper as a subprocess; skips when no daemon
- [x] ✅ **Task 2.2**: 193 blocks skipped, each with a reason. Event type is
  tested BEFORE payload presence, so a `SessionStart` block reads as "carries
  no tool call" rather than as unfinished conversion work
- [x] ✅ **Task 2.3**: Patterns asserted on a deny, which always carries its
  reason. Deliberately NOT on an allow: advisory text varies by disclosure
  ladder, and asserting it would invent failures
- [x] ✅ **Task 2.4**: The event's `cwd` is an isolated `tmp_path` while the
  subprocess runs at the repo root, as `test_stop_hook_hard_block.py` splits
  them. Measured to change no verdict today — kept as defence against the
  shadowing trap, which is silent because the shadowing handler can return the
  same decision the probe expected

### Phase 3: Shrink the manual gate

- [x] ✅ **Task 3.1**: Added to Step 12.0's pytest line and expected counts
- [x] ✅ **Task 3.2**: Step 12.4 is now "execute what the harness does NOT own",
  and tells the reader to ASK the harness for that list rather than working
  from a list in the doc — the same rule the section already carried after
  hardcoding "~65 blocking / ~24 advisory" while the generator emitted 200+.
  The snippet was run verbatim before shipping it
- [x] ✅ **Task 3.3**: The residual is split into four kinds, distinguishing
  the one that is unfinished work (prose with no payload) from the three that
  are permanent boundaries. No narrowing is possible: `split_playbook` is a
  total partition asserted by `test_the_partition_loses_nothing`, so a test
  that stops being executable moves into the skip list with its reason rather
  than disappearing

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

- [x] Every playbook test is EITHER executed by the harness OR explicitly
  marked as needing a human, with a reason
- [x] No test can silently fail to be covered by either route
- [x] The harness reports zero false failures on a clean tree — and on the
  RE-runs, which is the harder half: the first version passed once, then
  failed on `lsp_enforcement` because a `block_once` handler had already spent
  that session's block
- [x] A wrong constructor keyword argument in a documented example fails QA

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
