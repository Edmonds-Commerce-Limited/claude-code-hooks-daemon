# Plan 00551: supervisor own session ids from child tree

**Status**: In Progress
**Created**: 2026-10-23
**Owner**: dev
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #138

## Overview

The ccy supervisor decides which sessions are its own with `resolve_own_session_ids`
(`.claude/ccy/claude-supervise.py`). That function reads every numeric `/proc` entry and adopts every
`CLAUDE_CODE_SESSION_ID` it finds. Plan 00166 chose this "namespace-broad" identity on the assumption that the
supervisor runs in a private container PID namespace, so no foreign session is visible. On a host, or with a shared
PID namespace, `/proc` shows every other Claude Code session the user can read, rootless containers' sessions
included. Sessions in the same checkout share one context-sidecar directory. A supervisor there would act on another
session's sidecars and signals, and type `/compact` or `continue` into its own PTY for them. That is the
cross-injection class Plan 00166 fixed for containers.

Fix: an own session id comes only from the supervisor's own child process tree (the pid it spawns and that pid's
descendants by ppid). That is correct in a container and on a host alike. The fail-safe stays: an empty set means act
on nothing.

## Goals

- `resolve_own_session_ids` returns only ids found in the environ of the supervisor's child or its descendants.
- The union-only cache and the scan throttle (Plan 00182) keep working, and they never admit an id from outside the
  tree.
- The Plan 00166 comment block describes the new identity rule and drops the shared-namespace caveat.

## Non-Goals

- Changing how sidecars or signals are written by the daemon.
- Running the supervisor on hosts by default; this removes a blocker, it does not change deployment.

## Tasks

### Phase 1: Fix (TDD)

- [ ] ⬜ **Task 1.1**: RED tests with a fake `/proc` tree: an id in an unrelated process is NOT own; an id in the child
  or in a grandchild IS own; a process that re-parented away (ppid not in the tree) is not own; an empty tree fails
  safe. Include the issue's two-environ reproduction.
- [ ] ⬜ **Task 1.2**: GREEN: walk descendants of the child pid by `/proc/<pid>/stat` ppid; thread the child pid from
  where the supervisor spawns Claude to every caller (no global lookup, no silent fallback to the broad scan).
- [ ] ⬜ **Task 1.3**: Update the Plan 00166 comment block and `CLAUDE/development/CcySupervisor.md` where it states the
  identity rule.

### Phase 2: Land

- [ ] ⬜ **Task 2.1**: Targeted QA, merge, verify the live supervisor's worker hot-reloads the change
  (`.claude/rules/ccy-supervisor-dogfooding.md`), comment and close #138.

## Success Criteria

- [ ] The issue's reproduction returns only the child tree's id.
- [ ] A supervisor in this container still resolves its own session (verified after the hot reload).
- [ ] Release-bound consequences: a release note in the pending-release holding area stating the supervisor is now
  safe outside a private PID namespace.

## Delivery & Milestones

- Plan filed from issue #138 triage (actionable defect).
