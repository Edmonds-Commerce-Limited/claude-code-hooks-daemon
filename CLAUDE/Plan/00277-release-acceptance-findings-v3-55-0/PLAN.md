# Plan 00277: release acceptance findings v3 55 0

**Status**: Not Started
**Created**: 2026-08-26
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The v3.55.0 release gates surfaced findings that were deliberately NOT fixed
mid-release because none affects shipped handler behaviour: stale acceptance
test expectations, a documented-vs-implemented semantics mismatch in
`lsp_enforcement`, and one inconclusive acceptance test. Per RELEASING.md
("never drop a finding"), each is tracked here as a MUST-FIX to close
immediately after the release ships.

## Goals

- Every v3.55.0 acceptance/review finding below fixed or explicitly ruled on.

## Non-Goals

- No behaviour changes to handlers beyond what the rulings require.

## Tasks

### Phase 1: Stale acceptance expectations (test metadata only)

- [ ] ⬜ **Task 1.1**: `daemon_location_guard` playbook Test 19 expects
  pattern `CORRECT USAGE`, absent from the actual deny message. Align the
  `get_acceptance_tests()` expectation with the shipped message (or restore
  the wording if it regressed — check git history first).
- [ ] ⬜ **Task 1.2**: `recovery_cron_advisor` playbook Test 158 expects
  `[Rr]ecreat`, but the shipped advisory says "create one now". Align the
  expectation.
- [ ] ⬜ **Task 1.3**: `error_hiding_blocker` allow-case sample snippets
  (playbook Tests 30/34) use undefined names, so `lint_on_edit` denies the
  write after the tested handler allows it. Make the samples lint-clean.

### Phase 2: lsp_enforcement block_once semantics

- [ ] ⬜ **Task 2.1**: Documentation says `block_once` denies "the first
  symbol-lookup grep in a session"; implementation gates on
  `history.count_blocks_by_handler` — persistent, daemon-wide verdict
  history, so after any one block, every later session gets ALLOW+advisory
  (observed live: playbook Test 198). Rule which is intended, then fix the
  other: either key the count by session_id, or rewrite the guidance and the
  acceptance test to block-once-per-verdict-history.

### Phase 3: Inconclusive acceptance observations

- [ ] ⬜ **Task 3.1**: `agent_isolation_advisor` (playbook Test 214)
  produced no advisory on a non-isolated Agent spawn with many live peers,
  from a sub-agent AND from the main thread late in a long session.
  Determine whether per-session rate limiting explains it (probe from a
  fresh session) or the advisory genuinely fails to fire; fix if the latter.
- [ ] ⬜ **Task 3.2**: `command_hints` did not fire for `agent-browser` as
  the second segment of a compound command (`pkill ...; agent-browser --version`) though the docs say path-qualified/env-prefixed spellings in
  any shell segment are recognised. Confirm intended scope; fix handler or
  docs.

## Success Criteria

- [ ] All rulings recorded (here or in the affected handlers' docs)
- [ ] Regenerated playbook expectations pass against the live daemon
- [ ] Full QA green; daemon restart RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00277-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed during the v3.55.0 release acceptance gate
