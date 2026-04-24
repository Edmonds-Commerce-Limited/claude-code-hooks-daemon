# Plan 00101: Recap-Stoppage Investigation

**Status**: Not Started
**Created**: 2026-04-24
**Owner**: Claude (Opus) + transcript-inspector sub-agent
**Priority**: High (dogfooding — degrades main-thread productivity)
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration (transcript-inspector for diagnosis)

## Overview

During Plan 00100 Task 3.0.5 TDD work, the main Claude agent repeatedly
exhibited a pathological pattern:

1. Perform ONE tool call (typically an `Edit`)
2. Produce a short recap-style assistant message describing what was just done
3. End the turn WITHOUT further tool calls — mid-loop, mid-refactor
4. Stop hook auto-fires the "you stopped without explaining why" block
5. User notices and manually prompts the agent to continue

This happened at least three times in rapid succession while updating
three sibling callers in `src/claude_code_hooks_daemon/daemon/cli.py`,
a task whose structure obviously required multiple consecutive Edits.

The user observed I was at ~80% context usage at the time and posed the
hypothesis: **something in the stack may be causing premature stops at
high context pressure instead of letting compaction handle it**.

## Goals

- Confirm or refute: does recap-stoppage correlate with context usage?
- Identify the trigger pattern(s) that push the model into "recap and end"
  instead of "continue the loop"
- Produce a reproducible signature (message shape, reminder density,
  tool sequence) that could be detected programmatically
- Decide on a mitigation: handler, prompt nudge, hook behaviour change, or
  model-side prompting discipline

## Non-Goals

- Do NOT "fix" this by silencing the Stop hook — the Stop hook is the
  diagnostic that surfaced the problem. Removing the alarm doesn't
  remove the fire.
- Do NOT attempt to compress or summarise conversation yet — first
  understand what's triggering the premature stop.

## Context & Background

### Observed Symptom (this session)

- User interjected after ~3 recap-stops in a row during a routine
  multi-caller update (`current_fp = python_venv_fingerprint(project_root)`
  repeated across `_enumerate_venvs`, `cmd_list_venvs`, `cmd_prune_venvs`)
- Each stop happened immediately after one successful Edit
- The Stop hook was firing as designed — the model itself was wrongly
  ending turns mid-task
- Context utilisation was high (~80%) throughout the failure window

### Relevant hooks in this repo

- `auto_continue_stop` (priority 10, Stop event) — TERMINAL, blocks
  unexplained stops and demands `STOPPING BECAUSE:` prefix or
  `AUTO-CONTINUE` signal
- `task_completion_checker` (priority 20, Stop) — ADVISORY
- `hedging_language_detector` (priority 30, Stop) — ADVISORY
- `critical_thinking_advisory` (priority 55, UserPromptSubmit) — injects
  reminder context
- Multiple PostToolUse handlers inject "✅ PostToolUse hook system active"
  reminders on every tool call — potential reminder-density factor

### Sub-agent dispatched

`transcript-inspector` launched in background (agentId visible in session)
with a 400-word diagnostic brief. Awaiting findings before drafting
mitigations.

## Tasks

### Phase 1: Diagnose (in flight)

- [x] ✅ **Task 1.1**: Receive transcript-inspector findings (taskId
  `aea9c6a5020b79c62`, completed 2026-04-24). See "Root Cause Hypothesis"
  section below.
- [x] ✅ **Task 1.2**: Fold findings into "Root Cause Hypothesis" section
- [ ] ⬜ **Task 1.3**: Decide if additional diagnostic runs are needed
  (reproduce deliberately at low vs high context, with vs without heavy
  reminder injection)

### Phase 2: Validate Hypothesis

- [ ] ⬜ **Task 2.1**: Design a minimal reproducer if one fits the
  hypothesis (e.g. contrived high-context conversation that reliably
  triggers recap-stop)
- [ ] ⬜ **Task 2.2**: Run reproducer, capture transcript
- [ ] ⬜ **Task 2.3**: Confirm / refute hypothesis

### Phase 3: Mitigate

- [ ] ⬜ **Task 3.1**: Propose mitigation options, each with tradeoffs:
  - (a) Prompt-level: stronger "continue the loop" instruction in CLAUDE.md
  - (b) Handler-level: new advisory that detects recap-without-tool
    patterns and nudges continuation
  - (c) Hook-level: enhance `auto_continue_stop` to include specific
    "this looks like a recap-stop mid-loop" guidance
  - (d) Context-hygiene: tune which hooks inject reminders (reduce noise
    at high context) — i.e. a hook behaviour change
