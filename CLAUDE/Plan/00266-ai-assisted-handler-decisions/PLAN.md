# Plan 00266: AI-assisted handler decisions

**Status**: Dormant
**Created**: 2026-08-24
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

> **Why Dormant.** Phase 1 is finished and answered the question that
> prompted the plan. Phases 2–5 are deliberately NOT being built: no
> candidate yet clears the cost bar. Reference material until a triggering
> case appears — see the revival conditions under Success Criteria. Task 4.0
> is the exception, being a latent defect worth fixing on its own merit.

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

Two real false positives surfaced *while this plan was being written* — in
`nitpick.hedging_language` and `qa_suppression` — and are the concrete,
evidenced motivation for what to build, rather than a hypothetical
(`DECISIONS.md` §0).

**Headline finding**: Claude Code does support AI-driven hooks natively —
`"type": "prompt"` and `"type": "agent"` (the latter documented as
experimental), which run **in parallel** with this daemon's `command` hooks on
the same event. Parallel means they do not COMPOUND, not that latency is free:
the tool call blocks on the slowest hook, measured at ~1.2s against the
daemon's ~51ms (`EXPERIMENTS.md` §5). Schemas and timeouts in `RESEARCH-...md`.

**Native hooks have now been run live in this repository — read
`EXPERIMENTS.md` before writing any native-hook config.** Summary of what
constrains adoption: a native hook must be added ALONGSIDE the daemon wrapper
(`reconcile_settings_hooks` is additive per EVENT, so a replacement is never
restored); it must carry a `matcher` leaving `Edit`/`Write` reachable, because
unparseable model output FAILS CLOSED and an unscoped hook denies the very
tools needed to remove it; and that matcher forces the one layout
`validate_hook_commands` misreports, which is why Task 4.0 comes first.

**The decisive finding, and it arrived from experiment rather than reading**:
a native hook's prompt does NOT have to be a static string. The `PreToolUse`
payload carries `tool_use_id`, which the daemon's hook and a native `agent`
hook both receive independently — so the daemon can compose a per-event prompt,
key it by that id, and the agent hook fetches it. Measured working end to end
(`EXPERIMENTS.md` §6).

That makes **confirm-the-positive** (`DECISIONS.md` §3c) reachable natively
after all — the daemon runs its regex first and invokes the model only on an
existing match — and it needs no API credentials of the daemon's own, because
Claude Code makes the call. The plan's leading architecture.

## Goals

- Establish, with evidence, what Claude Code's native LLM-driven hook support
  actually is, how it relates to this daemon, and whether it coexists with
  this daemon's own hooks (`RESEARCH-...md`).
- Confront the latency and determinism costs of AI-driven hook decisions
  honestly against this project's own stated performance premise and testing
  discipline, and test the "advisory = free" intuition rather than assume it
  (`DECISIONS.md` §1, §1b).
- Produce a ranked brainstorm of candidates, each scored on why a regex
  cannot do the job, which event it lives on, whether that event tolerates
  the latency, and which mechanism fits (`IDEAS.md`).
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
- Not adopting native `prompt`/`agent` hooks project-wide as policy. Phase 4
  only *prototypes*; broader adoption is a separate decision, and would need
  Task 4.0 first (`validate_hook_commands` misreports a native hook as a
  duplicate registration — `RESEARCH-...md`).
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

- [ ] ⬜ **Task 2.1**: Model call behind an injectable dependency (as
  `TranscriptReader`/`NitpickSetup` already are), so tests mock it.
- [ ] ⬜ **Task 2.2**: Deferred/async surfacing — the call must NOT run
  synchronously inside the `Stop` the user is waiting on; the finding
  surfaces on a later event (`DECISIONS.md` §1b). New infrastructure
  (background task, per-session cache, cleanup). Do not substitute a
  synchronous call that merely feels less bad than `PreToolUse`.
