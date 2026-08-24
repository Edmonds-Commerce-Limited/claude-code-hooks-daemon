# Plan 00265: static type safe handler results

**Status**: Complete
**Created**: 2026-08-24
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`HookResult` is one event-agnostic type serving all 31 wired events. Nothing at
the type level ties a handler to the decisions its event can express, so a
handler on `SessionStart` can construct `HookResult(decision=Decision.DENY)` and
mypy is silent. The wire response then drops the refusal: the handler believes
it blocked, and nothing blocked.

Three guards now catch this, and all three are *detection after the fact*:
`to_json` enforces the contract at runtime, a derived integration sweep checks
every built-in handler, and `validate-project-handlers` checks a client's own
handlers. Each answers "did someone already write the bug?" — none makes the bug
unwritable.

This plan makes it unwritable. A per-event abstract base narrows the return type
**once**, and concrete handlers inherit the constraint with nothing to declare
and nothing to remember. That is the difference between a convention enforced by
tests and a property enforced by the compiler.

## Goals

- A handler cannot return a decision its event cannot deliver — mypy rejects it
- The constraint is INHERITED, so a new handler gets it without declaring anything
- `merge_pseudo_results` can no longer write an undeliverable decision into a result
- Existing runtime guards keep working unchanged (defence in depth, not replacement)

## Non-Goals

- Removing any existing guard. Project handlers ship outside this repository and
  may not be type-checked at all, so the runtime and CLI guards stay.
- Changing the wire format, the response schemas, or any handler's behaviour.
- Making `HookResult` immutable. `validate_assignment` already gives runtime
  enforcement on mutation; freezing would be a larger, separate change.

## Context & Background

### The design, verified before committing to it

Prototyped against the real `HookResult` and `Handler` under this project's
strict mypy. All four properties hold:

| Property                                  | Static (mypy)                 | Runtime (Pydantic)                                      |
| ----------------------------------------- | ----------------------------- | ------------------------------------------------------- |
| Construct `AdvisoryResult(decision=DENY)` | rejected `[arg-type]`         | `ValidationError`                                       |
| Mutate `.decision = DENY`                 | rejected                      | `ValidationError` (`validate_assignment` is already on) |
| Widen an inherited `handle()` return type | rejected `[override]`         | n/a                                                     |
| Correct advisory handler                  | clean, nothing extra declared | n/a                                                     |

This is the PHP pattern (wide interface type, narrowed by the implementation)
and it is *stronger* here, because Pydantic enforces the same constraint at
runtime that mypy enforces statically.

### Why per-event base classes rather than `Handler[ResultT]`

A generic parameter must be declared on every handler, so a handler that FORGOT
to declare would silently lose protection — the same failure mode this plan
exists to remove. A per-event base is inherited, so forgetting is not possible.

### Known frictions, recorded rather than discovered later

- **pyright disagrees with mypy** on narrowing a mutable field
  (`reportIncompatibleVariableOverride`: it demands invariance, mypy demands a
  subtype). This project's QA gate is mypy, so nothing fails — but the IDE will
  show it on the narrowed classes. Do not "fix" it by widening.
- **`merge_pseudo_results` mutates** `real.result.decision`. Under narrowed
  types that becomes both a type error and a runtime `ValidationError`. It must
  be restructured to construct a result rather than mutate one, and to clamp a
  pseudo-event's decision to what the trigger's event can carry.
- **Handler count**: 84 concrete handler classes across 11 packages
  (`pre_tool_use` 42, `status_line` 13, `session_start` 11, `post_tool_use` 7,
  `user_prompt_submit` 4, `nitpick` 2, and 1 each in `permission_request`,
  `pre_compact`, `stop`, `worktree_create`, `worktree_remove`).

### Capability tiers

Derived from `REFUSAL_CAPABLE_EVENTS`, which the existing tests already hold to
the emitted response:

| Tier     | Decisions                  | Events                          |
| -------- | -------------------------- | ------------------------------- |
| Gating   | ALLOW, CONTINUE, DENY, ASK | PreToolUse, PermissionRequest   |
| Blocking | ALLOW, CONTINUE, DENY      | PostToolUse, Stop, SubagentStop |
| Advisory | ALLOW, CONTINUE            | every other wired event         |

## Tasks

### Phase 1: Result type hierarchy

