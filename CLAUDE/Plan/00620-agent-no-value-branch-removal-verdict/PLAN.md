# Plan 00620: agent no value branch removal verdict

**Status**: In Progress
**Created**: 2026-11-18
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A branch whose work the delete proof cannot clear is never deleted today, and an agent has no way to remove one. Sending every such removal to a human makes every cleanup a human decision again, and the owner wants agents to work autonomously. The owner's proposal: require a sub-agent of at least Opus to confirm the work has no value, and let that verdict unlock the delete.

This is a loosening of a delete guard, so it is its own plan and runs under the security rules: Opus for the work, red tests first, an independent loosening review, and an adversarial pass that tries to forge or reuse a verdict. Archive refs and tags were rejected by the owner (they sprawl and hide valuable work), so the record is a single tracked ledger line, not a ref.

The open questions Q1 to Q8 of [FEASIBILITY.md](FEASIBILITY.md) are answered in [RULINGS.md](RULINGS.md), settled by a fable sub-agent under the owner's delegation, 2026-11-19. They are not the owner's own words, and a later owner message overturns them. The ruling that shapes everything else: a verdict is an agent's assertion and never unlocks a delete by itself. The delete also needs a fact the guard recomputes, namely that the branch's unproven work sits in a verified recovery bundle.

## Goals

- A verdict is written by a separate sub-agent of at least Opus, never by the agent that created or touched the branch, never by a fork or a resumed agent, and never by the guard's caller asserting it.
- The verdict is bound to the exact tip commit, expires, and lists what the branch held with a reason for each part judged worthless.
- Doubt means keep: tests, plan files, docs, config, and work described in any plan or journal are kept unless the reviewer clearly shows them superseded.
- The delete proceeds only when the guard finds a valid, fresh, tip-matching verdict and has itself written and verified a recovery bundle holding the branch's work. The restore lines still print.
- Every removal is recorded as a tracked ledger line and listed in a digest for the owner; nothing disappears silently.
- Repeated no-value verdicts over many branches trigger a stronger review.

## Non-Goals

- No archive refs and no tags. (A recovery bundle file is admitted by RULINGS.md section 1; it is not a ref.)
- No agent self-assertion path, no caller-typed reason and no override flag.
- No change to the merge proof, which stays the normal route for work with value.
- No remote delete. R-GIT-PUSH-DELETE-REMOTE is unchanged (RULINGS.md Q7).
- No command that deletes a recovery bundle.

## Tasks

### Phase 1: Feasibility and rulings

- [x] ✅ **Task 1.1**: Establish what a hook can prove about a sub-agent (its model and its independence from the session that owns the branch) from the payloads the daemon already receives. Findings: [FEASIBILITY.md](FEASIBILITY.md) (it cannot be proven against a same-user agent).
- [x] ✅ **Task 1.2**: Answer Q1 to Q8 and fix the shape of the mechanism: [RULINGS.md](RULINGS.md), settled by a fable sub-agent under the owner's delegation, 2026-11-19.

### Phase 2: Build (each slice is defined in RULINGS.md section 5)

- [x] ✅ **Task 2.1**: Slice 1, no change to delete behaviour. The live dispatch probe (journalled, passed); [DESIGN.md](DESIGN.md) with the verdict record, ledger line, review prompt and state layout; a pure module for inventory, verdict validation, bundle write and verify, ledger append and rate count, tests first; failing tests for forged, reused, stale, wrong-tip and self-written verdicts and for a verdict with no verified bundle, committed red.
- [x] ✅ **Task 2.2**: Slice 2. The reviewer agent definition, the `branch-reject request` command, the dispatch gate and the SubagentStop record, and the `delete-branch` wiring under the `rejected-bundled` tier. The red tests of Task 2.1 turn green.
- [x] ✅ **Task 2.3**: Slice 3. The `branch-reject digest` command and the session-start count of undigested removals.
- [ ] ⬜ **Task 2.4**: Slice 4. Builder's share is done and ticked below; the independent loosening review, CI green and the merge are NOT done and stay unticked (a builder may not do them).
  - [x] ✅ Adversarial forge tests (`tests/unit/core/test_branch_reject_forge.py`) and the verdict-reuse fixes.
  - [x] ✅ Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/014-agent-no-value-branch-removal-verdict.md`.
  - [x] ✅ Known gaps recorded (section below).
  - [ ] ⬜ Independent loosening review.
  - [ ] ⬜ CI green.
  - [ ] ⬜ Merge.

### Phase 3: Follow-up

- [ ] ⬜ **Task 3.1**: After the merge, file a follow-up plan to point `recovery_copy_advisory` at the reject route instead of `refs/archive/` (RULINGS.md Q6). Plan 00619 is not reopened.

## Known gaps

- A forger who also writes a NEW agent id into a copied dispatch and verdict is not caught. Accepted under RULINGS Q1 (the recovery bundle bounds the harm); DESIGN section 5 item 09.

- **Resolved (RULINGS Q8): single use and the rate are shared.** Each used verdict and reviewer agent gets a marker in the main checkout's `state_dir`, created exclusively when the ledger line is written. A git-refused removal gets a cancel marker. The used-verdict check, the 2-reviewer step and the refuse-after cap read the per-checkout tracked ledger together with these markers, and fail closed on damage. The ledger remains the human-readable record. `TestSingleUseAcrossCheckouts` in the forge tests pins three refusals: reuse from a second worktree, reuse after switching to an older commit, and the cap counting removals made in other worktrees.

- Slug collision: `a/b` and `a-b` at one tip share a bundle path; the second removal is refused (fails closed), so `a-b` cannot use the route while that bundle exists.

- A killed reviewer keeps its verdict, an unreadable second-stop transcript cannot withdraw a verdict, and an agent can mark digest entries read (this hides them only). Not yet pinned by tests.

## Success Criteria

- [ ] No delete of unproven work succeeds without a valid verdict and a recovery bundle the guard verified at delete time. Tests show the verdict cannot be reused (in any checkout or worktree), self-written, or forged by any route except the accepted RULINGS Q1 gap above, which the bundle bounds.
- [ ] A verdict alone, and a bundle alone, are each shown by a test to unlock nothing.
- [ ] Every removal appears in the ledger and the digest.
- [ ] A release note records the change in the pending-release holding area (CLAUDE/UPGRADES/UNRELEASED/release-notes/).

## Delivery & Milestones

- Plan filed from the owner's proposal; feasibility established; open questions ruled under delegation. The points left for the owner's glance are in RULINGS.md section 4.
- Slice 1 built: `core/branch_reject.py` with its tests green, `branches.reject` config, and the delete-path tests committed red for slice 2 (`tests/unit/core/test_branch_reject_delete.py`). Delete behaviour unchanged.
- Slice 2 built: `delete_branches(reject_route=...)` wired and the red tests green (DESIGN.md section 10); `delete-branch` builds the route from `branches.reject`; `branch-reject request` admits a review and prints the daemon-composed prompt(s); the `hooks-daemon-branch-reject-reviewer` agent ships; `branch_reject_dispatch_gate` (PreToolUse 59), `branch_reject_agent_binder` (PostToolUse 33) and `branch_reject_verdict_recorder` (SubagentStop 13) are registered. Targeted QA is still owed before the Task 2.4 merge ([handoff](subagent-reports/261120-task-2.2-handoff.md)).
- Slice 3 built: `branch-reject digest [--mark-read] [--format text|json]` and the read-only, fail-open session-start count in `branch_sweep` (DESIGN.md section 11).
