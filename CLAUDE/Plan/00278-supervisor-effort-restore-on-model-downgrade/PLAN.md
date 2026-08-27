# Plan 00278: Supervisor Effort Restore on Model Downgrade

**Status**: In Progress
**Created**: 2026-08-27
**Owner**: Claude (requested by joseph)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

A session running Fable at low effort can be transparently switched to Opus
(e.g. a safety-triggered model downgrade). The session then inherits the LOW
effort setting — but "Fable low" and "Opus low" are not equivalent: the
intended fallback is Opus at XHIGH effort. Nothing in the session reacts to
the switch today.

The ccy PTY supervisor already has both halves of the mechanism: the daemon's
observe-only context sidecar records `model_id` on every status render, and
the supervisor's tick loop already turns decisions into keystroke injections
(`/compact`, `continue`, `/goal`). This plan adds a model-downgrade detector:
the supervisor tracks the foreground session's model family across ticks and,
on a downgrade transition (fable → opus), injects `/effort xhigh` once —
unless the live effort is already xhigh or max, which requires the sidecar to
also carry the live effort level.

## Goals

- Context sidecar payload carries the live effort level (`effort`, nullable)
  read from the Status event, alongside the existing `model_id`.
- Supervisor detects a model-family downgrade for the SAME session across
  consecutive foreground sidecar readings and injects `/effort xhigh` once
  per downgrade, respecting the existing idle/empty-input-box gates.
- No injection when the post-downgrade effort is already `xhigh` or `max`.
- Dry-run mode injects the visible marker only, exactly like the other
  injection families.

## Non-Goals

- No reaction to model UPGRADES, and no attempt to distinguish a deliberate
  user model switch from a forced downgrade (a one-shot `/effort xhigh` is
  visible and trivially reversible, so firing on any ranked downgrade is
  accepted).
- No daemon-side injection — the observe-only boundary stands (daemon
  senses, supervisor actuates).
- No new config surface unless a real need appears; constants in the
  supervisor mirror the other injection families.

## Context & Background

- Sensor: `src/claude_code_hooks_daemon/handlers/status_line/context_sidecar.py`
  already writes `model_id` per render; `model_context.py` already reads the
  live effort from `hook_input["effort"]["level"]` — the sidecar addition
  reuses that extraction rule (live field only; the settings.json fallback is
  a display concern, not a sensor concern).
- Actuator: `.claude/ccy/claude-supervise.py` `decide_once()` composes the
  tick decision; goal injection (Plan 00269) is the closest template —
  per-family cap, success-only counting, empty-input-box deferral.
- Model family ranking (highest first): fable/mythos, opus, sonnet, haiku —
  matched by substring on `model_id`. A transition from a higher-ranked to a
  lower-ranked family is a downgrade. Unknown families never trigger.
- Session identity: the downgrade must be observed on the SAME `session_id`
  (a thread/terminal switch to a different session is not a downgrade).

## Tasks

### Phase 1: Sidecar effort field (sensor)

- [ ] ⬜ **Task 1.1**: TDD — extend `ContextSidecarHandler` payload with
  `effort` (string | null) from `hook_input["effort"]["level"]`; absent or
  malformed → null. Update sidecar unit tests.

### Phase 2: Supervisor downgrade detector (actuator)

- [ ] ⬜ **Task 2.1**: TDD — model family classifier + ranking in
  `claude-supervise.py` (pure functions; unknown → no rank).
- [ ] ⬜ **Task 2.2**: TDD — per-session model tracking in the tick decision
  path: remember `(session_id, family)` from the last foreground reading;
  on ranked downgrade with effort not in {xhigh, max}, decide an effort
  injection with payload `/effort xhigh`; one-shot cap per downgrade,
  reset when the family recovers; state carried in the machine state dict
  so host and worker never diverge.
- [ ] ⬜ **Task 2.3**: TDD — injection wiring: dry-run marker vs armed real
  command, empty-input-box deferral, decision.log lines, success-only cap
  counting (mirror goal injection).

### Phase 3: Integration & closure

- [ ] ⬜ **Task 3.1**: Full QA (`./scripts/qa/llm_qa.py all`), daemon restart
  RUNNING, supervisor version-lockstep test still green.
- [ ] ⬜ **Task 3.2**: Docs — supervisor top-of-file behaviour summary and
  any doc that enumerates injection families.
- [ ] ⬜ **Task 3.3**: Complete plan (archive, README row, journal closure).

## Dependencies

- Related: Plan 00269 (goal injection — template), Plan 00135 (sidecar/
  supervisor split), Plan 00035 (Blocked; generic StatusLine cache — not a
  prerequisite).

## Technical Decisions

### Decision 1: Detect via sidecar model_id transition, inject from supervisor

**Context**: where to detect and who acts.
**Decision**: the daemon stays observe-only (Plan 00135 boundary); the
supervisor compares consecutive foreground readings and injects. No new
signal file is needed — unlike goal injection, the trigger is derivable from
the sidecar stream itself.
**Date**: 2026-08-27

### Decision 2: Ranked-family downgrade, not fable→opus literal

**Context**: hardcoding one pair vs a ranking.
**Decision**: a small ordered family ranking (fable/mythos > opus > sonnet >
haiku); any ranked downgrade triggers. Same cost as the literal pair, covers
opus→sonnet fallbacks too, and unknown ids are inert.
**Date**: 2026-08-27

### Decision 3: Skip when effort already xhigh/max

**Context**: avoid clobbering a session already at high effort.
**Decision**: sidecar carries the live effort; the detector treats null as
"unknown → inject anyway" (the injection is idempotent and visible), and
skips only on a positive xhigh/max reading.
**Date**: 2026-08-27

## Success Criteria

- [ ] Sidecar JSON includes `effort` on every render; null-safe.
- [ ] Simulated fable→opus transition in unit tests yields exactly one
  `/effort xhigh` injection decision; opus→fable yields none; xhigh/max
  effort yields none; different-session switch yields none.
- [ ] Dry-run fires the marker only; armed fires the real command.
- [ ] All QA green; daemon restarts RUNNING; supervisor lockstep test green.

## Risks & Mitigations

| Risk                                                  | Impact | Probability | Mitigation                                                              |
| ----------------------------------------------------- | ------ | ----------- | ----------------------------------------------------------------------- |
| Downgrade happens mid-turn; sidecar renders pause     | Low    | Medium      | Detector compares across ticks; fires on the next fresh reading         |
| User deliberately switched models; injection unwanted | Low    | Low         | One-shot, visible, trivially reversible with /effort; documented        |
| Worker/host state divergence duplicates the injection | Medium | Low         | State rides the existing machine state dict (same fix as Plan 00164 P4) |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). The activity log lives in JOURNAL/. -->

- (pending)
