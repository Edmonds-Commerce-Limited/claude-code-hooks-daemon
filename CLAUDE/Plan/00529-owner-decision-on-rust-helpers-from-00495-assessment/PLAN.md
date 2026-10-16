# Plan 00529: owner decision on rust helpers from 00495 assessment

**Status**: Not Started
**Created**: 2026-10-16
**Owner**: dev
**Priority**: Medium
**Themes**: performance
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00495 Task 3.2 asked whether particular heavy paths justify a Rust helper (owner ruling A3). It answered from the
measured numbers in [RUST-HELPERS-ASSESSMENT.md](../00495-performance-improvement-programme/RUST-HELPERS-ASSESSMENT.md):
no path passes the cost test, one path is heavy for a Python reason, and the one helper that was justified (the transport
relay) already exists, opt-in. The choice is the owner's, so this plan holds it until they make it, and carries the work
that follows whichever way they decide.

The path that is over the performance budget is the secret-file guard's scan of Write and Edit content: about 9 ms per KB,
so a 115 KB Write spends 1.2 s in that one handler, and a 1.15 MB Write 9.3 s. The assessment recommends a Python fix, not
a helper. That fix is a Python change tracked as ledger N465 and fixed separately, so it is not in this plan.

## Goals

- The owner decides, from the assessment, on its two recommendations that are theirs: no new native helper, and the relay
  staying opt-in.

## Non-Goals

- A full Rust rewrite of the daemon or its handlers.
- Compiling any policy (Plan 00154 Rule 1).
- Making the transport relay default-on unless the owner decides so in Task 1.

## Tasks

### Phase 1: Decide

- [ ] ⬜ **Task 1**: The owner decides from the assessment. Put to them, with the assessment's recommendation first:
  (a) commission no new native helper; (b) leave the relay opt-in, or make it default-on. Record each answer here. (The
  secret-file guard's cost is a Python fix, ledger N465, fixed separately; it is not put to the owner.)

### Phase 2: Act on the decision

- [ ] ⬜ **Task 2**: If the owner chose a different answer in Task 1 (a helper, or the relay default-on), file the plan for
  it with the assessment as its evidence.

## Success Criteria

- [ ] The owner's decision on (a) and (b) is recorded in this plan.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00529-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed by Plan 00495 Task 3.2.
