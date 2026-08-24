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
hooks somehow." Phase 1 answers that factual question and enumerates every
real mechanism available. That answer then sharpens the question: Claude
Code's native `prompt`/`agent` hooks are real, adoptable with almost no code,
and run in parallel with this daemon's own hooks on the same event — cheap to
adopt (one validator fix, Task 4.0), but (see the Headline finding below)
still costing seconds per invocation, so the question is no longer
"can we have AI-driven hooks"
but "given that native hooks already exist, does a daemon-side AI handler
earn its cost at all, and for which specific judgements" (`DECISIONS.md` §4).

Two real false positives surfaced *while this plan was being written* —
`nitpick.hedging_language` flagging honest uncertainty that named its own
resolution path, and `qa_suppression` blocking a comment that argued
*against* a suppression it happened to name — and both are used as the
concrete, evidenced motivation for what to build, rather than a hypothetical
(`DECISIONS.md` §0).

**Headline finding**: Claude Code does support AI-driven hooks natively —
`"type": "prompt"` (30s timeout) and `"type": "agent"` (60s timeout, Read/
Grep/Glob tool access, no Bash, "experimental") hooks, confirmed against the
official docs, and confirmed to run **in parallel** with this daemon's own
`command` hooks on the same event — though parallel means the hooks do not
COMPOUND, not that the latency is free: the tool call still blocks on the
slowest hook, so a `prompt` hook on `PreToolUse` still costs seconds.

**Two constraints govern adopting a native hook here**, both measured against
the code rather than inferred (`RESEARCH-claude-code-native-hooks.md`):

- `reconcile_settings_hooks` is additive per EVENT, not per entry. A native
  hook must be added ALONGSIDE the daemon wrapper — replace it and the
  wrapper is never restored, and every handler on that event goes dark.
- `validate_hook_commands` misreports two of the three layouts for doing that
  as registration faults. Only Layout B (appended after the daemon command,
  same entry) is clean today, which is why Task 4.0 fixes the validator
  before Task 4.1 prototypes anything.

So native hooks are adoptable here, but not quite for free: one small
validator fix comes first.

**Phase 1's conclusions have now been tested live** — see `EXPERIMENTS.md`.
A `prompt` hook was registered in this repository and triggered. It works;
it also locked the session out of `Edit`/`Write` when its model answered in
prose, because unparseable output FAILS CLOSED. Read that document before
writing any native-hook config.

**The decisive finding for what to build daemon-side**: native hooks see only
raw event JSON, never a *prior daemon-side regex match*. That rules them out
for **confirm-the-positive** (`DECISIONS.md` §3c) — the safest way found to
let AI influence a shipping *blocking* handler, since it can only ever remove
a block, never add one — which is also the design this plan's live evidence
most directly motivates.

## Goals

- Establish, with evidence, what Claude Code's native LLM-driven hook support
  actually is, how it relates to this daemon, and whether it coexists with
  this daemon's own hooks (`RESEARCH-...md`).
- Confront the latency and determinism costs of AI-driven hook decisions
  honestly against this project's own stated performance premise and testing
  discipline, and test the "advisory = free" intuition rather than assume it
  (`DECISIONS.md` §1, §1b).
- Produce a ranked, concrete brainstorm of candidate use-cases, each scored
  on why a regex cannot do the job, which event it would live on, whether
  that event tolerates the latency, and which mechanism (native / daemon-side
  / self-audit) actually fits it (`IDEAS.md`).
- Decide, and build, the smallest defensible daemon-side AI handlers,
  grounded in the live false positives this plan itself surfaced — Phases 2
  and 3 below — so the pattern is proven in production rather than left as a
  brainstorm no one acted on.

## Non-Goals

- Not building every idea in `IDEAS.md` — most are explicitly rejected,
  deferred to Mechanism C, or marked native-hook-eligible instead; see that
  document's ranking section for the reasoning.
