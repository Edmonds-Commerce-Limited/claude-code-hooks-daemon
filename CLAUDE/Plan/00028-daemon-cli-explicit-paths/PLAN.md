# Plan 00028: Daemon CLI Explicit Paths for Worktree Isolation

**Status**: Not Started
**Created**: 2026-02-06
**Owner**: To be assigned
**Priority**: High
**Type**: Bug Fix / Feature Enhancement

## Overview

When multiple agents work in git worktrees simultaneously, each worktree runs its own daemon. The daemon CLI discovers the project root by walking up the directory tree from CWD to find `.claude/`. This auto-discovery can produce wrong results when:

1. An agent's CWD is not inside its worktree (e.g., still in `/workspace`)
2. Multiple daemons share the same hostname, causing PID/socket file collisions
3. The CLI walks past a worktree's `.claude/` and finds the main workspace's `.claude/`

These scenarios cause **cross-kill** (restarting daemon in worktree kills main workspace daemon), **PID confusion** (status shows wrong daemon), and **discovery instability** (inconsistent behavior depending on CWD).

## Goals

- Add `--pid-file` and `--socket` CLI flags to all daemon commands
- When explicit flags are provided, skip auto-discovery for those specific paths
- Maintain full backward compatibility (flags are optional)
- Update Worktree.md documentation to recommend explicit paths for worktree daemons
- Achieve 95%+ test coverage on new code with TDD

## Non-Goals

- Changing the auto-discovery algorithm itself
- Modifying the hook entry point scripts (they use the daemon socket, not the CLI)
- Changing how `HooksDaemon` (server.py) manages its socket/PID internally
- Removing or deprecating the environment variable overrides

## Context and Background

The existing `--project-root` flag (added at `cli.py:913-917`) already overrides auto-discovery of the project root. However, it does not allow independent control of PID and socket paths. The existing environment variable overrides (`CLAUDE_HOOKS_SOCKET_PATH`, `CLAUDE_HOOKS_PID_PATH`, `CLAUDE_HOOKS_LOG_PATH`) provide per-process overrides but are awkward to use for per-command invocations.

The `paths.py` module already supports environment variable overrides as the first check in `get_socket_path()` and `get_pid_path()`. The new CLI flags will override paths at a higher level -- directly in the `cmd_*` functions -- before those `paths.py` functions are called.

## Tasks

### Phase 1: TDD - Unit Tests (Red)

- [ ] **Task 1.1**: Create test file `tests/unit/daemon/test_cli_explicit_paths.py`
  - [ ] Test: `--pid-file` flag is parsed by argparse and available in `args.pid_file`
  - [ ] Test: `--socket` flag is parsed by argparse and available in `args.socket`
  - [ ] Test: `cmd_status` uses explicit `--pid-file` when provided
  - [ ] Test: `cmd_status` uses explicit `--socket` when provided
  - [ ] Test: `cmd_stop` uses explicit `--pid-file` and `--socket` when provided
  - [ ] Test: `cmd_start` uses explicit `--pid-file` and `--socket` when provided
  - [ ] Test: `cmd_logs` uses explicit `--socket` when provided
  - [ ] Test: `cmd_health` uses explicit `--socket` when provided
  - [ ] Test: `cmd_handlers` uses explicit `--socket` when provided
  - [ ] Test: When `--pid-file` is omitted, `get_pid_path()` is called (backward compat)
  - [ ] Test: When `--socket` is omitted, `get_socket_path()` is called (backward compat)
  - [ ] Test: `--pid-file` and `--socket` can be used independently
  - [ ] Test: `--pid-file` and `--socket` can be combined with `--project-root`
  - [ ] Test: `cmd_restart` passes explicit paths through both stop and start

- [ ] **Task 1.2**: Run tests -- they MUST FAIL (flags do not exist yet)

### Phase 2: Implementation (Green)

- [ ] **Task 2.1**: Add `--pid-file` and `--socket` global flags to argparse in `main()`
  - Add to `cli.py` where `--project-root` is defined
  - `--pid-file` type: `Path`, help: "Explicit PID file path (overrides auto-discovery)"
  - `--socket` type: `Path`, help: "Explicit socket path (overrides auto-discovery)"

- [ ] **Task 2.2**: Create helper functions to resolve paths with override support
  - Add `_resolve_pid_path(args, project_path) -> Path`
  - Add `_resolve_socket_path(args, project_path) -> Path`

- [ ] **Task 2.3**: Update all `cmd_*` functions to use the helper functions
  - `cmd_start()`, `cmd_stop()`, `cmd_status()`, `cmd_logs()`
  - `cmd_health()`, `cmd_handlers()`, `cmd_repair()`
  - `cmd_restart()` delegates to stop+start (inherits flags)

- [ ] **Task 2.4**: Ensure `cmd_start()` passes explicit paths to the daemon process
  - When setting `daemon_config.socket_path` and `daemon_config.pid_file_path`, use resolved paths from args

- [ ] **Task 2.5**: Run tests -- they MUST PASS

### Phase 3: Refactor

- [ ] **Task 3.1**: Review for DRY violations
- [ ] **Task 3.2**: Add type annotations, run mypy strict mode

### Phase 4: Integration Testing

- [ ] **Task 4.1**: Add integration test for explicit paths end-to-end
- [ ] **Task 4.2**: Test worktree isolation with two different project roots

### Phase 5: Documentation

- [ ] **Task 5.1**: Update `CLAUDE/Worktree.md` "Daemon Process Isolation" section
  - Recommend CLI flags over env vars for worktree daemons
- [ ] **Task 5.2**: Update CLI `--help` text

### Phase 6: QA and Daemon Verification

- [ ] **Task 6.1**: `./scripts/qa/run_autofix.sh`
- [ ] **Task 6.2**: `./scripts/qa/run_all.sh` -- ZERO failures
- [ ] **Task 6.3**: Daemon restart verification
- [ ] **Task 6.4**: Verify explicit flags work with live daemon

## Dependencies

- None (standalone enhancement)

## Technical Decisions

### Decision 1: Global flags vs subcommand-specific flags
**Decision**: Global parser (matches existing `--project-root` pattern)

### Decision 2: Helper functions vs inline resolution
**Decision**: Extract `_resolve_pid_path()` and `_resolve_socket_path()` helpers (DRY)

### Decision 3: Interaction with environment variable overrides
**Decision**: CLI flags > env vars > auto-discovery (most explicit wins)

## Success Criteria

- [ ] `--pid-file` and `--socket` flags accepted by all CLI commands
- [ ] Explicit paths completely bypass auto-discovery when provided
- [ ] Backward compatible: omitting flags preserves current behavior
- [ ] All existing tests pass unchanged
- [ ] 95%+ coverage on modified code
- [ ] Full QA suite passes
- [ ] Worktree.md updated with explicit-path recommendations

## Files to Modify

| File | Change |
|------|--------|
| `src/claude_code_hooks_daemon/daemon/cli.py` | Add flags, helpers, update cmd_* functions |
| `tests/unit/daemon/test_cli_explicit_paths.py` | NEW: TDD tests |
| `tests/integration/test_cli_explicit_paths_integration.py` | NEW: integration tests |
| `CLAUDE/Worktree.md` | Update daemon isolation docs |
