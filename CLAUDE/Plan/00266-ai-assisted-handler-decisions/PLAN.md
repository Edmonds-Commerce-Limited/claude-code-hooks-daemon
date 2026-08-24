# Plan 00266: AI-assisted handler decisions

**Status**: In Progress
**Created**: 2026-08-24
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The user wants a way for this daemon's handlers to use AI judgement, not just
deterministic pattern matching, to decide hook outcomes — but had no concrete
use-case in mind, only the belief that "Claude Code itself supports LLM driven
hooks somehow." This plan's Phase 1 answers that factual question, enumerates
every real mechanism available (native Claude Code hooks, a daemon handler
calling a model itself, and a third mechanism this codebase already uses —
prompting the *current* agent session to self-judge), confronts the latency
and determinism costs those mechanisms carry against a daemon whose entire
premise is a ~45ms round trip, and brainstorms + ranks concrete candidate
use-cases against that reality.

**Headline finding**: Claude Code does support this natively — `"type": "prompt"` and `"type": "agent"` hooks, confirmed against the official docs —
but this project's own `CLAUDE/ARCHITECTURE.md` already half-describes this
mechanism via a `.claude/hooks.json` file that does not exist anywhere in
this checkout, and the project's own `hook_registration_checker` currently
enforces the opposite policy ("every hook command routes through the daemon
wrapper"). See `RESEARCH-claude-code-native-hooks.md` for the full mechanism
reference and the specific gaps the docs left unanswered.

## Goals

- Establish, with evidence, what Claude Code's native LLM-driven hook support
  actually is, and how it relates to this daemon (`RESEARCH-...md`).
- Confront the latency and determinism costs of AI-driven hook decisions
  honestly against this project's own stated performance premise and testing
  discipline (`DECISIONS.md`).
- Produce a ranked, concrete brainstorm of candidate use-cases, each scored
  on why a regex cannot do the job, which event it would live on, whether
  that event tolerates the latency, and what mechanism fits it
  (`IDEAS.md`).
- Decide, and build, the smallest defensible first AI-assisted handler —
  Phase 2 below — so the pattern is proven in production rather than left as
  a brainstorm no one acted on.

## Non-Goals

- Not building every idea in `IDEAS.md` — most are explicitly rejected or
  deferred; see that document's ranking section for the reasoning.
- Not touching `security_antipattern`'s data-flow gaps (SQLi, path
  traversal, weak hashing) — that is `Plan 00204`'s question to answer
  first, and `IDEAS.md` #8 explains why an AI judge is the wrong tool for
  that specific hot, security-critical path regardless.
- Not adopting native Claude Code `prompt`/`agent` hooks project-wide, and
  not changing `hook_registration_checker`'s policy, as part of this plan —
  that tension is recorded in `RESEARCH-...md` for a human to resolve
  separately if a project-specific use-case for native hooks ever arises.