- Not touching `security_antipattern`'s data-flow gaps (SQLi, path
  traversal, weak hashing) — that is `Plan 00204`'s question to answer
  first, and `IDEAS.md` #8 explains why an AI judge needs the wrong
  (recall, not precision) filter shape for that specific hot,
  security-critical path regardless.
- Not adopting native Claude Code `prompt`/`agent` hooks project-wide as
  policy — code verification found no actual conflict with
  `hook_registration_checker` (`RESEARCH-...md`; only its guidance wording
  needed a fix, tracked as Task 4.0). Phase 4 below only *prototypes* native
  hooks for ideas that don't need daemon state; broader adoption is a
  separate decision.
- Not resolving the `gh` comment-quality idea (`IDEAS.md` #11) — it belongs
  to `Plan 00264`, which already owns that surface.

## Context & Background

See `RESEARCH-claude-code-native-hooks.md` for the mechanism reference
(including hook coexistence and model-determinism findings), `DECISIONS.md`
for the full latency/determinism/mechanism trade-off analysis — including
the concrete live evidence in §0, the `AdvisoryResult` type-level safety
pattern from Plan 00265 (§2), and the confirm-the-positive vs second-opinion
filter distinction (§3c) — and `IDEAS.md` for the full 16-candidate
brainstorm, mechanism mapping, and ranking.

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
- [x] ✅ **Task 1.5**: Brainstorm and score concrete candidate use-cases,
  each against: what it judges, why a regex cannot, which event, latency
  tolerance, advisory-vs-blocking, mechanism, and cost (`IDEAS.md`).
- [x] ✅ **Task 1.6**: Capture the two live false positives that surfaced
  during this plan's own writing as concrete, evidenced motivation, and
  fold in `comment_changelog`'s documented demoted-signal history as
  supporting evidence of the same root cause (`DECISIONS.md` §0).
- [x] ✅ **Task 1.7**: Resolve whether native hooks make daemon-side AI
  handlers redundant; verify the `hook_registration_checker` tension
  against its actual CODE, not just its prose (no conflict found — see
  `RESEARCH-...md`); identify the confirm-the-positive design as the
  concrete case native hooks structurally cannot reach; map every
  candidate idea to its best-fit mechanism (`DECISIONS.md` §3c, §4;
  `IDEAS.md` mapping).
- [x] ✅ **Task 1.8**: Rank the candidates and select the first builds
  (`IDEAS.md` ranking section).

### Phase 2: Build the nitpick semantic upgrade

- [ ] ⬜ **Task 2.1**: Design the model-call boundary as an injectable
  dependency (mirroring how `TranscriptReader`/`NitpickSetup` are already
  structured) so unit tests mock the call rather than hitting a real API.
- [ ] ⬜ **Task 2.2**: Design the deferred/async surfacing mechanism — the
  model call must not run synchronously inside the `Stop` response the
  user is waiting on; the finding surfaces on a *later* event
  (`DECISIONS.md` §1b). This is new daemon infrastructure (background
  task, per-session results cache, cleanup policy) — do not skip it in
  favour of a synchronous call that merely feels less bad than
  `PreToolUse`.
- [ ] ⬜ **Task 2.3**: TDD a nitpick handler that classifies assistant-message
  dismissiveness/hedging via a model call, pinned to `AdvisoryResult` so a
  hallucinated "deny" is unwritable. Include Example A (`DECISIONS.md` §0)
  as a fixed regression case.
- [ ] ⬜ **Task 2.4**: Implement fail-open behaviour for every external
  failure mode (no credential, timeout, network error, rate limit) —
  degrade to no-opinion, never block or crash.
- [ ] ⬜ **Task 2.5**: Full QA, daemon restart verification, dogfood in this
  repo's own config, acceptance tests asserting decision-class stability
  rather than exact wording.

### Phase 3: Build the confirm-the-positive filter (qa_suppression, comment_changelog)

- [ ] ⬜ **Task 3.1**: Design the filter as a post-match hook invoked only
  when the existing regex has already found a candidate span, returning
  either "confirmed" (today's block stands) or "mention, not use"
  (downgrade); falling back to "confirmed" — today's exact behaviour — on
  any model error, per `DECISIONS.md` §3c.
- [ ] ⬜ **Task 3.2**: Verify the design does not break the acceptance-test
  strategy `CLAUDE.md`'s "Blocking Handler False Positives" section
  documents as intentional (literal dangerous strings embedded in safe
  commands, e.g. `echo "git reset --hard"`, must still be blocked) —
  confirm this filter's judgement question ("use vs mention") is a
  different axis from that strategy's judgement question ("is this
  string in a command position"), so the two do not collide.
- [ ] ⬜ **Task 3.3**: TDD with mocked model responses; include Example B
  (`DECISIONS.md` §0) as a fixed regression case for `qa_suppression`, and
  the four documented demoted signals as regression cases for
  `comment_changelog`.
- [ ] ⬜ **Task 3.4**: Implement for `qa_suppression` first (the handler with
  the live evidence); extend to `comment_changelog` once proven.
- [ ] ⬜ **Task 3.5**: Full QA, daemon restart verification, dogfood,
  acceptance tests.

### Phase 4: Prototype native-hook-eligible ideas (no daemon infrastructure)

- [ ] ⬜ **Task 4.0**: Fix `validate_hook_commands` so a native hook is not
  misreported as a duplicate registration — see the measured layout table in
  `RESEARCH-...md`. TDD, one regression test per layout. **Prerequisite for
  4.1**, not a follow-up: a prototype that warns every session trains people
  to ignore the checker.
- [ ] ⬜ **Task 4.0b**: Clarify `hook_registration_checker.get_claude_md()`'s
  wording — the "every registered command routes through the daemon wrapper"
  rule applies to `type: command` entries only. Documentation-only.
- [ ] ⬜ **Task 4.1**: Prototype `IDEAS.md` #3 (`validate_instruction_content`
  classifier) as a native `prompt` hook, added ALONGSIDE the daemon's existing
  wrapper (never replacing it, per the reconcile-is-additive-per-event footgun
  in `RESEARCH-...md`). Two hard constraints from `EXPERIMENTS.md`, both learnt
  the hard way: it MUST carry a `matcher` narrow enough to leave `Edit`/`Write`
  reachable — an unscoped hook that starts emitting prose denies the very tools
  needed to remove it — and a matcher forces **Layout A**, which is why Task
  4.0 is a prerequisite rather than a tidy-up. Prototype an ADVISORY judgement
  only: Findings 9/10 show a native hook cannot deliver a readable block.
- [ ] ⬜ **Task 4.2**: Evaluate the prototype; decide whether it earns
  daemon-side infrastructure or stays a native experiment.
- [ ] ⬜ **Task 4.3**: Repeat for #4 and #13 if #3's prototype proves the
  pattern useful; otherwise stop here — a native experiment nobody found
  useful is not evidence to build more.

### Phase 5: Extend idle_housekeeping_advisory (near-zero-cost)

- [ ] ⬜ **Task 5.1**: Add "deny-reason actionability" (`IDEAS.md` #6) and
  "guidance context-cost" (`IDEAS.md` #7) to `idle_housekeeping_advisory`'s
  suggested audit topics — no new handler, config-only change.

## Technical Decisions

See `DECISIONS.md` for full reasoning (§2-4). Summary of the load-bearing calls:

- **`AdvisoryResult` is the decision that makes this defensible.** Its
  `decision` field is `Literal[Decision.ALLOW, Decision.CONTINUE]`
  (mypy + Pydantic runtime-enforced) — a hallucinated "deny" is
  **unconstructible**, not merely disciplined against. The single fact
  letting a non-deterministic handler ship in a project that otherwise
  asserts exact decisions in acceptance tests. Phase 2 is pinned to it
  directly.
- **Confirm-the-positive earns the equivalent guarantee for a *blocking*
  handler differently**: Phase 3's filter only ever downgrades an existing
  regex match to allow, never originates a block, and falls back to today's
  exact shipped behaviour on any model failure — no new silent failure mode.
- **Mechanism is chosen per idea, not project-wide.** Verified against
  `hook_registration_checker`'s actual CODE (not prose): native
  `prompt`/`agent` hooks coexist with this daemon's hooks today, zero code
  changes needed (`RESEARCH-...md`). Daemon-side is forced only where a
  judgement needs state a native hook cannot reach (`NitpickSetup`'s
  transcript cursor, or a prior regex match); a standalone judgement
  (`IDEAS.md` #3/#4/#13) is cheaper to prototype natively first (Phase 4).
- **Fail-open is mandatory**: any model-call error degrades to no-opinion
  (Phase 2) or today's existing behaviour (Phase 3), never a new block or a
  crash — an explicit, scoped exception to Core Standard 6 for this one
  class of external-service dependency.
- **"Advisory" does not mean "free" — this changes what Phase 2 must
  build.** A synchronous model call inside `Stop`'s own response still adds
  a perceptible end-of-turn pause; wrong-block risk is zero, perceived-
  latency risk is not (`DECISIONS.md` §1b). Task 2.2's deferred/async design
  (return immediately, surface the finding on a *later* event) is what
  actually delivers that intuition — a synchronous same-turn call would ship
  something slower than intended, with no test able to catch it.

## Success Criteria

- [ ] `RESEARCH-claude-code-native-hooks.md`, `DECISIONS.md` and `IDEAS.md`
  answer the user's original question with evidence, not speculation, and
  honestly flag what could not be verified from documentation alone.
- [ ] The nitpick upgrade (Phase 2) ships advisory-only, deferred (not
  synchronous on `Stop`), fails open on every external error mode, cannot
  construct a DENY at the type level, and passes this project's full QA +
  acceptance gates.
- [ ] The confirm-the-positive filter (Phase 3) ships for at least
  `qa_suppression`, can only ever downgrade a block, falls back to today's
  exact behaviour on any model error, and does not regress the
  false-positive-tolerant acceptance-test strategy.
- [ ] Phase 4's native-hook prototypes are evaluated and a stop/continue
  decision recorded before any daemon infrastructure is built for them.
- [ ] Per-invocation cost for any model call (daemon-side or native) is
  MEASURED before default-on rollout, never estimated — the docs state
  nothing about `prompt`/`agent` hook cost/billing at all
  (`RESEARCH-...md`).

## Risks & Mitigations

| Risk                                                                     | Impact                           | Probability                                                           | Mitigation                                                                                                                  |
| ------------------------------------------------------------------------ | -------------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| A model call blocks a hot-path event, daemon "feels slow"                | High — regresses core value prop | Medium if scope creeps past the deferred/confirm-the-positive designs | Restrict Phases 2-3 to `DECISIONS.md` §1b/§3c's designs; no synchronous same-turn shortcut                                  |
| An AI handler's non-determinism breaks acceptance-test/QA discipline     | Medium                           | Medium                                                                | Mock the model call in unit tests; assert decision-class stability, not exact wording; use Examples A/B as regression cases |
| A model-call failure blocks or crashes instead of failing open           | High                             | Low if tested explicitly                                              | Tasks 2.4/3.1 require dedicated failure-mode tests before either handler ships                                              |
| Confirm-the-positive filter weakens a block the acceptance tests rely on | Medium                           | Low if Task 3.2 is explicit                                           | Task 3.2 confirms the filter's axis ("use vs mention") differs from the tests' axis                                         |

## Delivery & Milestones

- Phase 1 delivered across this plan's initial commits.
