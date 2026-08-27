# Plan 00278: Model-Downgrade Resilience — Effort Restore + Security-Work Delegation

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

This plan bundles a second, complementary idea (joseph, 2026-08-27):
PREVENTION. The downgrade is triggered by security-flavoured content
accumulating in the fable main context. Routing security-related work
(exploit-adjacent code, credential-handling, attack-pattern analysis) into an
Opus subagent keeps that material out of the fable context entirely, so the
downgrade is less likely to fire at all. The two features are cross-related
for dogfooding: one prevents the downgrade, the other recovers the session's
effective capability when it happens anyway.

## Goals

- Context sidecar payload carries the live effort level (`effort`, nullable)
  read from the Status event, alongside the existing `model_id`.
- Supervisor detects a model-family downgrade for the SAME session across
  consecutive foreground sidecar readings and injects `/effort xhigh` once
  per downgrade, respecting the existing idle/empty-input-box gates.
- No injection when the post-downgrade effort is already `xhigh` or `max`.
- Dry-run mode injects the visible marker only, exactly like the other
  injection families.
- A guidance surface (advisory handler and/or resident CLAUDE.md guidance)
  steers security-flavoured work into an Opus subagent (`model: "opus"` on
  the Agent tool) so the fable main context stays clean of
  downgrade-triggering material.

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

- **Field report**:
  [FIELD-REPORT-fable-cyber-flags.md](FIELD-REPORT-fable-cyber-flags.md)
  (imported, generalised) documents the trigger: Fable's API-side `[cyber]`
  classifier keys on attack-mechanics CONTENT not intent, the fallback is
  session-scoped and silent (one estate ran degraded ~5.5h unnoticed), and the
  transcript JSONL records `model_refusal_fallback` /
  `content[].type == "fallback"` records. It ships a repo-level mitigation
  (opus-security subagent + trigger skill + path rule, delegate-BEFORE-reading
  invariant, clean-summary contract) and proposes two daemon handlers
  (`fable_flaggable_advisor`, `model_fallback_detector`) — direct input to
  Phase 3.

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

- [x] ✅ **Task 1.1**: TDD — extend `ContextSidecarHandler` payload with
  `effort` (string | null) from `hook_input["effort"]["level"]`; absent or
  malformed → null. Update sidecar unit tests.

### Phase 2: Supervisor downgrade detector (actuator)

- [x] ✅ **Task 2.1**: TDD — model family classifier + ranking in
  `claude-supervise.py` (pure functions; unknown → no rank).
- [x] ✅ **Task 2.2**: TDD — per-session model tracking in the tick decision
  path: remember `(session_id, family)` from the last foreground reading;
  on ranked downgrade with effort not in {xhigh, max}, decide an effort
  injection with payload `/effort xhigh`; one-shot cap per downgrade,
  reset when the family recovers; state carried in the machine state dict
  so host and worker never diverge.
- [x] ✅ **Task 2.3**: TDD — injection wiring: dry-run marker vs armed real
  command, empty-input-box deferral, decision.log lines, success-only cap
  counting (mirror goal injection).

### Phase 2b: Per-model minimum effort + model restore (joseph, 2026-08-27)

- [x] ✅ **Task 2b.1**: Research — confirm via the Claude Code guide whether
  an OFFICIAL per-model minimum/default effort mechanism exists. Answer: NO
  (Decision 4) — effort is a single global setting that survives a
  safety-triggered fallback unchanged; the supervisor mechanism stands.
- [x] ✅ **Task 2b.2**: Design + TDD — per-model minimum effort map in the
  supervisor (e.g. fable: low, opus: high, sonnet: high; configurable): when
  the foreground sidecar's live effort ranks BELOW the configured minimum for
  its model family, inject `/effort <minimum>`. Subsumes the Phase 2
  downgrade trigger (which becomes the special case "opus minimum = xhigh
  after a downgrade") — reconcile the two so there is ONE effort-injection
  family.
- [ ] ⬜ **Task 2b.3**: Design + TDD — model restore: the fallback is
  session-sticky, but flipping back manually works once the flaggable turn
  has passed. After a detected downgrade, inject `/model fable` a configured
  interval after the block (measured in supervisor-observable units — sidecar
  render progress/time, since the supervisor cannot count turns directly),
  followed by an `/effort <fable minimum>` reset — the ONE sanctioned
  effort-lowering: fable at xhigh eats account allowance, so a successful
  flip-back returns effort to fable's configured floor (joseph,
  2026-08-27). Guard against a flip-flop loop (re-downgrade backoff/cap).

