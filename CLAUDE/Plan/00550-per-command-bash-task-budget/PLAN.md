# Plan 00550: per command bash task budget

**Status**: Not Started
**Created**: 2026-10-23
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #137

## Overview

One Bash tool call that forks without end (a PATH stand-in that calls itself) filled a rootless container's pids
limit in seconds. Claude Code then could not fork, and the session aborted. Nothing in Claude Code or the daemon
limits how many tasks one tool call may create. Container-wide limits make it worse: they turn one runaway command
into a dead session.

Issue #137 proposes a daemon-shipped wrapper installed as `CLAUDE_CODE_SHELL_PREFIX`. It would budget only Bash tool
invocations, recognised by the tool shell's cwd hand-back, and pass hooks, the status line and MCP start-up through
untouched. It picks a strategy per host, first that works: a `systemd-run --scope` with `TasksMax`/`MemoryMax`; a
fresh user namespace with `prlimit --nproc` (measured working in rootless Podman); a dedicated uid (opt-in); or a soft
`ulimit` with a loud warning. A SessionStart advisory and `health` name the active strategy, so a host with no
guard is never silent.

**BLOCKED ON THE OWNER (issue-sdlc triage: needs human decision).** The prefix wraps every Bash call, hook command,
status line command and stdio MCP start, so a defect in the wrapper breaks the whole session. Whether to ship it, and
in what default, is a product call. The issue also lists unverified points that need a live-session spike first.

## Questions for the owner

1. Ship a `CLAUDE_CODE_SHELL_PREFIX` wrapper at all? The alternative is an advisory only, plus asking Anthropic for a
   native `CLAUDE_CODE_TOOL_TASKS_LIMIT` beside `CLAUDE_CODE_TOOL_MEMORY_LIMIT`.
2. If shipped: on by default with `on_unavailable: warn`, or opt-in?
3. First scope: the user-namespace rung alone (the only one measured), or the whole ladder?

## Goals

- A runaway fork chain in one Bash tool call fails on its own with EAGAIN, and the session, its hooks and its other
  tool calls carry on.
- The active strategy, or its absence, is stated at SessionStart and in `health`.

## Non-Goals

- Rewriting command text in a PreToolUse handler. That changes permission matching and the `sleep` auto-background
  exemption, and shows the model a prelude it did not write.
- Container-wide or session-wide limits, which already exist and cause the incident.

## Tasks

### Phase 0: Decision

- [ ] ⬜ **Task 0.1**: Owner answers the three questions above.

### Phase 1: Spike in a live session (before any design is fixed)

- [ ] ⬜ **Task 1.1**: Verify in a live Claude Code session that a prefix wrapper passes the tool shell's cwd
  hand-back, exit status, stdin and permission matching through unchanged. Also verify whether the prefix runs
  inside or outside the Claude Code sandbox when that is enabled, and measure the per-call cost.
- [ ] ⬜ **Task 1.2**: Check each strategy rung where it can run: systemd scope on a host with a user manager, the
  user-namespace rung where unprivileged namespaces are restricted, and real root.
- [ ] ⬜ **Task 1.3**: Check the issue's claim that `bash_safe_mode`'s "inject is reserved, the serialiser never emits
  it" note is stale (Plan 00271 added updatedInput); record a niggle if so.

### Phase 2: Implementation (only after Phase 0 and 1)

- [ ] ⬜ **Task 2.1**: TDD the wrapper, strategy detection (once per session) and the pass-through for every non-Bash
  invocation.
- [ ] ⬜ **Task 2.2**: TDD the config block (`tasks`, `memory`, `strategy`, `exempt_patterns`, `on_unavailable`) and
  the in-command escape hatch.
- [ ] ⬜ **Task 2.3**: SessionStart advisory and `health` line naming the active strategy.
- [ ] ⬜ **Task 2.4**: Installer writes the prefix into the project settings; upgrade guide and release notes.

## Success Criteria

- [ ] The issue's bounded reproduction (a self-calling PATH stand-in) fails with EAGAIN inside one tool call while the
  calling session can still fork.
- [ ] A host with no available strategy says so at SessionStart, and no Bash call is denied by default.
- [ ] Release-bound consequences (the new config block, the settings change, the upgrade step) are recorded in the
  pending-release holding area.

## Delivery & Milestones

- Plan filed from issue #137 triage.