- [ ] ⬜ **Task 2.3**: Handler pinned to `AdvisoryResult` so a hallucinated
  DENY is unwritable; fail-open on every external error (no credential,
  timeout, network, rate limit) — no-opinion, never block or crash.
  Example A (`DECISIONS.md` §0) as a fixed regression case.

### Phase 3: Build the confirm-the-positive filter (qa_suppression, comment_changelog)

- [ ] ⬜ **Task 3.1**: Post-match hook, invoked ONLY where the existing regex
  already matched. Returns "confirmed" (block stands) or "mention, not use"
  (downgrade), and falls back to "confirmed" — today's exact behaviour — on
  any model error (`DECISIONS.md` §3c).
- [ ] ⬜ **Task 3.2**: Confirm it cannot break the acceptance-test strategy
  `CLAUDE.md` documents as intentional (literal dangerous strings embedded
  in safe commands must still block). Its question — "use vs mention" — is
  a different axis from "is this in command position", so the two should
  not collide; verify that rather than assume it.
- [ ] ⬜ **Task 3.3**: `qa_suppression` first (it has the live evidence),
  `comment_changelog` after. Example B (`DECISIONS.md` §0) and the four
  demoted signals as fixed regression cases.

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
- [ ] ⬜ **Task 4.1b**: Build out DYNAMIC PROMPTING — the leading architecture.
  Design, constraints and a working probe are in `EXPERIMENTS.md` §6 and
  `prototype/dynamic-prompt-probe.sh`. Non-negotiable: a missing prompt file
  MUST mean allow, so losing the ordering race degrades to today's behaviour.
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

**Revival conditions** — this plan is Dormant, so the first criterion is
whether to wake it. Any ONE of these is sufficient; none has occurred yet:

- [ ] A guard false-positives on something that **cannot be worked around by
  rewording** — i.e. it blocks content that genuinely must be written as-is.
  Both false positives on record were reworded away in under a minute, which
  is why they do not justify the machinery.

- [ ] The same guard false-positives **repeatedly enough to be a real tax**,
  rather than once in a long session.

- [ ] Evidence that a structural blind spot is actually being exploited — the
  clearest candidate is `tdd_enforcement`, which checks that a test file
  EXISTS and cannot check that it asserts anything (`IDEAS.md` #13).

- [ ] `agent` hooks lose their experimental designation, which removes the
  standing objection to the leading architecture.

- [x] `RESEARCH-claude-code-native-hooks.md`, `DECISIONS.md`, `IDEAS.md` and
  `EXPERIMENTS.md` answer the user's original question with evidence, not
  speculation, and honestly flag what could not be verified.

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

| Risk                                                                     | Impact                           | Probability                                                                  | Mitigation                                                                                                                  |
| ------------------------------------------------------------------------ | -------------------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| A model call blocks a hot-path event, daemon "feels slow"                | High — regresses core value prop | Medium if scope creeps past the deferred/confirm-the-positive designs        | Restrict Phases 2-3 to `DECISIONS.md` §1b/§3c's designs; no synchronous same-turn shortcut                                  |
| An AI handler's non-determinism breaks acceptance-test/QA discipline     | Medium                           | Medium                                                                       | Mock the model call in unit tests; assert decision-class stability, not exact wording; use Examples A/B as regression cases |
| A model-call failure blocks or crashes instead of failing open           | High                             | **Confirmed real** for native hooks — they fail CLOSED (`EXPERIMENTS.md` §1) | Tasks 2.3/3.1 require dedicated failure-mode tests; a native design must make the missing-prompt case ALLOW                 |
| Confirm-the-positive filter weakens a block the acceptance tests rely on | Medium                           | Low if Task 3.2 is explicit                                                  | Task 3.2 confirms the filter's axis ("use vs mention") differs from the tests' axis                                         |

## Delivery & Milestones

- Phase 1 research delivered at `a97d7128`, corrected at `aee09d9f`.
- Live experiments (`EXPERIMENTS.md`) at `3423b9f8`, `cb5802e2`, `d3d95d70`
  on branch `plan/00266-ai-assisted-hooks`.