- [x] ✅ **Task 1.1**: Write failing tests for the three narrowed result types
  - [x] ✅ Construction of an out-of-tier decision raises
  - [x] ✅ Assignment of an out-of-tier decision raises
  - [x] ✅ Each tier accepts every decision it should
- [x] ✅ **Task 1.2**: Add `AdvisoryResult`, `BlockingResult`, `GatingResult`
- [x] ✅ **Task 1.3**: Derive the tier membership from `REFUSAL_CAPABLE_EVENTS`
  rather than restating it, and add a test that the two cannot drift
- [x] ✅ **Task 1.4**: Prove the STATIC half is really enforced — a fixture of
  deliberate violations checked by a real mypy run, with the fixture's own
  `VIOLATION:` markers as the expectations, so adding a case extends the test
  automatically. Verified non-vacuous by widening a tier and confirming the
  guard named exactly the two violations that stopped being caught.

### Phase 2: Per-event handler bases

- [x] ✅ **Task 2.1**: Write failing tests that a handler subclassing an event
  base cannot return an out-of-tier decision, and cannot widen the override —
  both now in the mypy fixture, caught at `[arg-type]` and `[override]`
- [x] ✅ **Task 2.2**: Add the bases, narrowing `handle()`. Three real tier
  classes plus a one-line alias per event: mypy enforces a narrowed return type
  identically through an alias, so an event costs a line rather than a class
  body. Named `{Event}HandlerBase` because `WorktreeCreateHandler` and
  `WorktreeRemoveHandler` are already concrete handler class names.
- [x] ✅ **Task 2.3**: Add a test that every WIRED EVENT — not merely every
  existing package — has a base whose tier matches the capability table, so an
  event that gains its first handler later already has one

### Phase 3: Reparent the handlers

- [x] ✅ **Task 3.0** (unplanned, and it gates the rest): the FACTORIES decide
  whether a narrowed handler is writable at all. They construct via `cls(...)`
  so the runtime type was always right, but were annotated `-> "HookResult"`.
  `allow` now returns `Self`; `deny`/`ask` stay WIDE on the base so
  `AdvisoryResult.deny(...)` is rejected, with `Self` overrides only on the
  tiers that can refuse. A second mypy fixture pins both directions.
- [x] ✅ **Task 3.1**: Reparent the advisory-tier packages (the ones that gain
  real protection): `session_start`, `pre_compact`, `status_line`,
  `user_prompt_submit`, `worktree_create`, `worktree_remove`
- [x] ✅ **Task 3.2**: Reparent the blocking-tier packages: `post_tool_use`, `stop`
- [x] ✅ **Task 3.3**: Reparent the gating-tier packages: `pre_tool_use`,
  `permission_request`
- [x] ✅ **Task 3.4**: Add a test that every concrete handler descends from its
  event's base, so a new handler cannot bypass the hierarchy — and that each
  `handle()` still DECLARES its event's tier, since inheriting the base is not
  enough if the override re-widens. `nitpick` is exempt by recorded decision.

### Phase 4: Close the mutation path

- [x] ✅ **Task 4.1**: Write a failing test that `merge_pseudo_results` cannot
  write a decision the trigger's event cannot carry
- [x] ✅ **Task 4.2**: Restructure it to construct rather than mutate, clamping
  to the trigger event's tier. `event_name` is now a REQUIRED argument — the
  merge cannot be done correctly without it, and an unknown one raises rather
  than resolving to the advisory tier. A clamped refusal is not discarded: its
  reason is delivered as context (what such an event CAN carry) and the clamp
  is logged at ERROR.
- [x] ✅ **Task 4.3**: Verify the existing pseudo-event sweep still passes

### Phase 5: Project handlers and documentation

- [x] ✅ **Task 5.1**: Decide and record whether project handlers must use the
  event bases — see Decision 3. RECOMMENDED, not required; `Handler` stays
  supported and undeprecated, and `validate-project-handlers` remains their
  real protection.
- [x] ✅ **Task 5.2**: Update `CLAUDE/HANDLER_DEVELOPMENT.md` and
  `CLAUDE/PROJECT_HANDLERS.md` with the base-class guidance
- [x] ✅ **Task 5.3**: Add truth-changes manifest entries — "handlers subclass
  `Handler`" becomes "handlers subclass their event's base"; plus the two
  consequences a reader would otherwise meet as a surprise (the factory-form
  fix can surface NEW validator warnings, and `merge_pseudo_results` gained a
  required argument)
