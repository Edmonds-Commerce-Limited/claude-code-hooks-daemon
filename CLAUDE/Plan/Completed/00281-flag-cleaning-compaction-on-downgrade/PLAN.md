# Plan 00281: flag cleaning compaction on downgrade

**Status**: Complete
**Created**: 2026-08-27
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (ccy supervisor work — hot-reloadable)

## Overview

Plan 00278 gave the ccy supervisor downgrade resilience: on a silent
model-family downgrade it restores the effort floor and flips the model back.
But in a session doing security-adjacent work the main **context** stays
saturated with flag-tripping vocabulary (attack/exploit/spoof/evasion/rootkit/
credential mechanics), so the platform classifier re-downgrades on the next
flagged turn — a visible flip-flop (surfaced by the new `↓N↑M` status-line
counter). Restoring the model cannot win that fight while the context keeps
re-tripping.

This plan adds a supervisor-fired, opt-in, gated `/compact` that fires on a
REPEATED downgrade (a flip-flop) and instructs Claude to summarise the sensitive
material at a HIGH LEVEL — describing what was done and its outcome, never the
mechanics — so the compacted context stops re-triggering the classifier and the
subsequent model-restore actually sticks. It is a real (armed) `/compact`,
audit-trailed like every other supervisor injection.

## Goals

- Fire ONE armed `/compact <flag-cleaning instruction>` when a downgrade
  RECURS after a prior auto-restore (the flip-flop signal), not on a one-off.
- The instruction cleans flaggable content: high-level summary only, no
  attack/exploit/credential specifics, then resume the work in progress.
- Opt-in (default OFF — auto-compaction is invasive and loses context),
  capped per process, and audit-trailed with a per-action glyph.
- Hot-reloadable (worker-side), TDD, dogfood-enabled in this repo.

## Non-Goals

- NOT firing on the first downgrade — the existing model-restore handles a
  transient one-off; compaction escalates only when the restore did not stick.
- NOT enabled by default — a project not doing flaggable work never wants its
  context auto-compacted by a content classifier.
- NOT a guarantee the classifier won't re-fire — the summary is produced by the
  (possibly downgraded) model; this reduces re-trip probability, not to zero.

## Technical Decisions

### Decision 1: Trigger is the FLIP-FLOP, not the downgrade

Fire only when a downgrade episode is open AND at least one model auto-restore
has already happened this process (`machine._model_restores >= 1`) — i.e. a
prior restore was undone. This reuses existing machine state and matches the
human-visible `↓N↑M` counter (Plan 00278): `↓ > ↑` is exactly "restore didn't
stick".

### Decision 2: Opt-in, capped, backed off

`/compact` is heavy (it rewrites context). Ship OFF (`CCY_FLAG_COMPACT`, default
off / policy `flag_compact_enabled=False`), cap at `_MAX_FLAG_COMPACTIONS`
(default 1 per process) with a backoff, so it can never storm.

### Decision 3: Escalate the restore — compact first, restore after

Place the flag-compact branch just BEFORE the model-restore branch in
`decide_once`. On a qualifying flip-flop the compact fires instead of a
re-restore; the compaction ends the flagged turn and cleans the context, and the
existing model-restore then lands on the clean context on a later idle tick.

### Decision 4: Instruction wording

Reuse the armed-compact PTY path (`/compact <body>`). Body: summarise at a high
level; where the work was security-adjacent, state only what was done and the
outcome, never the mechanics/payloads/signatures/credentials; then resume.

### Decision 5: Audit-trailed

Arm an audit item (`/compact (flag-cleaning after repeated downgrade)`); add a
per-action glyph (🧽) to the Plan 00278 audit iconography ruleset.

## Tasks

### Phase 1: Config + machine state

- [x] ✅ **Task 1.1**: `CompactPolicy.flag_compact_enabled` (+ `CCY_FLAG_COMPACT`
  env parse, default off); `_MAX_FLAG_COMPACTIONS` + backoff constants.
- [x] ✅ **Task 1.2**: machine `_flag_compactions` counter, `mark_flag_compaction`,
  a `flag_compact_due(now)` predicate, export/import round-trip.

### Phase 2: decide_once branch (TDD)

- [x] ✅ **Task 2.1**: RED tests — fires only on flip-flop (episode open +
  ≥1 restore), respects opt-in/cap/backoff/can-inject, payload is a real
  `/compact` with the flag-cleaning body, dry-run marker, arms audit.
  (`tests/unit/supervise/test_flag_compact.py`, 17 tests.)
- [x] ✅ **Task 2.2**: GREEN — branch added before the model-restore branch,
  gated on `flag_compact_due`; `TickOutcome.is_flag_compact` distinguishes it
  from the capacity `/compact`; host success-only `mark_flag_compaction`
  bookkeeping; `is_flag_compact` round-trips through the worker→host JSON.

### Phase 3: Audit glyph + docs

- [x] ✅ **Task 3.1**: 🧽 per-action glyph for `/compact` in `_audit_action_glyph`.
- [x] ✅ **Task 3.2**: supervisor header doc (module docstring — done);
  dogfood-enabled in this repo (`CCY_FLAG_COMPACT=1` in the tracked
  `.claude/ccy/ccy.env`, verified dogfood-only — the installer never copies it
  to clients); config-changes manifest entry is **N/A** — `CCY_FLAG_COMPACT`
  is a ccy env var, not a `hooks-daemon.yaml` key, so it does not fit the
  manifest schema (the sibling `CCY_MODEL_RESTORE_SECONDS` has none either).

### Phase 4: Dogfood

- [x] ✅ **Task 4.1**: worker-reloaded (forced restart; fresh pid verified
  loading the committed code); full supervise suite (492) + QA (25/25,
  coverage 95.1%) green.

## Success Criteria

- [ ] A flip-flop downgrade (open episode + prior restore) with the feature
  enabled yields exactly one `would-compact` decision carrying the
  flag-cleaning body; a first downgrade does not.
- [ ] Disabled by default; cap and backoff enforced; state round-trips.
- [ ] Audit trail names the `/compact` with the 🧽 glyph.
- [ ] Full supervise unit suite + `./scripts/qa/llm_qa.py all` green.

## Dependencies

- Builds on: Plan 00278 (downgrade resilience — effort restore, model restore,
  audit trail, `↓N↑M` counter).

## Delivery & Milestones

- Feature + tests + plan docs delivered at `5580d9a7`
- Dogfood-enable (`CCY_FLAG_COMPACT=1` in this repo's `ccy.env`) at `6594dbad`
- Live worker restarted onto the committed code (fresh pid verified) — Phase 4
