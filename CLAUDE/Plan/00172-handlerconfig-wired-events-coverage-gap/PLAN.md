# Plan 00172: Close the HandlersConfig ↔ wired-events coverage gap

**Status**: Not Started
**Created**: 2026-07-17
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

While fixing the `status_line` config-drop bug (a hand-maintained event-type
list in `daemon/cli.py` omitted `status_line`, so every status-line handler's
`enabled` flag was silently discarded), a follow-up audit hunted for other
instances of the same bug class: **a hand-maintained enumeration of event
types / handlers / config keys that has drifted from a single source of truth
and is not guarded by a test that would catch the drift.**

The audit found that the `status_line` fix, while correct for the reported
symptom, rests on a partial SSoT: `HandlersConfig` declares only **11 of the
31 wired events**. The mapping builder now iterates the model's fields, so it
faithfully covers whatever the model declares — but the model itself is that
narrow list. This plan closes the gap so the guardrail covers all wired events
(or an explicit, test-enforced exclusion set), and hardens the drift tests so
they cross-check against `wired_event_metas()` rather than re-encoding the same
hand-maintained subset.

## Goals

- Make `HandlersConfig`'s event-type coverage track the wired-event catalogue
  (`wired_event_metas()`) as the single source of truth, or add an explicit,
  test-enforced statement of which wired events are intentionally
  non-configurable.
- Fix `PluginConfig.event_type` (the `Literal` of allowed plugin event types)
  to cover the same wired events, and make its test cross-check the catalogue
  instead of mirroring the hard-coded list.
- Ensure the `_build_handler_config_mapping` regression test structurally
  catches a wired event that gains handlers without a matching model field.

## Non-Goals

- No change to the delivered `status_line` fix itself (this plan builds on it).
- No implementation of handlers for the 20 currently-unhandled wired events —
  this is about config/plumbing coverage, not new event behaviour.

## Context & Background

Source of the findings: read-only audit agent dispatched 2026-07-17 after the
`status_line` fix. Confirmed-correct (SSoT-derived or test-locked, ruled out):
`registry.EVENT_TYPE_MAPPING`, `INPUT_SCHEMAS`, `RESPONSE_SCHEMAS`,
`HOOK_EVENTS_IN_SETTINGS`, `EventKey`, `ConfigValidator.VALID_EVENT_TYPES`,
`_EVENT_TYPE_CONFIG_KEYS`.

### Findings (audit output, ranked)

**Finding 1 — HIGH (structural, latent).**
`config/models.py:98-108` (`HandlersConfig` declares 11 event fields) consumed
by `daemon/cli.py` `_build_handler_config_mapping` (iterates
`type(config.handlers).model_fields`). The model declares only 11 of 31 wired
events, so config for the 20 Plan-00170 wired events would be silently dropped
by the mapping — the exact `status_line` failure mode, re-armed for any of
those events that later gains built-in handlers. Should track
`wired_event_metas()` / the `EventID` catalogue. Currently a subset only.
Guarded only partially: `tests/unit/daemon/test_cli_handler_config_mapping.py`
asserts events with an on-disk built-in handler directory, so it cannot catch a
wired event lacking both a dir and a model field. Latent today (no built-in
handlers consume the 20 events), but the recurrence guardrail covers only 11
of 31 events.

**Finding 2 — MEDIUM.**
`config/models.py:292-304` (`PluginConfig.event_type` `Literal`); test at
`tests/config/test_models.py:395`. The `Literal` omits the same 20 wired
events, so a plugin targeting one is rejected at validation. The test mirrors
the hard-coded list instead of cross-checking `wired_event_metas()`, so the two
drift together undetected. Fails loud (validation error) rather than silent,
but is a real feature restriction with an unguarded enumeration.

**Finding 3 — LOW.**
`config/schema.py:33-55` — a non-enforcing 3-event JSON-schema stub. Confirm
intent; either remove or make it derive from the catalogue.

**Finding 4 — LOW.**
The doc generator and playbook generator use intentional narrow event subsets.
Confirmed intentional; documented here so future audits rule them out. Likely
no action beyond a clarifying comment.

## Tasks

### Phase 1: Decide the model

- [ ] ⬜ **Task 1.1**: Decide whether all wired events should be configurable
  (`HandlersConfig` gains fields for all 31) or whether a subset is
  intentionally non-configurable — and encode that decision as data
  derived from `wired_event_metas()`, not a hand-maintained list.
- [ ] ⬜ **Task 1.2**: Make the same decision for `PluginConfig.event_type`.

### Phase 2: TDD implementation

- [ ] ⬜ **Task 2.1**: Failing test cross-checking `HandlersConfig` coverage
  against `wired_event_metas()` (allow an explicit, named exclusion set).
- [ ] ⬜ **Task 2.2**: Failing test cross-checking `PluginConfig.event_type`
  against `wired_event_metas()`; replace the mirrored list in
  `test_models.py`.
- [ ] ⬜ **Task 2.3**: Strengthen `test_cli_handler_config_mapping` so a wired
  event with handlers but no model field fails the test.
- [ ] ⬜ **Task 2.4**: Implement model/plumbing changes to pass the tests.

### Phase 3: Housekeeping (Findings 3-4)

- [ ] ⬜ **Task 3.1**: Resolve the `schema.py` 3-event stub (derive or remove).
- [ ] ⬜ **Task 3.2**: Comment the doc/playbook generator subsets as
  intentional so future audits rule them out.

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Run `./scripts/qa/run_all.sh` (all pass).
- [ ] ⬜ **Task 4.2**: Restart daemon, confirm RUNNING.

## Dependencies

- Builds on: the `status_line` config-drop fix (delivered first; see git
  history for `_build_handler_config_mapping`).
- Related: Plan 00170 (wired-events burn-down).

## Success Criteria

- [ ] `HandlersConfig` and `PluginConfig.event_type` coverage are derived from
  or test-locked against `wired_event_metas()`.
- [ ] A drift test fails if a wired event gains handlers without config
  coverage.
- [ ] All QA checks pass; daemon restarts RUNNING.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Blow-by-blow log lives in JOURNAL/. -->

- Not yet started. Recovery cron intentionally not created — short tracking
  task, not a long execution run.
