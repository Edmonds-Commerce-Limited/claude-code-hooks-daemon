# Plan 00619: branch pool graduated warnings

**Status**: Not Started
**Created**: 2026-11-18
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The branch pools (open work, parked, merged) hard-stop branch creation at their cap, with no exemption, including for owner-priority work. The owner's ruling: the cap stays a hard stop, so the guard must warn well before it is hit. Today pressure is reported at session start and at stop and only near or over the cap; there is no graduated signal.

This plan adds a warning ladder driven by the share of each pool's cap in use: a warn at 60 percent, a strong warn at 80 percent, and a very strong warn at 90 percent that is never rate-limited and never silenced until usage drops below 90 percent. The block at 100 percent is unchanged. A peer asked for four branch-guard changes; verification against main (`untracked/scratch/branch-guard-verify.md`) found three already fixed in 3.75.0 and one (the cap message) already naming the branch and command, so only this ladder is new work.

## Goals

- A pure function maps (count, cap) to a level (none, warn, strong, very strong, block), unit-tested over a table of caps and counts, rounding the thresholds up.
- Thresholds are configurable per pool, defaulting to 60, 80 and 90 percent.
- Each warning names the pool, its count against its cap, and the specific branch to finish or remove first with its exact command; the text is generic.
- At the very strong level the warning shows on every tool call and every prompt, bypassing any rate limit, until usage falls below the threshold.
- Session start and stop reports use the same ladder.
- No change to what the guards deny or allow.

## Non-Goals

- No exemption from the cap for any task, and no change to the 100 percent block.
- No re-adding `delete-branch --allow-unproven`, and no loosening of any delete guard.
- No archive-ref design for unproven work (a separate plan if wanted).

## Tasks

### Phase 1: Ladder

- [ ] ⬜ **Task 1.1**: Write the failing table test for the level function and the very-strong never-silenced behaviour, commit it red.
- [ ] ⬜ **Task 1.2**: Implement the level function and config keys (the thresholds per pool), reusing the existing pool inventory counts.
- [ ] ⬜ **Task 1.3**: Emit the warnings from the existing advisory surfaces (pre-tool-use, prompt submit, session start, stop) with the branch and command named.
- [ ] ⬜ **Task 1.4**: Independent review, targeted QA, CI green, merge, release note.

### Phase 2: Confirm the remaining peer claim

- [ ] ⬜ **Task 2.1**: Trace how the stop guard resolves its repository when a command runs in another clone, and add a test if it differs from the creation guard.

## Success Criteria

- [ ] The ladder test table passes and was committed red first.
- [ ] A session at 90 percent sees the warning on every call and prompt.
- [ ] No guard denies or allows anything it did not before (loosening and tightening review).
- [ ] A release note records the ladder in the pending-release holding area (CLAUDE/UPGRADES/UNRELEASED/release-notes/).

## Delivery & Milestones

- Plan filed after the owner's ruling and the verification report.