- [ ] ⬜ **Task 3.2**: User picks one, implement with TDD
- [ ] ⬜ **Task 3.3**: Dogfood for at least one multi-step session

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Track recap-stop count over subsequent sessions
- [ ] ⬜ **Task 4.2**: Write up findings in a lessons-learned note for
  future LLM contributors

## Root Cause Hypothesis (Phase 1.1 findings — 2026-04-24)

`transcript-inspector` sub-agent (taskId `aea9c6a5020b79c62`) analysed this
session's transcript. Key findings:

### Stoppage census

- 6 total `stop_hook_summary` events; 3 problematic (L143 plan-recap stop,
  L685 mid-loop-after-Edit stop, plus early L34/L45 conversational).
- 2 legitimate stops used `STOPPING BECAUSE:` or `AUTO-CONTINUE` correctly.

### Trigger pattern

Problematic stops both follow the same shape:

1. Model executes Edit tool call
2. Tool result arrives: `"The file ... has been updated successfully."`
3. Model's next turn produces **zero output** — no text, no tool call
4. Claude Code interprets the empty turn as end-of-session; Stop hook fires

Not "recap then stop" as initially suspected — it is **silent stop** after
a successful Edit result. The recap-before-stop observation was an
artefact: text-then-tool pairs visible in transcript were split across
two records but belong to one inference.

### Context pressure correlation

| Stop         | Context at stop | % of 200k |
| ------------ | --------------- | --------- |
| L143 (bad)   | 147,631         | 79%       |
| L685 (bad)   | 157,440         | 79%       |
| L374 (legit) | 162,000         | 81%       |
| L34 (bad)    | 95,000          | 48%       |
| L45 (bad)    | 114,000         | 57%       |

Clustering at ~79% is suggestive but n is too small for certainty.
Context pressure is NOT the sole cause — early session stops at 48–57%
show the pattern is not purely high-context driven.

### Reminder density

Every tool result is followed by `✅ PostToolUse hook system active`
reminder. Density is uniform across the session — no spike immediately
before problematic stops. Reminder-density hypothesis **refuted**.

### Validated / refuted

- ✅ Pattern: silent turn after Edit tool result (confirmed)
- ⚠️ Context pressure: correlated but insufficient sample (partial support)
- ❌ Recap-style text triggering stop: refuted (the text was on the
  tool-call turn, not a separate turn)
- ❌ Reminder-density spike: refuted (density is uniform)

### Proposed validation test (Task 2.1 seed)

Compare `output_tokens` on the final assistant turn before each stop:

- If near-zero output at high context → generation-cutoff (model stops
  generating)
- If normal output (200–400 tokens) with no tool call → planning /
  instruction-following issue

The two produce different mitigations: cutoff favours context-hygiene
(option d); planning issue favours prompt-level nudge (option a).

## Technical Decisions

_To be populated during Phase 3 after hypothesis validated._

## Success Criteria

- [ ] Concrete signature of recap-stoppage documented
- [ ] Root cause identified with supporting evidence (transcript excerpts)
- [ ] At least one mitigation implemented and verified in a real session
- [ ] Zero recap-stoppages during a 30-minute multi-step task as
  regression test

## Risks & Mitigations

| Risk                                                                      | Impact | Probability | Mitigation                                           |
| ------------------------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------- |
| Root cause is "model-side, not hook-side" and unfixable downstream        | High   | Medium      | Document behaviour for future LLM prompting guidance |
| Disabling handlers (e.g. reminder reduction) causes regressions elsewhere | Medium | Low         | TDD + acceptance tests before/after                  |
| Hypothesis is wrong, real cause is elsewhere                              | Medium | Medium      | Don't commit to mitigation until Phase 2 validates   |

## Notes & Updates

### 2026-04-24

- Plan created after user flagged ~3 recap-stops in rapid succession
  during Plan 00100 Task 3.0.5 TDD execution
- `transcript-inspector` sub-agent dispatched with 400-word diagnostic
  brief (background)
- Main thread continues Task 3.0.5 work in parallel; Phase 1.2+ of this
  plan awaits sub-agent completion