- [x] ✅ **Task 5.4**: Add a post-upgrade task for client projects with handlers

## Technical Decisions

### Decision 1: Per-event base classes, not a generic type parameter

**Context**: Both encodings type-check. They differ in what happens when a
developer forgets.
**Options considered**:

1. `Handler(Generic[ResultT])`, each handler declaring `Handler[AdvisoryResult]`
   — a forgotten declaration silently loses protection.
2. Per-event abstract base narrowing `handle()` — the constraint is inherited,
   so it cannot be forgotten, only actively overridden (which mypy rejects).

**Decision**: Option 2. A guard that depends on remembering to declare it is the
failure mode this plan exists to remove.

### Decision 2: Keep every existing runtime guard

**Context**: Static typing could be read as making the runtime checks redundant.
**Decision**: Keep them. Project handlers live outside this repository and may
never be type-checked; `to_json` enforcement and `validate-project-handlers` are
their only protection. Static typing raises the floor for THIS repo's handlers;
it does not reach a client's.

### Decision 3: Event bases are RECOMMENDED for project handlers, not required

**Context**: Task 5.1. This repository's handlers are now reparented and mypy
enforces the tier. Project handlers live in a client's own repository, and the
question is whether the documentation should require the same of them.
**Options considered**:

1. **Require it** — document `Handler` as deprecated for project handlers and
   have `validate-project-handlers` warn on a direct subclass.
2. **Recommend it** — document the bases as the better default, keep `Handler`
   fully supported, and leave the CLI guard as the enforcement.

**Decision**: Option 2. A static guard only pays off where a type-checker
actually runs, and most client projects do not run mypy over
`.claude/project-handlers/`. Requiring the base there would trade a real
protection (the CLI guard, which works regardless) for a cosmetic one, while
breaking every existing project handler on upgrade for no runtime benefit.
The post-upgrade task therefore *offers* the base as an improvement rather than
demanding a migration.

**Consequence worth stating**: this is the one population the static work in
this plan does not reach, which is exactly why Decision 2 keeps every runtime
guard.

## Success Criteria

- [x] A `SessionStart` handler returning DENY fails `./scripts/qa/llm_qa.py all`
  — `tests/integration/test_static_type_safety_is_enforced.py` runs a real
  mypy over two fixtures pinning 14 deliberate violations, and pytest is
  part of the QA suite
- [x] Every concrete handler descends from its event's base, enforced by a test
  — and a second sweep asserts each `handle()` still DECLARES its tier,
  since inheriting the base is not enough if the override re-widens
- [x] `merge_pseudo_results` cannot produce an undeliverable decision
- [x] All existing response-contract tests still pass unchanged
- [x] QA green (23/23), daemon restarts RUNNING, client-mode fixture verified
  — provisioned the real fixture, confirmed its daemon came up RUNNING on a
  genuine client install, and validated a probe handler that IMPORTS an
  event base to prove the `project_loader` fix on the surface that matters

## Risks & Mitigations

| Risk                                                     | Impact | Probability | Mitigation                                                                                  |
| -------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------- |
| Reparenting 84 handlers breaks daemon load               | High   | Medium      | Restart the daemon after each package, not once at the end                                  |
| A handler genuinely needs a wider decision than its tier | High   | Low         | That is the bug this finds; fix the handler or correct the tier — never widen to silence it |
| pyright noise leads someone to "fix" the narrowing       | Medium | Medium      | Recorded above and in the class docstrings                                                  |
| Pseudo-event merge now raises where it silently degraded | High   | Medium      | Phase 4 lands before any reparenting of trigger events                                      |

## Delivery & Milestones

- Design verified against real `HookResult`/`Handler` under strict mypy, before
  any production change
- Phases 1-2 (result hierarchy + per-event bases) at `999fdbba`
- Phase 4 (pseudo-event merge clamped to the trigger's tier) at `557f9cc2`
- Factory-form blind spot in the AST scan closed at `0877bbf0`
- Phase 3 groundwork (`Self` factories, one shared discovery predicate) at
  `32914462`
- Phases 3+5 (all 84 handlers reparented, docs, manifests, the shipped example
  whose refusal never worked) at `6fc2db3a`
- The CLAUDE.md handler-skeleton rewrite belonging to this plan landed
  separately at `b2c38307`, swept there by the daemon's auto-commit on restart
  rather than by intent — see the 2026-08-24 JOURNAL entry