### Phase 3: Security-work delegation (prevention)

- [ ] ⬜ **Task 3.1**: Design — decide the surface(s), taking the field
  report's proposals as the starting point: `fable_flaggable_advisor`
  (advisory, configurable flaggable path globs + topic terms, pointing at an
  opus-security subagent) and `model_fallback_detector` (advisory scan of the
  live transcript for `model_refusal_fallback` records — the report calls
  this the highest-value, lowest-risk piece). Honour the report's boundaries:
  delegate-BEFORE-reading (decide from framing/path, never by opening the
  content), clean-summary contract, and a NARROW trigger set (only
  attack-mechanics-describing work delegates — not all security work).
  Record trigger heuristics as a Technical Decision before implementing.
- [ ] ⬜ **Task 3.2**: TDD — implement the chosen surface(s); advisory-only,
  never blocking; rate-limited per session.
- [ ] ⬜ **Task 3.3**: Dogfood — enable in this repo's config; verify the
  advisory fires on a representative security task and that the delegation
  guidance names `model: "opus"` explicitly.

### Phase 3b: Downgrade snapshot capture (joseph, 2026-08-27)

- [ ] ⬜ **Task 3b.1**: Design + TDD — when a cyber downgrade is detected
  (the transcript's `model_refusal_fallback` record — natural home is the
  `model_fallback_detector` surface from Task 3.1), capture a DIAGNOSTIC
  SNAPSHOT: the fallback record itself (originalModel, fallbackModel,
  apiRefusalCategory, scope, timestamp) plus a bounded window of the
  preceding transcript (the prompt/content that tripped the classifier),
  written to a dated file under a configurable reports dir (default
  `untracked/reports/`). Purpose: let a project diagnose WHY it gets
  flagged and fine-tune its delegation config (path globs, topic terms).
  Secret-word redaction applies to everything written; snapshots live in
  untracked/ and are never auto-committed.

### Phase 3c: Config surface (joseph, 2026-08-27)

- [ ] ⬜ **Task 3c.1**: ALL Plan 00278 features get first-class config with
  the classic clobber-or-extend convention (`mode: additive | replace`,
  matching `command_hints`/`goal_injection`): per-model effort floors,
  downgrade target, caps/cooldowns, model-restore timing, flaggable
  path globs + topic terms, snapshot dir + window size. Daemon-side
  options live under the owning handler in `.claude/hooks-daemon.yaml`;
  supervisor-side values resolve via ccy env (documented in one place).
  Record the split as a Technical Decision; config-changes manifest entry.

### Phase 4: Integration & closure

- [ ] ⬜ **Task 4.1**: Full QA (`./scripts/qa/llm_qa.py all`), daemon restart
  RUNNING, supervisor version-lockstep test still green.
- [ ] ⬜ **Task 4.2**: Docs — supervisor top-of-file behaviour summary and
  any doc that enumerates injection families; config-changes manifest entry
  for any new handler/option.
- [ ] ⬜ **Task 4.3**: Complete plan (archive, README row, journal closure).

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

### Decision 4: No official per-model effort exists — supervisor owns it

**Context**: Task 2b.1 — checked the Claude Code guide before building.
**Decision**: Claude Code has NO per-model effort configuration: `effortLevel`
(settings.json) / `CLAUDE_CODE_EFFORT_LEVEL` are single global settings, and
the docs state the effort setting carries over unchanged through a
safety-triggered model fallback with no documented reset. Skill/agent
frontmatter `effort:` covers only skill/subagent scope. So the per-model
minimum map (Task 2b.2) is legitimately the supervisor's job, not a
reimplementation of an official feature.
**Date**: 2026-08-27

## Success Criteria

- [ ] Sidecar JSON includes `effort` on every render; null-safe.
- [ ] Simulated fable→opus transition in unit tests yields exactly one
  `/effort xhigh` injection decision; opus→fable yields none; xhigh/max
  effort yields none; different-session switch yields none.
- [ ] Dry-run fires the marker only; armed fires the real command.
- [ ] Security-work delegation surface exists, is advisory-only, names an
  Opus subagent as the destination, and is dogfood-enabled in this repo.
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
