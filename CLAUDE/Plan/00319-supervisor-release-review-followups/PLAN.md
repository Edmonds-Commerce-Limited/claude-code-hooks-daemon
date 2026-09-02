# Plan 00319: supervisor release review followups

**Status**: Not Started
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The v3.60.0 release's Step 10 code-review gate returned 13 findings against
the supervisor and status-line work shipped by Plans 00316, 00317 and 00318.
Three were BLOCKING and were fixed before the release shipped (commit
`55dd5b2e`). The remaining ten are non-blocking: none of them makes the
release unsound, but RELEASING.md's "never drop a finding" rule requires every
surviving finding to be captured as a tracked MUST-FIX item rather than left
in a review transcript that nobody reads again. This plan is that tracked
capture.

The findings cluster into three themes. **Unbounded growth**: several
per-session artefacts (the worker error log, the `manual-model-changes/`
marker directory, a second `MtimeCachedFile` entry set) accumulate with no
reaper, which is the same shape of defect the project has already fixed
elsewhere. **Silent failure**: a marker write with no error guard, a decision
log line dropped on a branch collision, and a typed command lost across a
worker restart with no diagnostic trace — each is invisible when it happens,
which is exactly what makes it expensive to diagnose later. **Contract drift**:
a writer and a reader disagreeing on how a session id is stemmed, an audit
banner that bypasses the poster's own lock and rate limit, and mutable state
on a router-shared handler instance.

Each finding below is self-contained: it names the file, what is wrong, and
why it matters. They can be fixed independently and in any order, so this plan
is a good candidate for parallel sub-agent execution once someone has decided
which of them are worth the change.

## Goals

- Every one of the ten surviving v3.60.0 review findings is either fixed with
  a TDD regression test, or explicitly closed as won't-fix with the reason
  recorded in this plan.
- No finding is closed by assertion alone: a fix lands with a test that fails
  against the current code.
- The unbounded-growth findings (F4, F5, F7) are fixed or bounded, because
  they degrade a long-lived session rather than failing once.

## Non-Goals

- Re-opening the three BLOCKING findings already fixed in `55dd5b2e`
  (`_MANUAL_MARKER_WINDOW_SECONDS` drift, the `input_line_empty` override,
  and raw-vs-canonical `/model` argument comparison). Those shipped.
- Redesigning the supervisor's two-tier host/worker split. Plan 00317 settled
  that boundary; these are defects within it, not arguments against it.
- Any change to the status-line banner's user-visible design. Plan 00318's
  countdown banner is confirmed working live.

## Tasks

### Phase 1: Silent-failure findings

- [ ] ⬜ **Task 1.1 (F1)**: `write_manual_model_marker` is called in the tick
  path (`.claude/ccy/claude-supervise.py`) without an error guard — it is
  the only unguarded write there. Every other write in that path reports
  its outcome. A failure here silently loses the manual-model marker, and
  the symptom surfaces much later as a false "downgraded" status
  indicator. Give it the same observable write outcome the failsafe-cron
  marker got in Plan 00314.
- [ ] ⬜ **Task 1.2 (F3)**: the audit flush's `decision.log` line is dropped
  when the standing-authorisation branch injects on the same tick. The
  audit trail is the documented source of truth for what the supervisor
  did (see `CLAUDE/UPGRADES/truth-changes/v3.60.0.yaml`), so a tick that
  silently writes no line makes it an incomplete record.
- [ ] ⬜ **Task 1.3 (F8)**: a worker restart mid-line drops a typed
  `/compact` / `/model` with no diagnostic trace. The recognizer's buffer
  is reset by the reload, so a partially-typed command vanishes. Dropping
  it may be the right behaviour; doing so invisibly is not — emit a trace
  so the next person debugging "my /model did nothing" can see it.

### Phase 2: Unbounded-growth findings

- [ ] ⬜ **Task 2.1 (F4)**: `claude-supervise-worker.err.log` is uncapped and
  logs every submitted `/`-line verbatim. Two problems, one file: it grows
  without limit in a long session, and it records what the human typed.
  Cap it (rotate or truncate) and decide deliberately what belongs in it.
- [ ] ⬜ **Task 2.2 (F5)**: `manual-model-changes/` markers are never reaped.
  Each manual `/model` leaves a file behind and nothing removes it.
- [ ] ⬜ **Task 2.3 (F7)**: a second unbounded per-session `MtimeCachedFile`
  entry set was added without a bound. The project has already fixed this
  exact shape once; apply the same bound.

### Phase 3: Contract-drift findings

- [ ] ⬜ **Task 3.1 (F6)**: the marker writer uses the raw `session_id` while
  the daemon reads via `safe_session_stem()`. They agree today only
  because real session ids happen to be stem-safe. A session id that is
  not makes the marker unreadable — a silent miss, not an error. Use the
  same stemming on both sides.
- [ ] ⬜ **Task 3.2 (F9)**: the audit banner writes the status message
  directly, bypassing `StatusMessagePoster`'s lock and rate limit, so it
  can clobber a live Ctrl+C hint. Route it through the poster, or state in
  the code why the bypass is correct.
- [ ] ⬜ **Task 3.3 (F10)**: `_cached_fragment` is mutable state on a
  router-shared handler instance. Handlers are shared across events, so
  per-event state on the instance leaks between events.

### Phase 4: Non-blocking observations from the v3.60.0 acceptance run

- [ ] ⬜ **Task 4.1**: `bin/hooks-daemon secret-meta <path> | head -20` is
  DENIED by `pipe_blocker`, while the unpiped command passes. The
  `secret-meta` helper is the documented alternative offered by the
  secret-file guard's own deny message, so having it blocked when piped
  is a sharp edge in the recommended recovery path. Decide whether
  `secret-meta` belongs in `pipe_blocker`'s whitelist.

## Success Criteria

- [ ] All ten findings (F1, F3, F4, F5, F6, F7, F8, F9, F10 and the
  `secret-meta` observation) are closed — each either fixed with a
  regression test that fails against the pre-fix code, or marked won't-fix
  with a recorded reason.
- [ ] `./scripts/qa/llm_qa.py all` passes 25/25 after the changes.
- [ ] For any supervisor change: the worker hot-reload is verified by pid, per
  the contract in the global `CLAUDE.md` — a `ps` check showing a NEW
  `--worker` pid before any behaviour is tested.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00319-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Findings captured from the v3.60.0 Step 10 review gate; the three BLOCKING
  siblings shipped separately in `55dd5b2e`.
