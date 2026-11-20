# Plan 00628: daemon socket path too long from init sh

**Status**: Complete
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
- `init.sh`'s readiness poll follows the discovery file the daemon publishes,
  so the hook that starts the daemon also reaches it.
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

- [x] ✅ **Task 1.1**: unit tests for path selection (forced and default, socket and PID, never over the limit; one function) — `tests/unit/daemon/test_socket_path_fit.py`
- [x] ✅ **Task 1.2**: unit tests for the discovery-file lifecycle (absent after a failed bind; incumbent's file intact) — `tests/unit/daemon/test_cli_start_discovery_after_bind.py`
- [x] ✅ **Task 1.3**: unit tests for the fallback root's ownership and mode checks, and the no-runtime-dir case
- [x] ✅ **Task 1.4**: integration test: long project path, no discovery file, one `init.sh` start reaches a daemon — `tests/integration/test_init_sh_long_project_path_reaches_its_daemon.py`

### Phase 2: GREEN

- [x] ✅ **Task 2.1**: `paths.fit_socket_path` / `fit_pid_path`, used by `get_socket_path`, `get_pid_path`, the CLI flags, the config getters and `transport_verify.resolve_events_dir`
- [x] ✅ **Task 2.2**: safe short-path root (`_is_private_dir`; `/tmp/hooks-daemon-<uid>` 0700 or `UnsafeRuntimeDirError`, reported by `cmd_start` before the fork)
- [x] ✅ **Task 2.3**: discovery file published from the `serving` callback, cleaned only by its publisher
- [x] ✅ **Task 2.4**: `init.sh` follows discovery in its readiness poll (its launcher still passes its computed paths; the daemon fits them)

### Phase 3: Release

- [x] ✅ **Task 3.1**: release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/006-long-project-path-socket.md`

## Success Criteria

- [x] All new tests fail before the fix and pass after; the touched existing suites pass
- [x] The reproduction scripts show one hook start reaching the daemon
- [x] The release-bound consequence is recorded in the pending-release holding area: the 00628 callout `CLAUDE/UPGRADES/v3/v3.75.0-to-v3.76.0/release-notes/006-long-project-path-socket.md` (moved there from `UNRELEASED/release-notes/` at the v3.76.0 release)
- [x] Merged by the coordinator after the full QA gate (merge `2628d4965`, released as v3.76.0, release merge `de8833b5b`)

## Delivery & Milestones

- Merge `2628d4965` (Plan 00628 branch); code commits `55460bf4a`, `4005eee3a`, `bd05c243b`; shipped in tag v3.76.0
- Follow-up rough edges ledgered as N681 in `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md` (already present, not duplicated)
