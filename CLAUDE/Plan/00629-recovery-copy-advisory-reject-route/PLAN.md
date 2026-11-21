# Plan 00629: recovery copy advisory reject route

**Status**: Not Started
**Created**: 2026-11-21
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Follow-up filed by Plan 00620 Task 3.1, as ruled in
[00620 RULINGS.md Q6](../Completed/00620-agent-no-value-branch-removal-verdict/RULINGS.md). Plan 00620
shipped the no-value removal route (`branch-reject request` then `delete-branch`, under the
`rejected-bundled` tier): a branch whose work no proof clears can be removed once an independent
Opus reviewer judges it worthless, and the guard itself writes and verifies a recovery bundle
before the delete. That bundle does the job `refs/archive/<name>` was advised for, without a ref.

`recovery_copy_advisory` (`src/claude_code_hooks_daemon/core/branch_practice.py`, surfaced by
`branch_creation_guard` on a recovery-shaped branch name) still tells agents to keep a recovery
copy as `git update-ref refs/archive/<name> <sha>`. The owner rejected archive refs because they
sprawl and hide valuable work (00620 Overview). This plan points the advice at the reject route
instead. Plan 00619 is complete and is not reopened.

This changes advice only. It must not loosen any guard: the advisory never blocks today, and the
`remote-held` tier and the remote archive proof stay as they are (RULINGS Q6).

## Goals

- `recovery_copy_advisory` no longer advises `refs/archive/<name>`. It tells the agent that a
  recovery-copy branch is not needed: work with value is merged or parked, and work judged
  worthless leaves through `branch-reject request` / `delete-branch`, whose bundle is the
  recovery copy.
- The branch-practice docs say the same, in the template and the deployed copy.

## Non-Goals

- No change to delete behaviour, the reject route, the `remote-held` tier or the remote archive
  proof (`utils/remote_refs.py`, `tests/unit/core/test_remote_archive_proof.py`), which still
  recognise existing `refs/archive/` refs on a remote.
- No change to `RECOVERY_COPY_PATTERNS` or to when the advisory fires.
- Plan 00619 is not reopened.

## Tasks

### Phase 1: Advice and docs

- [ ] ⬜ **Task 1.1**: Red tests first. Update `tests/unit/core/test_branch_practice.py` (the
  assertion that the advice names `refs/archive/`) and
  `tests/unit/handlers/pre_tool_use/test_branch_creation_guard.py` (lines asserting
  `refs/archive/rescue/plan-9` and the guidance text) to require the reject-route wording and
  the absence of `refs/archive/`.
- [ ] ⬜ **Task 1.2**: Change `recovery_copy_advisory`, the module docstring of
  `core/branch_practice.py`, the `constants/branch_guard.py` comment and the
  `branch_creation_guard` guidance string. Print the commands through the existing
  docs-command helper so the wrapper path is right in a client install.
- [ ] ⬜ **Task 1.3**: Update the "Branch Practice" section of
  `src/claude_code_hooks_daemon/install/templates/core/Worktree.core.md` and redeploy
  `CLAUDE/core/Worktree.core.md`; regenerate the handler guidance if it changes.
- [ ] ⬜ **Task 1.4**: Release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

### Phase 2: Close

- [ ] ⬜ **Task 2.1**: Targeted QA, independent review confirming no guard was loosened,
  merge.

## Success Criteria

- [ ] `recovery_copy_advisory` never names `refs/archive/`, and names the reject route
  (pinned by `tests/unit/core/test_branch_practice.py`).
- [ ] `branch_creation_guard` guidance and the deployed branch practice agree with it.
- [ ] No guard verdict changes (the branch creation guard, delete and remote archive proof
  tests pass unchanged apart from the advice text).
- [ ] A release note records the change in the pending-release holding area
  (CLAUDE/UPGRADES/UNRELEASED/release-notes/).

## Delivery & Milestones

- Plan filed by Plan 00620 Task 3.1 after 00620 merged to main (merge commit 69e375788).
