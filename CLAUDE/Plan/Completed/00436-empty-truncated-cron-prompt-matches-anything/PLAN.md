# Plan 00436: empty truncated cron prompt matches anything

**Status**: Complete
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

From ledger [00422](../00422-niggles-ledger-fifteen/NIGGLES.md) N5 row (g), one
of the three rows in that table the reviewers flagged as having teeth — and the
only one that fails in the ALLOW direction.

`cron_is_asserted` decides whether a project's declared `persistent_crons` job
is actually live in the session, by comparing the declared prompt with the one
`session_crons` delivers. The delivered prompt is capped and marked, so an
over-cap declaration can only ever be compared by PREFIX, and the module is
careful about that: prefix matching applies only when the delivery was really
truncated, because "accepting every prefix would make a one-line cron match a
ten-line declaration".

The empty prefix is the case that rule does not cover. A delivered prompt of
nothing but a marker — `… [+1200 chars]` — strips to an empty string, is
correctly identified as truncated, and then every declaration on the same
schedule starts with it. Any declared job matches, so the handler reports
coverage that does not exist. That is the expensive direction: a missing cron
reported as present is a session with no recovery net and nothing saying so,
whereas the reverse merely nags.

## Goals

- An empty (or whitespace-only) delivered prefix never asserts a non-empty
  declaration, on any schedule.
- The existing truncation behaviour is unchanged: an over-cap declaration still
  matches its real truncated delivery, and a genuinely different prompt still
  does not match.

## Non-Goals

- **A minimum prefix LENGTH.** Requiring, say, 16 characters would be a policy
  invented here rather than derived from the contract, and the delivery cap
  gives no basis for a floor above zero. The empty prefix is the case that
  carries literally no evidence; a one-character prefix that survived the cap is
  a different argument, and this plan records it rather than guessing at it.
- **Changing what is compared.** Schedule stays an exact match, prompt stays
  word-normalised, `id` is still never used.

## Tasks

### Phase 1

- [x] ✅ **Task 1.1**: RED — a test that a `session_crons` entry whose prompt is
  only a truncation marker does not assert a declared job on the same schedule,
  plus the whitespace-around-the-marker variant.

- [x] ✅ **Task 1.2**: GREEN — prefix matching requires a non-empty normalised
  prefix. The reason goes in the code, because the next reader has to
  understand why an empty prefix is a different case from a short one.

- [x] ✅ **Task 1.3**: Confirm the existing truncation tests still pass
  unchanged — the fix must not narrow the case the module was built for.

## Success Criteria

- [x] ✅ The new tests observed RED before the fix and GREEN after.
- [x] ✅ `llm_qa.py all` passes — 35/35.
- [x] ✅ A release note lands in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`:
  any client declaring `persistent_crons` is affected.
- [x] ✅ N5 row (g) is marked done in ledger 00422, with the residual (a
  one-character surviving prefix) recorded rather than implied.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00436-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
