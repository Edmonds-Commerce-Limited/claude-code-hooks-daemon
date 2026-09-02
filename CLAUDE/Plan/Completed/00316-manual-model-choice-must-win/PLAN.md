# Plan 00316: manual model choice must win

**Status**: Complete
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: High (the machine actively overrode a human's typed choice)
**Recommended Executor**: Sonnet
**Execution Strategy**: Single python-developer agent, TDD

## Overview

Owner field report (2026-09-02, this live session): manually typing
`/model opus` in a fable session was registered by the model-change
machinery as a DOWNGRADE — the status-line fallback indicator fired, and
the ccy supervisor's decision log shows it went further and auto-restored
fable ("♻️ /model fable (auto-restore after downgrade)"), overriding the
human's deliberate choice. Detection of SILENT substitution (the harness
swapping models under load) is the valuable feature; a human typing a
model command is not a fallback, and nothing may fight it or nag about it.

The supervisor's PTY position makes the distinction cleanly available: a
manual change is preceded by the user TYPING a `/model ...` command
through the PTY input stream the supervisor itself forwards; a silent
substitution has no such input. Track the last user-initiated model
command (with a generous validity window) and treat any matching observed
model change as manual — suppressing both the supervisor auto-restore and
the daemon's fallback status-line indicator for that change.

The owner also ruled on the adjacent feature: per-model DEFAULT effort
coupling ("/effort low coupled to model switch" in the audit) is a liked
feature and should be kept and expanded — but as DEFAULTS only. Any
manual effort setting always wins over the coupling, exactly as any
manual model setting always wins over restore logic.

## Goals

- A user-typed `/model X` is never classified as a downgrade/fallback: no
  supervisor auto-restore, no status-line fallback indicator, no advisory.
- Silent substitution detection keeps working unchanged (no user-typed
  model command in the window → still flagged and still restorable).
- Per-model default effort remains applied on model change, expanded to a
  declared mapping (config), but an explicit manual `/effort` (typed by
  the user, or set for the session) always beats the coupled default —
  the coupling must not re-fire over a manual effort for the same model
  spell.
- Decision log entries name WHY each action was or was not taken
  ("manual change detected — no restore" vs "silent substitution —
  restoring").

## Non-Goals

- Changing what counts as the session's target model at launch.
- Any change to model_fallback_detector's handling of genuine silent
  fallbacks.
- Removing the effort coupling feature (it is liked; only its precedence
  is corrected).

## Tasks

### Phase 1: manual-change recognition

- [x] ✅ **Task 1.1**: RED — unit tests in the supervise test suite: a
  `/model opus` typed through the PTY input path within the validity
  window marks the subsequent observed model change as MANUAL (no
  restore, decision log says so); an observed change with no typed
  command in the window stays a fallback (restore fires as today); the
  window expires; rapid successive manual changes each count.
- [x] ✅ **Task 1.2**: GREEN — implement last-typed-model tracking in the
  supervisor input path (host tier — note the hot-reload contract:
  `_forward_io` runs in the PTY HOST, so live pickup needs a session
  restart or applies from the next session; the worker-tier decision
  logic hot-reloads) and consume it in the restore decision.
- [x] ✅ **Task 1.3**: Suppress the daemon status-line fallback indicator
  for a manual change: give the supervisor a way to record the manual
  change where `model_fallback_detector` can see it (shared untracked
  marker/ledger), TDD on the handler side.
  Correction during implementation: the field-report's status-line
  indicator is `downgrade_indicator` (self-detected purely from the
  model id Claude Code reports, no dependency on the supervisor), not
  `model_fallback_detector` (which only ever fires from the platform's
  OWN `model_refusal_fallback` transcript record — never on a manual
  `/model` command, so it was never the culprit). Fixed
  `downgrade_indicator`/`downgrade_state.py` to consult the shared
  marker instead.

### Phase 2: effort coupling precedence

- [x] ✅ **Task 2.1**: Config-declared per-model default effort mapping
  (keep current behaviour as the defaults); manual `/effort` recorded and
  honoured over the coupling until the user changes model again or
  re-sets effort. TDD.

### Phase 3: verification

- [x] ✅ **Task 3.1**: Full QA 25/25; live dogfood checklist journalled
  (manual `/model opus` → no indicator, no restore; then a forced silent
  substitution fixture → still detected). See `JOURNAL/` for the checklist
  and the hot-reload caveat.

## Success Criteria

- [x] Owner can type `/model opus` in a fable session and nothing fights
  or flags it — LIVE-CONFIRMED: no auto-restore, the shared marker written
  with the real session id, and the downgrade indicator reading
  `high_water_family: opus, downgraded: false` (see `JOURNAL/`).
- [x] Silent substitution still detected and restored.
- [x] Manual `/effort` always beats coupled defaults.
- [x] QA 25/25.

## Delivery & Milestones

- Recognition + classification: f7f939c4, 18e7652f
- Field-miss observability (typed-slash diagnostics): 7fe9f13b
- Latch survives busy spells; marker deferred until session known: da693aaa
- Test pollution of the live worker log removed: 07871229
