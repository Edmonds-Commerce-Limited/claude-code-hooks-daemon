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
- [x] ✅ **Task 2b.3**: Design + TDD — model restore: the fallback is
  session-sticky, but flipping back manually works once the flaggable turn
  has passed. After a detected downgrade, inject `/model fable` a configured
  interval after the block (measured in supervisor-observable units — sidecar
  render progress/time, since the supervisor cannot count turns directly),
  followed by an `/effort <fable minimum>` reset — the ONE sanctioned
  effort-lowering: fable at xhigh eats account allowance, so a successful
  flip-back returns effort to fable's configured floor (joseph,
  2026-08-27). Guard against a flip-flop loop (re-downgrade backoff/cap).

### Phase 3: Security-work delegation (prevention)

- [x] ✅ **Task 3.1**: Design (Decision 5) — decide the surface(s), taking the field
  report's proposals as the starting point: `fable_flaggable_advisor`
  (advisory, configurable flaggable path globs + topic terms, pointing at an
  opus-security subagent) and `model_fallback_detector` (advisory scan of the
  live transcript for `model_refusal_fallback` records — the report calls
  this the highest-value, lowest-risk piece). Honour the report's boundaries:
  delegate-BEFORE-reading (decide from framing/path, never by opening the
  content), clean-summary contract, and a NARROW trigger set (only
  attack-mechanics-describing work delegates — not all security work).
  Record trigger heuristics as a Technical Decision before implementing.
- [x] ✅ **Task 3.2**: TDD — implement the chosen surface(s); advisory-only,
  never blocking; rate-limited per session. Delivered as
  `model_fallback_detector` (SessionStart) and `flaggable_work_advisor`
  (PreToolUse, ships disabled), tests first.
- [x] ✅ **Task 3.3**: Dogfood — enable in this repo's config; verify the
  advisory fires on a representative security task and that the delegation
  guidance names `model: "opus"` explicitly.

### Phase 3d: Blocking surfaces (deferred until advisories dogfood cleanly)

- [ ] ⬜ **Task 3d.1**: Deny content-revealing git/grep over configured
  flaggable paths by command shape (handover §3.3).
- [ ] ⬜ **Task 3d.2**: Enforce the `*-opus-security-DETAIL*` read-boundary
  by pattern (handover §3.4).

### Phase 3b: Downgrade snapshot capture (joseph, 2026-08-27)

- [x] ✅ **Task 3b.1**: Design + TDD — when a cyber downgrade is detected
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

- [x] ✅ **Task 3c.1** (daemon-side: options with `mode: additive | replace`
  on `flaggable_work_advisor`, snapshot dir + window on
  `model_fallback_detector`, config-changes manifest entries;
  supervisor-side: `CCY_MIN_EFFORT_LEVELS` + `CCY_MODEL_RESTORE_SECONDS`
  env config shipped in Phase 2b; split recorded as Decision 6): ALL Plan 00278 features get first-class config with
  the classic clobber-or-extend convention (`mode: additive | replace`,
  matching `command_hints`/`goal_injection`): per-model effort floors,
  downgrade target, caps/cooldowns, model-restore timing, flaggable
  path globs + topic terms, snapshot dir + window size. Daemon-side
  options live under the owning handler in `.claude/hooks-daemon.yaml`;
  supervisor-side values resolve via ccy env (documented in one place).
  Record the split as a Technical Decision; config-changes manifest entry.

### Phase 5: Live-dogfooding burst (2026-08-27, joseph in session)

- [x] ✅ **Task 5.1**: Detector recovery-fix — distinguish an ACTIVE fallback
  from one a later assistant turn already recovered from; soft notice for
  recovered, loud alert only while active.
- [x] ✅ **Task 5.2**: Status-line `downgrade_indicator` — per-session
  model-family high-water state; renders `⚠️{high}→{current}` only while a
  downgrade is live; no supervisor dependency.
- [x] ✅ **Task 5.3**: Manual model-switch trigger — `*.model-switch-intent`
  signal + `--emit-model-switch <family>` CLI; eager insert (empty-input-box
  gate only); `/model` confirm-Enter (payload → \\r → delay → \\r). PROVEN live:
  opus→fable switch fired and landed.
- [x] ✅ **Task 5.4**: Coupled effort correction — EVERY `/model` injection
  (manual and auto-restore) arms an unconditional `/effort` on the next
  injectable tick: top family → its floor (sanctioned lowering), else xhigh.
  Manual switches no longer consume the auto-restore cap/backoff.
- [x] ✅ **Task 5.5**: Ship `model_fallback_detector` DISABLED by default
  (Decision 7); dogfood config keeps it on.
