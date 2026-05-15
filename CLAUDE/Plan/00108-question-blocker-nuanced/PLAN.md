# Plan 00108: Nuanced AskUserQuestion Blocker

**Status**: Not Started
**Created**: 2026-05-15
**Owner**: TBD
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The current `ask_user_question_blocker` handler
(`src/claude_code_hooks_daemon/handlers/pre_tool_use/ask_user_question_blocker.py`)
blocks **every** `AskUserQuestion` tool call unconditionally when enabled.
There is no escape hatch — even a question with genuinely ambiguous, equally-
valid options is denied. As a consequence the handler is disabled by default
and unusable in practice: turning it on prevents legitimate clarifications,
leaving it off allows tautological "should I continue?" prompts.

This plan applies the same nuance the Stop handler already enforces via
`STOPPING BECAUSE:` (see `handlers/stop/auto_continue_stop.py` Branch 2): the
agent gets an explicit, audited escape hatch for genuinely-needed questions,
and every other question is rewritten as "state your assumption and proceed"
so the watching user can intervene if the assumption is wrong.

## Goals

- Replace "always deny" with a prefix-positive policy: allow `AskUserQuestion`
  only when the question text (or a dedicated reasoning field) begins with
  `ASKING BECAUSE:`, mirroring the `STOPPING BECAUSE:` convention
- When denied, return a reason that instructs the agent to state the question
  and its assumed-correct answer in plain text and proceed — producing an
  audit log the user can interrupt
- Make the handler safe to enable by default (after acceptance) once it has a
  working escape hatch

## Non-Goals

- Building a content-classifier for tautological vs. genuine questions —
  prefix-positive is the only reliable signal from text alone
- Changing other agent-question paths (e.g. confirmation questions in
  assistant text) — those are already covered by `auto_continue_stop`'s
  CONFIRMATION_PATTERNS Branch 3
- Touching the `AskUserQuestion` tool schema or Claude Code itself — the
  prefix lives in the question text the agent supplies, not in tool metadata

## Context & Background

### Stop-handler analogy

`auto_continue_stop` distinguishes intentional stops (`STOPPING BECAUSE: ...`)
from unintentional ones (silent stop, confirmation question, tool error) and
denies the latter with branch-specific recovery guidance. The audit memory
entry "NEVER adjust tests to match code — fix code to match tests" reinforces
the project's preference for explicit intent over implicit pattern-matching.

### Tool-input shape

`AskUserQuestion` `tool_input` carries a `questions` array; each entry has
`question`, optional `header`, `multiSelect`, and `options[]`. The prefix
check therefore runs over each `question` string (and any future top-level
`reasoning` field if Claude Code adds one — out of scope here).

### User as safety net

