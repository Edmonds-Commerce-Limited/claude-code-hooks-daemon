# Plan 00187: socket discovery split brain cli reconciliation

**Status**: Complete
**Created**: 2026-07-23
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (TDD)

## Overview

A field report (`untracked/hooks-daemon-socket-mixup-upgrade.md`) documented a
confusing failure after a v3.47.0 → v3.48.0 upgrade: every management/health
command (`status`, `health`, `restart`) reported `Daemon: NOT RUNNING` while
hooks kept firing normally. The daemon was running the whole time — the two
halves of the install had diverged on the socket name.

Root cause: a stale, git-tracked `.claude/hooks-daemon.env` in the client
project pinned a hand-picked short socket name (`-pda`) as an AF_UNIX
length-limit workaround. The **bash hook forwarders** (`init.sh`) source that
env and bind/look-up `-pda.sock` (so hooks worked). The **Python management
CLI**, invoked directly without sourcing that env, falls through to
`get_socket_path()` → the deterministic hash name `-aee977c2.sock`, finds
nothing there, and reports `NOT RUNNING`.

The asymmetry that makes this silent: `init.sh` consults the daemon's
**socket discovery file** (`daemon{suffix}.socket-path`, written by the daemon
at every startup with its *actual* bound socket) as a fallback, but the Python
CLI does **not**. This plan closes that gap — the management CLI now mirrors
`init.sh`'s discovery-file fallback, so `status`/`health` agree with the hook
forwarders and surface an explicit split-brain drift warning instead of a bare
`NOT RUNNING`.

## Goals

- The management CLI's read/diagnostic commands (`status`, `health`) find a
  live daemon via the socket discovery file when the computed socket path has
  no live daemon — mirroring `init.sh`'s existing fallback (DRY: both sides use
  the same discovery file).
- When a live daemon is discovered on a socket that DIFFERS from the computed
  path, the CLI reports an explicit split-brain drift warning naming both paths
  and the likely cause (a stale `hooks-daemon.env` override), instead of a bare
  `NOT RUNNING` (report recommendation #3; neutralises the "silently broken"
  harm of #2).
- No regression to the explicit-override contract: an explicit `--socket` flag
  or a set `CLAUDE_HOOKS_SOCKET_PATH` env is honoured verbatim and never
  second-guessed (mirrors `init.sh`'s guard).

## Non-Goals

- Rewriting or reconciling the client-authored `hooks-daemon.env` file itself
  (it lives in the client repo; the upstream daemon must not edit client files).
  The durable fix is making the CLI robust to the drift + telling the operator.
- Changing `get_socket_path()`'s handling of env-provided paths (report
  recommendation #1 option b) — that would change the override contract and is
  riskier than the discovery-file fallback, which fully resolves the reported
  symptom.
- Retargeting mutating commands (`stop`/`restart`) at the discovered daemon —
  out of scope for this fix; `status`/`health` diagnosis is the priority.

## Context & Background

- `daemon/paths.py`: `get_socket_path()` honours `CLAUDE_HOOKS_SOCKET_PATH`
  verbatim; `write_socket_discovery_file()` / `cleanup_socket_discovery_file()`
  manage the discovery file at a deterministic (untracked dir + hostname
  suffix) location that does NOT depend on the env override.
- `daemon/cli.py`: `_resolve_socket_path()` / `_resolve_pid_path()` resolve
  CLI flag > env-honouring getter. `cmd_start` writes the discovery file at
  startup (line ~539). `cmd_status` / `cmd_health` read the PID file for
  liveness.
- `init.sh` (lines ~468-480): reads the discovery file as a fallback ONLY when
  `CLAUDE_HOOKS_SOCKET_PATH` is unset AND the computed socket is not live.

## Tasks

### Phase 1: Discovery-file read helper (paths.py)

- [x] ✅ **Task 1.1**: TDD `read_socket_discovery_file(project_dir) -> Path | None`
  - [x] ✅ RED: tests in `tests/daemon/test_paths.py` (round-trips
    `write_socket_discovery_file`; returns None when file missing/empty;
    strips whitespace; honours hostname suffix)
  - [x] ✅ GREEN: implement helper mirroring the write path's location logic
  - [x] ✅ REFACTOR + verify coverage (11 tests, incl. OSError branch)

### Phase 2: Split-brain reconciliation in the CLI (cli.py)

- [x] ✅ **Task 2.1**: TDD `_resolve_effective_daemon(args, project_path)`
  returning `(socket_path, pid_path, drift_warning)`
  - [x] ✅ RED: unit tests — primary live → no fallback/warning; primary dead +
    discovery names a different LIVE daemon → adopt discovered socket/pid +
    warning; discovery names same path → no warning; discovery dead/stale →
    no adoption; explicit `--socket` / `CLAUDE_HOOKS_SOCKET_PATH` → verbatim
  - [x] ✅ GREEN: implement (pid-file liveness via `read_pid_file(..., verify_daemon=True)`,
    pid path = discovered socket sibling `.pid`)
  - [x] ✅ REFACTOR
- [x] ✅ **Task 2.2**: Wire `cmd_status` and `cmd_health` to use it
  - [x] ✅ RED: command-level tests asserting RUNNING + drift warning in the
    split-brain scenario (previously NOT RUNNING)
  - [x] ✅ GREEN: wire in; print the drift warning to stderr
  - [x] ✅ REFACTOR

### Phase 3: Integration & QA

- [x] ✅ **Task 3.1**: Full QA (`llm_qa.py all`) green — 13/13 PASSED,
  10537 tests, coverage 95.2%
- [x] ✅ **Task 3.2**: Daemon restart verification (RUNNING) + live end-to-end
  split-brain dogfood (status on a crafted drifted project reports RUNNING +
  warning instead of the old NOT RUNNING)
- [x] ✅ **Task 3.3**: Field report moved out of `untracked/` into this plan as
  `FIELD-REPORT-socket-mixup-upgrade.md` (tracked supporting doc, resolution
  banner added)

## Success Criteria

- [x] `read_socket_discovery_file` implemented + tested
- [x] `status`/`health` report RUNNING (with a drift warning) in the split-brain
  scenario instead of a bare NOT RUNNING
- [x] Explicit `--socket` / env override still honoured verbatim
- [x] All QA checks pass; daemon restarts RUNNING
- [x] Field report resolved out of `untracked/`

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only. -->

- Plan created at 8880eee8 (parent HEAD)
- Phase 1 `read_socket_discovery_file`: `84fdee7b` (+ OSError test `7235e557`)
- Phase 2 `_resolve_effective_daemon` + cmd_status/cmd_health wiring: `6d501471`
- QA fixes (black + error_hiding exclusion): `57b7001a`
- Field report tracked into plan folder: `a8424c5e`
- Full QA 13/13 (10537 tests, 95.2% coverage); daemon restart RUNNING; live
  end-to-end split-brain dogfood verified

## Notes & Updates

- Failsafe recovery cron: `421460b4` (hourly at :37, non-durable).
