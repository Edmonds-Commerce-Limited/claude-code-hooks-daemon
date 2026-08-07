# Plan 00197: Journal Day-File Today-Only Guard

**Status**: Complete
**Created**: 2026-08-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Cheap, automatable journal hygiene: a Write/Edit targeting a plan
`JOURNAL/NNNNN-Journal-YY-MM-DD.md` day-file whose embedded date is not
**today** must be BLOCKED. Agents sometimes get confused about which day-file
they should be appending to (especially across a session that spans a
midnight rollover) and log activity against the wrong day. The existing
`journal-dayfile-naming` check (Plan 00163) already validates grammar and
plan-number coherence, but deliberately tolerates yesterday's date as a
"legitimate midnight rollover" exception — that tolerance is exactly the
confusion this plan closes. The correct behaviour on a rollover is to START a
new today-dated day-file, not keep appending to yesterday's.

This plan adds a new, single-purpose check — `journal-dayfile-is-today` — that
owns write-time freshness (today vs. not-today) at `Stage.EDIT`, defaulting to
BLOCK. The existing `journal-dayfile-naming` check is narrowed to grammar +
plan-number + calendar-validity only, since recency is now the new check's
exclusive concern (avoids two checks giving contradictory advice about the
same fact).

## Goals

- Block any Write/Edit whose target is a journal day-file dated anything other
  than today (past, including yesterday, and future), with a remediation that
  names the exact today-dated filename to use instead.
- Allow creation of a correctly-named today's day-file without friction.
- New config knob `plan_workflow.qa.journal.today_only_mode` (block | advise |
  off), default `block`, independent of the existing `journal.mode` field.
- Preserve legacy-plan-allowlist grandfathering (advise-only) and fail-open
  behaviour when `today` is unknown (e.g. the `plan-qa --lint` CLI path).
- Resident `get_claude_md()` guidance on `plan_qa_edit` documents the new
  rule so agents are told about a rule that can block them.

## Non-Goals

- No change to COMMIT-stage or SWEEP-stage journal checks.
- No change to `journal-append-only` (append-vs-rewrite is a separate
  concern from which day-file is targeted).
- No new escape-hatch marker — grandfathering already covers "this project
  genuinely can't comply yet"; write-time freshness has no legitimate
  per-file exception the way plan-doc-size does.

## Tasks

### Phase 1: TDD

- [x] ✅ **Task 1.1**: Write failing tests for `journal-dayfile-is-today`
  (today/yesterday/future/past/creation/non-journal/malformed-defer/
  today-None/legacy-allowlist/off-mode/block-mode/advise-mode).
- [x] ✅ **Task 1.2**: Implement the check, config field, and context
  threading until tests pass.
- [x] ✅ **Task 1.3**: Narrow `journal-dayfile-naming` to drop the
  today-or-yesterday recency sub-check; update its docstring/tests
  accordingly (no more "only check that may ratchet to BLOCK" claim).

### Phase 2: Integration

- [x] ✅ **Task 2.1**: Update `plan_qa_edit.get_claude_md()` with the new
  rule and the exact block message shape.
- [x] ✅ **Task 2.2**: Add `CLAUDE/UPGRADES/UNRELEASED/config-changes/` entry
  for `plan_workflow.qa.journal.today_only_mode`.
- [x] ✅ **Task 2.3**: Run `./scripts/qa/llm_qa.py all` — zero failures.
- [x] ✅ **Task 2.4**: Restart the daemon, verify `RUNNING`.
- [x] ✅ **Task 2.5**: Live-dogfood: Edit a stale-dated day-file (denied) and
  a today-dated one (allowed) against the live daemon.

## Success Criteria

- [x] New check ships with tests covering every edge case above.
- [x] `journal-dayfile-naming` no longer double-reports recency.
- [x] QA suite passes with zero suppressions.
- [x] Daemon restarts and reports RUNNING with the new code.
- [x] Live dogfood confirms both the block and the allow paths.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00197-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Implementation delivered at `e5ce3692` (`journal-dayfile-is-today` check,
  narrowed `journal-dayfile-naming`, `plan_qa_edit` guidance, config-changes
  manifest, docs). Daemon restarted and live-dogfooded successfully
  post-delivery (see JOURNAL for the block/allow probe transcript).