The user is watching every turn. The audit-log path (deny + "state assumption
and proceed") gives the user the same intervention window they already have
during normal output — they can interrupt if the assumed answer is wrong.
This trades a hypothetical "ask first" failure mode for a real "wait forever
on a tautology" failure mode, which the current handler causes today.

## Tasks

### Phase 1: Design & TDD Setup

- [ ] ⬜ **Task 1.1**: Decide prefix string and matching rules

  - [ ] ⬜ Adopt `ASKING BECAUSE:` (uppercase, colon, leading prefix in
    `question` text) — direct mirror of `STOPPING BECAUSE:`
  - [ ] ⬜ Specify match semantics: prefix must appear at the start of any
    `question` string in `tool_input["questions"]` (whitespace-stripped, case-
    sensitive — keeps the bar high enough that the agent has to mean it)
  - [ ] ⬜ Decide multi-question behaviour: ALL questions in a single
    `AskUserQuestion` call must carry the prefix, otherwise the whole call is
    denied (prevents prefix-laundering by mixing one justified question with
    several tautological ones)

- [ ] ⬜ **Task 1.2**: Decide config surface

  - [ ] ⬜ Keep `enabled: false` by default in this plan's first ship
  - [ ] ⬜ Add an `options.mode` field with values `strict` (deny without
    prefix) and `advisory` (warn-only — context message but allow through)
  - [ ] ⬜ Add an `options.required_prefix` override (default
    `"ASKING BECAUSE:"`) so projects with different conventions can tune it

### Phase 2: TDD Implementation (Red → Green → Refactor)

- [ ] ⬜ **Task 2.1**: Update tests first

  - [ ] ⬜ Locate existing test file
    (`tests/unit/handlers/pre_tool_use/test_ask_user_question_blocker.py` —
    confirm path during execution)
  - [ ] ⬜ Add failing tests: prefix present on all questions → ALLOW; prefix
    missing on any question → DENY with assumption-and-proceed guidance;
    advisory mode → DENY behaviour replaced by context injection only
  - [ ] ⬜ Edge cases: empty `questions` array, missing `tool_input`,
    leading whitespace before prefix, mixed-case prefix, prefix appearing
    mid-sentence (should NOT match)
  - [ ] ⬜ Run tests, confirm RED

- [ ] ⬜ **Task 2.2**: Implement nuanced `handle()`

  - [ ] ⬜ Read `tool_input.questions` defensively (FAIL FAST on schema
    violation — log and fall through to DENY, never silently allow)
  - [ ] ⬜ Apply prefix check per question; gate on ALL-prefixed
  - [ ] ⬜ ALLOW path: return `HookResult(decision=Decision.ALLOW)` so the
    user gets the question
  - [ ] ⬜ DENY path: return guidance message — see Phase 3 wording
  - [ ] ⬜ Honour `options.mode` (strict vs. advisory)
  - [ ] ⬜ Run tests, confirm GREEN

- [ ] ⬜ **Task 2.3**: Refactor

  - [ ] ⬜ Pull prefix string and reason text to module-level named constants
    (NO MAGIC engineering principle)
  - [ ] ⬜ Confirm 95%+ coverage on the file
  - [ ] ⬜ Run `./scripts/qa/llm_qa.py all` — must pass clean

### Phase 3: Guidance Wording (DENY reason)

- [ ] ⬜ **Task 3.1**: Draft the DENY reason text
  - Required content:
    - Explain why the question was blocked (no `ASKING BECAUSE:` prefix)
    - Instruct: state the question and your assumed-correct answer in plain
      output text, then proceed with that assumption
    - Note: the user is watching and will interrupt if the assumption is wrong
    - Escape hatch: if the question really has equally-valid options the agent
      cannot resolve, retry the `AskUserQuestion` with each `question`
      prefixed `ASKING BECAUSE: <one-line reason the agent cannot decide>`

### Phase 4: CLAUDE.md Guidance

- [ ] ⬜ **Task 4.1**: Implement `get_claude_md()` for the handler
  - Currently returns `None` (line 75 of source) — replace with concise
    guidance: prefix convention, when to use it, how to phrase the assumption
    fallback. Mirrors the Stop-handler block already shipped in
    `auto_continue_stop.get_claude_md()`.

### Phase 5: Acceptance Tests

- [ ] ⬜ **Task 5.1**: Replace the single `BLOCKING` acceptance test
  - [ ] ⬜ Test 1: `AskUserQuestion` without prefix → DENY with
    "assumption-and-proceed" guidance
  - [ ] ⬜ Test 2: `AskUserQuestion` with `ASKING BECAUSE:` prefix on all
    questions → ALLOW (question reaches user)
  - [ ] ⬜ Test 3: Mixed (prefix on one, missing on another) → DENY
  - [ ] ⬜ Test 4: Advisory mode → context injection only, never DENY

### Phase 6: Dogfooding & Release Decision

- [ ] ⬜ **Task 6.1**: Keep `enabled: false` for the initial ship of this
  plan — observe in main thread, ensure the escape hatch actually works in
  practice before flipping the default
- [ ] ⬜ **Task 6.2**: Open follow-up issue/plan if behaviour proves stable
  to flip `enabled: true` by default in a subsequent MINOR release

## Dependencies

- Depends on: nothing (handler is self-contained; no shared utility changes)
- Blocks: nothing
- Related: `auto_continue_stop` (pattern source)

## Technical Decisions

### Decision 1: Prefix-positive vs. pattern-negative detection

**Context**: We need to distinguish tautological questions from genuine ones.

**Options Considered**:

1. **Prefix-positive** — Allow only if `ASKING BECAUSE:` prefix present.
   Pros: zero false positives on legitimate questions that took the trouble
   to declare intent; mirrors `STOPPING BECAUSE:`; the agent already pays
   this cost for stops. Cons: requires agent to know the convention (covered
   by `get_claude_md()`).
2. **Pattern-negative** — Detect tautological language ("should I continue",
   "would you like me to"). Pros: zero agent-side change. Cons: arbitrary
   regex maintenance; false positives on legitimate uses of the same wording;
   diverges from the Stop-handler convention.

**Decision**: Option 1 (prefix-positive). It's the same convention the
codebase already enforces for `STOPPING BECAUSE:`, has no false-positive risk,
and is verifiable from a single string check.

### Decision 2: ALL-prefixed vs. ANY-prefixed for multi-question calls

**Context**: `AskUserQuestion` may contain N questions in one call.

**Options Considered**:

1. **ANY** — Allow if at least one question has the prefix. Cons: prefix
   laundering — agent can attach one justified question to N tautological
   ones.
2. **ALL** — Require every question to carry the prefix.

**Decision**: ALL. Closes the laundering loophole; trivial for the agent to
satisfy (one prefix per question is a few extra tokens).

### Decision 3: Default `enabled` state on first ship

**Context**: Current handler is `enabled: false`. Once nuanced, it's safer.

**Options Considered**:

1. Flip to `enabled: true` immediately.
2. Keep `enabled: false`, observe in dogfooding, flip in a follow-up.

**Decision**: Option 2. Project memory entry "NEVER push before acceptance
tests complete" — same caution applies to flipping defaults. Ship nuanced
behaviour first, validate it actually works in real sessions, then flip in a
subsequent release.

## Success Criteria

- [ ] Handler allows `AskUserQuestion` calls where every question carries
  `ASKING BECAUSE:` and denies otherwise
- [ ] DENY reason instructs agent to state-assumption-and-proceed with the
  prefix escape hatch documented
- [ ] `get_claude_md()` returns concise guidance (no longer `None`)
- [ ] Acceptance tests pass (Phase 5)
- [ ] Full QA suite passes (`./scripts/qa/llm_qa.py all`)
- [ ] Daemon restart verifies handler loads
  (`$PYTHON -m claude_code_hooks_daemon.daemon.cli restart` + status RUNNING)
- [ ] 95%+ coverage on the handler file

## Risks & Mitigations

| Risk                                                       | Impact | Probability | Mitigation                                                                                            |
| ---------------------------------------------------------- | ------ | ----------- | ----------------------------------------------------------------------------------------------------- |
| Agent doesn't learn the `ASKING BECAUSE:` convention       | Med    | Low         | `get_claude_md()` injects the rule into every session; DENY reason restates the escape hatch verbatim |
| User dislikes the assumed-answer audit pattern in practice | Med    | Low         | Plan ships `enabled: false`; advisory mode available; trivial to flip back to old "always block"      |
| `AskUserQuestion` tool input schema changes upstream       | Low    | Low         | FAIL FAST on schema violation — log and DENY (never silently allow); schema test pins current shape   |

## Timeline

This is a single-handler change with one test file and one config touch.
Expected effort: 1–2 hours including QA + daemon restart verification. No
phase-level time estimates — see project rule "no time estimates in plan
documents".

## Notes & Updates

### 2026-05-15

- Plan drafted in response to user feedback that the existing always-deny
  handler is too aggressive for real use; modelled after the
  `auto_continue_stop` `STOPPING BECAUSE:` Branch 2 pattern.
