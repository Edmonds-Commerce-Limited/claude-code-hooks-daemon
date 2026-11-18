# Plan 00620: agent no value branch removal verdict

**Status**: Not Started
**Created**: 2026-11-18
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A branch whose work the delete proof cannot clear is never deleted today, and an agent has no way to remove one. Sending every such removal to a human makes every cleanup a human decision again, and the owner wants agents to work autonomously. The owner's proposal: require a sub-agent of at least Opus to confirm the work has no value, and let that verdict unlock the delete.

This is a loosening of a delete guard, so it is its own plan and runs under the security rules: Opus for the work, red tests first, an independent loosening review, and an adversarial pass that tries to forge or reuse a verdict. Archive refs and tags were rejected by the owner (they sprawl and hide valuable work), so the record is a single tracked ledger line, not a ref.

## Goals

- A verdict is written by a separate sub-agent of at least Opus, never by the session that owns the branch, and never by the guard's caller asserting it.
- The verdict is bound to the exact tip commit, expires, and lists what the branch held with a reason for each part judged worthless.
- Doubt means keep: tests, plan files, docs, config, and work described in any plan or journal are kept unless the reviewer clearly shows them superseded.
- The delete proceeds only when the guard finds a valid, fresh, tip-matching verdict. The restore line still prints.
- Every removal is recorded as a tracked ledger line and listed in a digest for the owner; nothing disappears silently.
- Repeated no-value verdicts over many branches trigger a stronger review.

## Non-Goals

- No archive refs, tags or bundles.
- No agent self-assertion path and no override flag.
- No change to the merge proof, which stays the normal route for work with value.

## Tasks

### Phase 1: Feasibility

- [ ] ⬜ **Task 1.1**: Establish what a hook can prove about a sub-agent (its model and its independence from the session that owns the branch) from the payloads the daemon already receives. If it cannot be proven, report that to the owner before designing further. Findings: [FEASIBILITY.md](FEASIBILITY.md) (it cannot be proven against a same-user agent; draft design and owner questions Q1-Q8 inside).
- [ ] ⬜ **Task 1.2**: Design the verdict record (ledger line, tip binding, expiry, reasons) and the review prompt, and write them into a DESIGN.md for the owner to approve.

### Phase 2: Build (after the owner approves the design)

- [ ] ⬜ **Task 2.1**: Failing tests for forged, reused, stale, wrong-tip and self-written verdicts, committed red.
- [ ] ⬜ **Task 2.2**: Implement the verdict check and the ledger, and wire the delete path.
- [ ] ⬜ **Task 2.3**: The daily digest of removals.
- [ ] ⬜ **Task 2.4**: Independent loosening review, adversarial forge attempt, targeted QA, CI green, merge, release note.

## Success Criteria

- [ ] No delete of unproven work succeeds without a valid verdict that a test shows cannot be forged, reused, or self-written.
- [ ] Every removal appears in the ledger and the digest.
- [ ] A release note records the change in the pending-release holding area (CLAUDE/UPGRADES/UNRELEASED/release-notes/).

## Delivery & Milestones

- Plan filed from the owner's proposal; no code yet.
