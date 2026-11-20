# Plan 00606: Plan 00605 follow-up daemon fixes

**Status**: Complete (2026-11-15)
**Created**: 2026-11-15
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Delivering Plan 00605 (GitHub #203) surfaced three daemon defects, recorded in that plan's Follow-ups and journal.
Each waited for a branch while the parked-branch slot was full.

1. `work-queue done` caches the issue it has just finished as the next workable one. The issue-sdlc runbook runs
   `done` before it closes the issue, and `done` refreshes the workable-issues cache while the issue is still open.
   Before this plan only `issue_validity_cli` called `remove_workable`, so the stale entry stayed until someone runs
   `issue-validity --list-eligible`. Meanwhile R-STOP-IDLE-WITH-WORKABLE-ISSUE names a closed issue as workable.
2. Acceptance socket discovery depends on the runner's hostname. `tests/acceptance/conftest.py` `_discover_socket`
   checks only `CLAUDE_HOOKS_SOCKET_PATH` and a glob of `untracked/`. When the natural socket path would exceed 104
   bytes, the daemon falls back to a socket under `/tmp`, discovery misses it, and every acceptance test errors. Main
   CI run 43620790845 attempt 1 failed this way.
3. `branch_creation_guard` does not see a branch that `scripts/setup_worktree.sh` creates. The guard matches
   `checkout -b`, `switch -c`, `branch <name>`, `worktree add` and Agent worktree isolation in the Bash command text,
   but the script runs `git worktree add` itself. Plan 00605's branch was created this way while `branch-preflight`
   reported that creation was blocked.

## Goals

- `work-queue done` never leaves the issue it finished listed as workable.
- Acceptance socket discovery finds the daemon's socket wherever the daemon's own resolver puts it.
- Running `scripts/setup_worktree.sh` while branch creation is blocked is refused, in the same way as a direct
  `git worktree add`.

## Non-Goals

- No change to the branch pool caps or to how pools are counted.
- No change to the issue-sdlc runbook's step order. The fix belongs in the daemon, so the order stops mattering.

## Tasks

### Phase 1: TDD fixes

- [x] ✅ **Task 1.1**: A failing test finishes a queue entry for an issue that is still open and asserts the cache does
  not list it. Then fix `work-queue done` to exclude the queue entry's issue number. The number is parsed by
  `issue_number_in_name` in `branch_inventory.py`, built on the existing `_ISSUE_IN_NAME` pattern. The issue is
  removed even when the GitHub lookup fails.
- [x] ✅ **Task 1.2**: A failing test puts the daemon's socket at the `/tmp` fallback path and asserts `_discover_socket`
  finds it. Then make discovery also try the daemon's own socket resolver, `get_socket_path(REPO_ROOT)`.
- [x] ✅ **Task 1.3**: A failing test runs a `scripts/setup_worktree.sh` invocation through `branch_creation_guard` while
  creation is blocked, and asserts it is denied. Then teach the guard to recognise the script. Wrappers are removed
  with `peel_command_wrappers`, interpreter options are parsed, and `branch_touch_recorder` records the route. The
  review fixes are in `5b1ab6f22`.
- [x] ✅ **Task 1.4**: Add a release note under `CLAUDE/UPGRADES/UNRELEASED/release-notes/` for the user-visible fixes (1.1
  and 1.3).

## Success Criteria

- [x] Each new test fails before its fix and passes after it: 14 review-fix tests and the first commit's tests,
  recorded in `subagent-reports/261115-python-developer-sonnet.md`.
- [x] Targeted QA passes on the branch: 40/43 at `5b1ab6f22`. The one failure was `ssh_agent.py`, which this plan does
  not touch, and main had already fixed it in `98bfe657e`. After main was merged in, `error_hiding` passes. Over the
  merged range on main (`1cabe4394..0fb70b7c6`) the result is `QA: 43/43 PASSED`. Main CI run 43752399610 is green.
- [x] The pending-release holding area carries
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/077-work-queue-done-and-setup-worktree-guard.md`.

## Delivery & Milestones

- Implementation `d696d45cc`, review fixes `5b1ab6f22`. Merge `0fb70b7c6`, fast-forwarded to main.
- Reports: `subagent-reports/261115-python-developer-sonnet.md` and `subagent-reports/261115-code-reviewer-opus.md`.
