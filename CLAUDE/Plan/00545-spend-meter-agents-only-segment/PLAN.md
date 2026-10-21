# Plan 00545: spend meter agents only segment

**Status**: In Progress
**Created**: 2026-10-21
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #133

## Overview

The spend-meter status-line segment (`handlers/status_line/spend_meter.py`) reads, for example,
`Σ⚙ 89.7M tok-eq · 1 live (1 sonnet) · max 127k · 54 unmeasured`.

- It is the longest segment on the line, and it is all dim grey internal jargon.
- The cumulative total only ever grows and has no reference point.
- `unmeasured` counts (agent, reason) pairs the context-budget gate could not measure. In the owner's session, 50 of
  54 were `no-usage-in-tail`, which points at agent start-up rather than a fault.

The decision is recorded on #133: the owner delegated it ("apply pragmatism"), and the coordinator chose option 1,
agents only.

## Goals

- The segment shows only while sub-agents are running, as `⚙ <n> agent(s) (<families>) · <largest context>`, for
  example `⚙ 1 agent (sonnet) · 127k`. With none running it renders nothing.
- The cumulative total leaves the bar; `hooks-daemon spend` keeps the ledger.
- A transcript holding no assistant usage yet is a start-up state, not `unmeasured`. Real measurement failures
  (usage-less tail in a transcript that has usage, missing/unreadable transcript, handler error) show in red only when
  non-zero.

## Non-Goals

- Other status-line segments (`⚡`, `📈`); the owner ruled them out of scope.
- Changing the ledger or `hooks-daemon spend`.

## Tasks

### Phase 1: Build (TDD)

- [x] ✅ **Task 1.1**: Establish what is already done. Commit `bf01783be` (N516, N517: "a first-call transcript is a
  fresh agent") and release note 002 may already cover part of the miscount; read them and record what remains.
- [x] ✅ **Task 1.2**: Agents-only rendering, with red real-failure count only when non-zero. Tests first.
- [x] ✅ **Task 1.3**: Start-up transcripts are not counted as unmeasured, if not already done. Tests first.
- [x] ✅ **Task 1.4**: Update `status-line-explained`, `CLAUDE/Architecture/StatusLine.md`, and a release note.

### Phase 2: Ship

- [ ] ⬜ **Task 2.1**: Targeted QA, merge, CI green, close #133.

## Success Criteria

- [ ] With no agents running, the segment renders nothing; with agents running it renders the agents-only form (tested).
- [ ] A start-up transcript is never counted as unmeasured; real failures render red only when non-zero (tested).
- [ ] A release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (the pending-release holding area).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/ — see CLAUDE/PlanJournalling.md. -->

- Not yet delivered.
