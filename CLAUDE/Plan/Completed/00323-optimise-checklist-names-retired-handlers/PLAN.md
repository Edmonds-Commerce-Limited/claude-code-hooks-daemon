# Plan 00323: optimise checklist names retired handlers

**Status**: Complete
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

Found by actually RUNNING the config-optimisation step on this repo (the
first thing Plan 00322 asked for). Its five-area checklist scores a project
out of 29 items, and four of those items are handlers Plan 00237 DELETED:
`bash_error_detector`, `yolo_container_detection`, `validate_plan_number`
and `plan_completion_advisor`. They are in `RETIRED_HANDLERS`, absent from
the registry, and nothing can enable them.

Two consequences, both bad in a client project. A fully-optimised
installation scores 25/29 (86%) and can never reach 100%, so the number the
report leads with is wrong and stays wrong. And the step generates four
recommendations to "enable" handlers that do not exist — advice that, if
followed, adds dead keys to the project's config. The one thing the review
must be is trustworthy; a permanent phantom deficit is exactly what teaches
a reader to skim past it.

The instruction body is a shell heredoc, so nothing type-checks these names
against the registry. A cheap contract test closes that: no name the script
mentions may appear in `RETIRED_HANDLERS`, and every `handlers.<event>.<name>`
reference must resolve to a live `HandlerID` config key.

## Goals

- The checklist scores only handlers that exist, with denominators and the
  overall total adjusted to match.
- A future retirement that leaves a stale name in the script fails CI rather
  than shipping a phantom recommendation to every client.

## Non-Goals

- Re-deciding which handlers the five areas SHOULD cover (the areas gained
  no new members here — this removes dead ones only).
- Reviving any retired handler.

## Tasks

### Phase 1: Lock the contract

- [x] ✅ **Task 1.1**: Contract test under `tests/unit/scripts/`: no
  `RETIRED_HANDLERS` key appears in `optimise-invoke.sh`, and every
  `handlers.<event>.<name>` reference in it resolves to a live `HandlerID`
  config key. RED first.

### Phase 2: Fix the checklist

- [x] ✅ **Task 2.1**: Remove the four retired names from Areas 3, 4 and 5,
  fix each area's denominator and the 29-item total, and update the report
  template rows.

### Phase 3: Ship

- [x] ✅ **Task 3.1**: QA, daemon restart + verification, CHANGELOG entry,
  commit and push.

## Success Criteria

- [x] A fully-configured project can score 100% on the config-optimisation
  report.
- [x] No recommendation names a handler that cannot be enabled.
- [x] The contract test fails if a retired name reappears.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00323-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Delivered in the archiving commit: checklist trimmed to 25 live items and two contract tests (`tests/unit/scripts/test_optimise_checklist_handlers.py`) that fail if a retired handler name returns.
