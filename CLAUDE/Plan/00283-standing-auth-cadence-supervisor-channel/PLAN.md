# Plan 00283: Standing-auth reinforcement cadence + supervisor-typed channel

**Status**: In Progress
**Created**: 2026-08-28
**Owner**: joseph / Claude
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`standing_authorisations` (Plan 00223) re-injects a project's recorded
authorisations as folded `hook_additional_context` on **every**
UserPromptSubmit. That is reliable but noisy — the short-form text rides along
on every prompt, including automated failsafe-recovery ticks — and
`hook_additional_context` is the weakest channel available: it sits below a
genuine user-role turn in influence.

This plan does two coupled things:

1. **Reduce the cadence.** Deliver the FULL text once per session to establish
   it, then reinforce only on whichever comes first: **N user prompts** or
   **T minutes** since the last delivery. Fewer, deliberately-spaced
   reinforcements instead of one-per-prompt.

2. **Use a stronger channel when available.** Where the ccy PTY supervisor is
   armed and watching, route the reinforcement through it as a **real typed
   user-role line** (mirroring `goal_injection`'s `*.goal-intent` →
   supervisor-types-`/goal` contract), falling back to folded hook-context
   when no supervisor is armed. Lower frequency *buys* the louder channel: a
   real turn outranks hook meta-context, so it can afford to fire rarely.

The 00223 reliability finding (a per-request system-prompt restriction needs a
per-*session*-recurring answer that survives compaction) is preserved: the new
cadence still delivers many times per session and still survives compaction —
it only drops the redundant one-per-prompt repeats.

## Goals

- Replace the hardcoded "full ×3 then short every prompt" decay with:
  first delivery full; thereafter reinforce on `>= prompt_interval` prompts
  OR `>= interval_minutes` elapsed, whichever fires first (short form).
- When a supervisor is armed+watching, reinforce by writing a
  `*.standing-auth-intent` signal the supervisor types as a real user-role
  line at its next idle choke point; otherwise inject folded hook-context.
- Never create an injection loop: a supervisor-typed reinforcement is itself a
  new UserPromptSubmit carrying the fixed machine-origin marker — the handler
  must recognise its own marker and neither count it nor re-signal on it.
- Keep every existing invariant: ships disabled upstream (Decision 3), text is
  a recorded request never a countermand (Decision 2), never blocks.
- Make the cadence tunable in config, and document the new options in a
  `config-changes/` manifest so existing installs are told.

## Non-Goals

- No change to WHICH authorisations exist or their wording semantics. Plan
  00280 (Not Started) separately adds model-cap advisory text to this handler;
  this plan is orthogonal and must not conflict with it — coordinate on the
  shared file at merge time.
- Not making the supervisor mandatory: unsupervised sessions keep working via
  the hook-context fallback with identical cadence.
- Not flipping the upstream default: every entry still ships disabled.

## Context & Background

Signalling contract mapped from `goal_injection` (authoritative reference is
`goal_injection.py` + `.claude/ccy/claude-supervise.py`):

- **Shared dir**: `ProjectContext.daemon_untracked_dir() / "context-sidecar"`,
  resolved independently by daemon and supervisor (no cross-import). Supervisor
  mirror: `_daemon_untracked_dir()` + `_default_sidecar_dir()`.
- **Signal file**: `<sanitised-session>.<suffix>` where suffix is NOT `.json`
  (so the sidecar JSON reader ignores it). Body is JSON with at least
  `{session_id, ts}` so the supervisor's own-session scope filter and TTL work.
  Atomic temp-then-`replace`, fail-open.
- **Supervisor consumes at an idle choke point only** (NOOP tick, empty input
  box, MONITOR state), strictly subordinate to compact/continue. Best existing
  template is the `*.model-switch-intent` signal plumbing.
- **Armed-detection**: the supervisor writes a status file under
  `untracked/supervise/` (`write_supervisor_status`) that a SessionStart
  advisory already reads to tell whether a supervisor is live + current. The
  handler reuses that to decide channel.
- **Idle-only consequence**: supervisor injection lands at task boundaries, so
  the FIRST (establishing) delivery stays immediate hook-context; supervisor
  routing applies to the later reinforcements.
- **Lockstep**: `claude-supervise.py` carries a version pinned to the daemon
  (existing test). Any header/marker constant shared across the two ends gets a
  lockstep equality test, exactly as `_GOAL_HEADER_TEXT` does today.

## Tasks

### Phase 1: Cadence rework (handler-only, no supervisor dependency) ✅

- [x] ✅ **Task 1.1**: Replace `_FULL_TEXT_DELIVERIES` decay with cadence state.
  - [x] ✅ Track per session: last-delivery timestamp, prompts-since-last count
    (new `_SessionState` dataclass, injectable `_clock`).
  - [x] ✅ Deliver full text on the first delivery of a session; short form after.
  - [x] ✅ Reinforce when `prompts_since_last >= prompt_interval` OR
    `minutes_since_last >= interval_minutes`; else stay silent.
  - [x] ✅ Keep the bounded/FIFO per-session map shape; reset on daemon restart.
- [x] ✅ **Task 1.2**: Exclude automated ticks from the prompt counter.
  - [x] ✅ Robust signal chosen: match a small set of STABLE machine-origin
    markers (`FAILSAFE RECOVERY CHECK`, `🤖 [ccy-supervisor]`) — Claude Code
    exposes no automated-vs-human flag. The supervisor marker also gives the
    Phase 2/3 loop-guard for free.