- [x] ✅ **Task 5.6**: Live re-test PASSED hands-free (decision.log 12:32:00
  `/model fable` → 12:32:03 coupled `/effort low`, no human keypress, end
  state fable low). First round exposed that `/effort` needs its own
  confirming Enter — added as `CCY_EFFORT_CONFIRM_ENTERS` (default 1),
  worker-side only so a hot-reload deployed it.
- [ ] ⬜ **Task 5.7** (proposed, awaiting joseph): mid-session fallback
  detection on UserPromptSubmit (turn-gated live scan) to replace the
  SessionStart-only surface.

### Phase 4: Integration & closure

- [x] ✅ **Task 4.1**: Full QA (`./scripts/qa/llm_qa.py all`), daemon restart
  RUNNING, supervisor version-lockstep test still green. (QA 25/25 on the
  merged tree at f0a9dc33; daemon RUNNING; lockstep test in the passing suite.)
- [x] ✅ **Task 4.2**: Docs — supervisor top-of-file behaviour summary and
  any doc that enumerates injection families; config-changes manifest entry
  for any new handler/option. (Supervisor header documents all families +
  raise-only invariant; vUNRELEASED manifest carries model_fallback_detector
  and flaggable_work_advisor entries.)
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

### Decision 5: Two daemon surfaces — detector (enabled) + advisor (opt-in)

**Context**: Task 3.1/3.2 surface choice, from the field report's proposals.
**Decision**: (a) `model_fallback_detector` — SessionStart, ADVISORY,
default-enabled, model-agnostic: keys on the transcript's
`model_refusal_fallback` record (assistant `content[].type == "fallback"`
blocks as corroboration), fail-silent per malformed record, loud
PROTECTION-DEGRADED-style alert, once per session per distinct record, plus a
secret-redacted diagnostic snapshot (record + bounded preceding-record
window; options `snapshot_enabled`/`snapshot_dir`/`snapshot_window_records`;
write failures degrade to an advisory mention). (b) `flaggable_work_advisor`
— PreToolUse, ADVISORY (never DENY, non-terminal), ships DISABLED: fires when
Read/Edit/Write/Grep targets a `flaggable_path_globs` match, a Bash command
mentions one, or the tool input carries 2+ `flaggable_topic_terms` (narrow
seed: spoof, spoofing, evasion, exploit, rootkit); advises delegating the
whole sub-task to `quarantine_agent` (default `hooks-daemon-opus-security`)
BEFORE opening the content; `mode: additive | replace` merging
(`command_hints` convention); rate-limited once per session per matched path.

Deferred within this plan: the report's §3.3 (deny content-revealing
git/grep over flaggable paths by command shape) and §3.4 (enforce the
`*-opus-security-DETAIL*` read-boundary) — blocking surfaces, added as
Phase 3d after the advisories dogfood cleanly.

**Date**: 2026-08-27 (default-enabled choice for the detector REVISED by
Decision 7 — it now ships disabled/opt-in)

### Decision 6: config split — daemon YAML vs supervisor env (Task 3c.1)

**Context**: where each 00278 feature's configuration lives.
**Decision**: daemon-side features (the two Phase 3 handlers, snapshot
options) configure under their handler keys in `.claude/hooks-daemon.yaml`,
with `mode: additive | replace` merging for list options. Supervisor-side
features (effort floors, model-restore timing) configure via ccy env vars —
`CCY_MIN_EFFORT_LEVELS`, `CCY_MODEL_RESTORE_SECONDS` — because the
standalone supervisor deliberately imports nothing from the daemon (no
YAML/pydantic), and env resolution keeps the host and its policy worker
subprocess in agreement. Both halves are documented at their point of use.
**Date**: 2026-08-27

### Decision 7: model_fallback_detector ships DISABLED (opt-in) — dogfood verdict

**Context**: dogfooding it in the noisiest possible estate (this repo, doing
flaggable work) showed the SessionStart surface spamming: a huge alert block
plus one snapshot file PER distinct record at every session start, reporting
fallbacks that had already happened. For a normal project it essentially
never fires; the continuous "am I downgraded?" signal is carried better by
the `downgrade_indicator` status line (ships enabled).
**Decision** (joseph, 2026-08-27): flip the default to disabled with a
"probably leave OFF" hint in the config template; keep it enabled only in
this repo's dogfood config, where the diagnostic snapshots earn their keep
tuning delegation config.
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

- Phases 1–3c delivered through f0a9dc33 (QA 25/25 on merged tree)
- Detector recovery-fix at 3e23dff2; benign classifier-trip fixture at 3b028d4b
- Confirm-Enter + manual model-switch signal at d8379072 (flip PROVEN live)
- Status-line downgrade_indicator merged at 3a89c867
- Coupled effort correction merged at efbaf2b7
- Detector default flipped to opt-in at 2af2f579