- Not resolving the `gh` comment-quality idea (`IDEAS.md` #11) — it belongs
  to `Plan 00264`, which already owns that surface.

## Context & Background

See `RESEARCH-claude-code-native-hooks.md` for the mechanism reference,
`DECISIONS.md` for the latency/determinism/mechanism trade-off analysis
(including the `AdvisoryResult` type-level safety pattern from Plan 00265
that a first AI handler should adopt), and `IDEAS.md` for the full
15-candidate brainstorm and ranking.

## Tasks

### Phase 1: Research and brainstorm

- [x] ✅ **Task 1.1**: Verify what Claude Code's native hook system actually
  offers, against official docs rather than assumption
  (`RESEARCH-claude-code-native-hooks.md`).
- [x] ✅ **Task 1.2**: Confirm whether this daemon's own architecture already
  describes a native-hook mechanism, and whether it is actually
  implemented anywhere in this checkout.
- [x] ✅ **Task 1.3**: Work through the latency budget per hook event against
  this daemon's own stated ~45ms premise, including whether the
  `asyncio` dispatch model isolates a slow handler from other daemon
  clients (`DECISIONS.md` §1).
- [x] ✅ **Task 1.4**: Work through determinism/testability/trust
  consequences against this project's TDD/coverage/acceptance-test
  discipline, and identify the type-level safety pattern
  (`AdvisoryResult`) a first AI handler should be pinned to
  (`DECISIONS.md` §2).
- [x] ✅ **Task 1.5**: Brainstorm and score 10-15 concrete candidate
  use-cases, each against: what it judges, why a regex cannot, which
  event, latency tolerance, advisory-vs-blocking, mechanism, and cost
  (`IDEAS.md`).
- [x] ✅ **Task 1.6**: Rank the candidates and select the smallest
  defensible first build (`IDEAS.md` ranking section).

### Phase 2: Build the first AI-assisted handler (nitpick semantic upgrade)

- [ ] ⬜ **Task 2.1**: Design the model-call boundary as an injectable
  dependency (mirroring how `TranscriptReader`/`NitpickSetup` are
  already structured) so unit tests mock the call rather than hitting a
  real API, per `DECISIONS.md` §2.
- [ ] ⬜ **Task 2.2**: Write failing unit tests first (TDD) for a nitpick
  handler that classifies assistant-message dismissiveness/hedging via
  a model call, pinned to `AdvisoryResult` so a hallucinated "deny" is
  unwritable rather than merely disciplined-against.
- [ ] ⬜ **Task 2.3**: Implement the handler; wire it into the existing
  `pseudo_events.nitpick` chain on the `Stop` trigger only for the
  first cut (defer sampled `PreToolUse` firing until Stop-only proves
  out).
- [ ] ⬜ **Task 2.4**: Implement fail-open behaviour for every external
  failure mode (no credential configured, timeout, network error, rate
  limit) — must degrade to no-opinion/ALLOW, never block or crash, per
  `DECISIONS.md` §2.
- [ ] ⬜ **Task 2.5**: Decide and document the cost/rate-limit posture
  (reuse the existing `stop:1/1` trigger, or introduce a coarser
  sample) before enabling by default.
- [ ] ⬜ **Task 2.6**: Full QA, daemon restart verification, dogfood in this
  repo's own config, acceptance tests reflecting decision-class
  stability rather than exact wording (`DECISIONS.md` §2).

### Phase 3: Build the second AI-assisted handler (validate_instruction_content classifier)

- [ ] ⬜ **Task 3.1**: Confirm scope stays limited to `CLAUDE.md`/`README.md`
  writes only, per `IDEAS.md` #3.
- [ ] ⬜ **Task 3.2**: TDD the classifier with mocked model responses;
  decide the fail-open default for an unreachable model on a *blocking*
  PreToolUse path (this is the one candidate where blocking is
  defensible, so the fail-open direction needs explicit sign-off, not
  just fail-open-to-allow by default).
- [ ] ⬜ **Task 3.3**: Implement, QA, daemon restart, dogfood, acceptance
  tests.

## Technical Decisions

See `DECISIONS.md` for full reasoning. Summary of the load-bearing calls:

- **Mechanism**: a daemon `Handler` calling a model itself (Mechanism B),
  not native Claude Code `prompt`/`agent` hooks (Mechanism A) and not a
  daemon advisory that asks the current agent to self-judge (Mechanism C) —
  because the first two candidates are both cases where an *independent*
  judge matters (self-policing language, or a narrow well-scoped file
  check), not a self-audit Mechanism C would suit.
- **Event**: `Stop` for the first build — the one place on the latency table
  where 1-3 seconds of model latency is least likely to be felt, and where
  the existing nitpick trigger (`stop:1/1`) already fires.
- **Safety boundary**: pin the handler's return type to `AdvisoryResult`
  (Plan 00265's per-event-capability type hierarchy) so a model "deciding"
  to deny is unwritable, not merely a convention to remember.
- **Fail-open**: any model-call failure (timeout, missing credential, rate
  limit, network error) must degrade to no-opinion, never to a block or a
  crash — an explicit, written exception to Core Standard 6's "fail fast"
  posture, scoped to this one class of *external service* dependency.

## Success Criteria

- [ ] `RESEARCH-claude-code-native-hooks.md`, `DECISIONS.md` and `IDEAS.md`
  answer the user's original question with evidence, not speculation,
  and honestly flag what could not be verified from documentation alone.
- [ ] The first AI-assisted handler (Phase 2) ships advisory-only, fails
  open on every external error mode, cannot construct a DENY at the
  type level, and passes this project's full QA + acceptance gates.
- [ ] The second handler (Phase 3) ships with an explicit, reviewed decision
  on its fail-open direction given it is the one blocking candidate.

## Risks & Mitigations

| Risk                                                                                                     | Impact                                                                  | Probability                                         | Mitigation                                                                                                                                                        |
| -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A model call blocks a hot-path event and the daemon "feels slow"                                         | High — regresses the daemon's core value proposition                    | Medium if scope creeps past `Stop`/rare-file events | Restrict Phase 2/3 strictly to the events `DECISIONS.md` §1 rates as latency-tolerant; do not extend to `PreToolUse` at full sampling without a separate decision |
| An AI handler's non-determinism breaks the acceptance-test/QA discipline                                 | Medium — erodes trust in "green QA" meaning what it has always meant    | Medium                                              | Mock the model call in unit tests; assert decision-class stability (not exact wording) in acceptance tests, per `DECISIONS.md` §2                                 |
| A model-call failure blocks or crashes instead of failing open                                           | High — an external service hiccup takes down protection or blocks users | Low if built with explicit tests for this           | Task 2.4/3.2 require dedicated failure-mode tests before either handler ships                                                                                     |
| Native `prompt`/`agent` hook adoption elsewhere in the project collides with `hook_registration_checker` | Low — no such adoption is in this plan's scope                          | Low                                                 | Documented in `RESEARCH-...md` for whoever revisits Mechanism A later                                                                                             |

## Delivery & Milestones

- Phase 1 (research) delivered in this plan's initial commit.