- [x] ✅ **Task 1.3**: TDD — cadence tests (first-full, N-prompt trigger,
  T-minute trigger via injected clock, silence between, per-session reset,
  automated-tick exclusion, loop-guard). 37 pass; handler 98% covered.

### Phase 2: Channel routing in the handler ✅

- [x] ✅ **Task 2.1**: Armed-detection helper — `armed_supervisor_live` in the
  shared `utils/ccy_supervisor` (Phase 2a): config-armed AND pid-alive AND
  source-current.
- [x] ✅ **Task 2.2**: On a reinforcement tick with a supervisor armed, write a
  `<session>.standing-auth-intent` signal (atomic, fail-open, `{ts, session_id, rendered_lines, source}` body) instead of injecting hook-context.
  - [ ] ⬜ Fixed machine-origin header + lockstep test — DEFERRED to Phase 3:
    the lines self-identify and the machine-origin marking is the supervisor's
    `🤖 [ccy-supervisor` prefix, so the lockstep (daemon marker == supervisor
    `_BOT_PREFIX`) belongs with the Phase 3 consumer where both ends exist.
- [x] ✅ **Task 2.3**: Hook-context fallback when no supervisor is armed; the
  FIRST/establishing delivery is always immediate hook-context.
- [x] ✅ **Task 2.4**: Loop-guard — the handler's own supervisor-typed line
  carries `🤖 [ccy-supervisor`, matched by `_is_automated_prompt` (Phase 1
  marker fix), so it neither counts nor re-signals.
- [x] ✅ **Task 2.5**: TDD — routing tests (armed→signal, unarmed→context,
  write-fail→context, first-always-context, channel-off→never-routes,
  no-project-context→context). 49 tests; handler 98.77%.

### Phase 3: Supervisor consumer (`claude-supervise.py`)

- [ ] ⬜ **Task 3.1**: New glob + TTL + `load_standing_auth_signal` reader with a
  fail-closed validation gate (header allowlist, len/line/control caps),
  mirroring `load_goal_signal` / `_validate_goal_lines`.
- [ ] ⬜ **Task 3.2**: A subordinate branch in `decide_once` below
  compact/continue/goal; type the line via `_perform_injection` (raw text
  \+ marker, no slash command); dry-run marker; consume-on-success only.
- [ ] ⬜ **Task 3.3**: TDD in `tests/unit/supervise/` incl. the lockstep
  header-equality test; keep the daemon/supervisor version test green.

### Phase 4: Config + docs

- [ ] ⬜ **Task 4.1**: Add `interval_minutes`, `prompt_interval`, and a
  supervisor-channel toggle to the handler options (sane defaults 15 / 5 /
  auto); read via the registry setattr pattern.
- [ ] ⬜ **Task 4.2**: `config-changes/vX.Y.Z.yaml` entry (staged in
  `UNRELEASED/config-changes/`) documenting the new options.
- [ ] ⬜ **Task 4.3**: Update `get_claude_md()` and `HANDLER_REFERENCE.md` to
  describe the new cadence and channel.

### Phase 5: Verification

- [ ] ⬜ **Task 5.1**: Full QA (`./scripts/qa/llm_qa.py all`), daemon restart
  RUNNING, guidance-coverage gate green.
- [ ] ⬜ **Task 5.2**: Client-mode check IF any path/interpreter/wrapper/asset
  surface was touched (the signal dir + supervisor status file are
  install-mode-dependent, so this is likely required).
- [ ] ⬜ **Task 5.3**: Update/extend the handler's `get_acceptance_tests()`.

## Technical Decisions

### Decision 1: First delivery stays immediate hook-context, not supervisor

**Context**: the supervisor types only at an idle choke point, so a
supervisor-routed establishing delivery could be deferred past the point where
the authorisation first matters.
**Decision**: the first (full) delivery per session is always immediate folded
hook-context; supervisor routing applies only to later reinforcements. This
also means an unarmed session and an armed session behave identically on turn
one.

### Decision 2: Cadence is prompt-driven, so "T minutes" means "first prompt after T"

**Context**: the handler runs only on UserPromptSubmit; it cannot fire on a
wall-clock timer alone.
**Decision**: "interval_minutes" is evaluated at each prompt as
"elapsed since last delivery >= T". An idle session therefore reinforces at
most once per T, on its next prompt — which also quiets idle sessions
naturally.

## Success Criteria

- [ ] First prompt of a session delivers the full text; subsequent prompts are
  silent until N-prompts or T-minutes, then deliver the short form.
- [ ] Armed+watching supervisor → reinforcement arrives as a real typed line;
  unarmed → folded hook-context; first delivery always hook-context.
- [ ] No injection loop from the supervisor-typed line (own-marker guard).
- [ ] Ships disabled upstream unchanged; never blocks; 95%+ coverage.
- [ ] Full QA passes; daemon restarts RUNNING; supervisor version test green.

## Dependencies

- Related: Plan 00280 (Not Started) — also edits `standing_authorisations`
  (model-cap advisory text). Orthogonal; coordinate at merge.
- Pattern precedent: Plan 00269 (Complete) — supervisor goal-message injection.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes; blow-by-blow in JOURNAL/. -->

- (none yet)
