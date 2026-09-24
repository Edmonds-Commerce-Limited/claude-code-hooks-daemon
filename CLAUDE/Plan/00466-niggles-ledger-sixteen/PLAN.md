# Plan 00466: niggles ledger sixteen

**Status**: In Progress
**Created**: 2026-09-24
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The rolling ledger for defects found in passing. Ledger fifteen
([00422](../00422-niggles-ledger-fifteen/PLAN.md)) stays open for its own
entries: four are waiting on stated owner questions, and several are
graduated to plans still in flight. But its PLAN.md passed the 25,000-byte
warning line with N29. So new entries are filed here, and 00422 takes no
more.

Each entry gets enough evidence for someone else to reproduce it, and ends
in a terminal state: fixed, graduated to its own plan, or dismissed as
not-a-defect with the reasoning kept.

## Goals

- Record each niggle with reproducible evidence in [NIGGLES.md](NIGGLES.md).
- Resolve each entry to a terminal state.

## Non-Goals

- Becoming a feature plan. A niggle that needs design graduates to its own
  numbered plan and leaves a pointer here.

## Niggles

Full write-ups are in [NIGGLES.md](NIGGLES.md). One line each here:

| #   | Verdict                                                                                                   | Origin             | Status                |
| --- | --------------------------------------------------------------------------------------------------------- | ------------------ | --------------------- |
| N1  | `resolve_venv_python`'s fallback accepts a venv interpreter that cannot run on this host                  | Plan 00457's agent | ✅ Remedied           |
| N2  | `setup_worktree.sh` tells every agent to run the full suite through the denied `run_all.sh`               | Coordinator        | 🔄 Graduated to 00463 |
| N3  | `goal_injection` treats any edit of an In Progress plan as the plan starting, and displaces the live goal | Coordinator        | 🔄 In progress        |
| N7  | The regenerated CLAUDE.md guidance block is not deterministic, so a restart commits a reorder             | Coordinator        | 🔄 In progress        |
| N8  | `reference_repo_freshness` says BLOCKED on a call it allows                                               | Coordinator        | ✅ Remedied           |
| N9  | `docs_qa` judges gitignored markdown, so installing a Claude Code plugin fails local full QA              | Coordinator        | 🔄 In progress        |
| N10 | A wildcard in the middle of a protected filename gets past `secret_file_guard`                            | 00466 review       | 🔄 In progress        |
| N11 | Any exception in `secret_file_guard.matches()` lets the call through unless `strict_mode` is on           | 00466 review       | 🔄 In progress        |

## Tasks

### Phase 1: Resolve entries

- [ ] ⬜ **Task 1.1**: Bring every entry to a terminal state.

## Success Criteria

- [ ] Every row is terminal: remedied, graduated, or dismissed with reasoning.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00466-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Opened with N1.
