# Plan 00628: daemon socket path too long from init sh

**Status**: In Progress
**Created**: 2026-11-19
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded
**Target release**: 3.76.0

## Overview

A client seat (v3.74.0, still present in v3.75.0) whose project path is long
had EVERY tool call denied. `init.sh`, finding no discovery file, started the
daemon with its own default socket path FORCED through
`CLAUDE_HOOKS_SOCKET_PATH` / `CLAUDE_HOOKS_PID_PATH`. `paths.get_socket_path`
returns an override verbatim, so the length fallback never ran and the bind
failed (`AF_UNIX path too long`); every hook got `daemon_startup_failed`. The
CLI, invoked without the override, places the socket under the short runtime
directory, so `status` reports RUNNING while hooks cannot reach it.

Worse, the failed start wrote the shared discovery file (pointing at its own
unbindable path) BEFORE binding, then deleted it on the crash path, so a live
incumbent's discovery file vanished and the next hook lost it too.

Reproduced in this worktree (`untracked/scratch/00628/repro*.bash`, output in
the journal): the forced start dies, the discovery file is deleted, `status`
says RUNNING on `/run/user/...`, the next hook's `SOCKET_PATH` is the long one.

## Goals

- One function decides the socket and PID path for every caller (default,
  env-forced, `--socket` flag, config), and never yields a socket path over the
  AF_UNIX limit.
- `init.sh` stops forcing its computed paths on the daemon, and its readiness
  poll follows the discovery file the daemon publishes, so the hook that starts
  the daemon also reaches it.
- The discovery file is written only after a successful bind and removed only
  by the process that wrote it.
- The short fallback directory keeps the protection the untracked directory
  had: owned by this user and closed to group and others, never a bare shared
  `/tmp`; otherwise a private 0700 subdirectory, or fail closed with a clear
  message.

## Non-Goals

- The launcher printing "Daemon started successfully" for a daemon that died
  while binding (recorded as a niggle, not fixed here).
- Relay/per-event socket placement (unchanged apart from sharing the safer root).

## Tasks

### Phase 1: RED

- [ ] ⬜ **Task 1.1**: unit tests for path selection (forced and default, socket and PID, never over the limit; one function)
- [ ] ⬜ **Task 1.2**: unit tests for the discovery-file lifecycle (absent after a failed bind; incumbent's file intact)
- [ ] ⬜ **Task 1.3**: unit tests for the fallback root's ownership and mode checks, and the no-runtime-dir case
- [ ] ⬜ **Task 1.4**: integration test: long project path, no discovery file, one `init.sh` start reaches a daemon

### Phase 2: GREEN

- [ ] ⬜ **Task 2.1**: `paths.fit_socket_path` / `fit_pid_path`, used by `get_socket_path`, `get_pid_path`, the CLI flags and the config getters
- [ ] ⬜ **Task 2.2**: safe short-path root
- [ ] ⬜ **Task 2.3**: discovery file published from the `serving` callback
- [ ] ⬜ **Task 2.4**: `init.sh` passes only caller-set paths and follows discovery in its poll

### Phase 3: Release

- [ ] ⬜ **Task 3.1**: release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/006-*.md`

## Success Criteria

- [ ] All new tests fail before the fix and pass after; the touched existing suites pass
- [ ] The reproduction scripts show one hook start reaching the daemon
- [ ] The release-bound consequence is recorded in the pending-release holding area (`CLAUDE/UPGRADES/UNRELEASED/release-notes/006-*.md`)

## Delivery & Milestones

- <!-- delivery commit hashes -->
