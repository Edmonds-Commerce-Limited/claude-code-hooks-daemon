# Plan 00119: Scope single-daemon enforcement to actual daemon server processes

**Status**: Complete
**Created**: 2026-06-04
**Owner**: Claude (Opus)
**Priority**: High
**Type**: Bug Fix (safety-critical enforcement)
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded (small, safety-critical, must stay coherent)

## Overview

`find_all_daemon_processes` / `_is_daemon_process`
(`src/claude_code_hooks_daemon/daemon/process_verification.py`) classify **any**
process whose cmdline contains the string `claude_code_hooks_daemon` as a
killable "daemon process". Under container single-daemon enforcement
(`enforce_single_daemon`) these get SIGTERMed (SIGTERM → SIGKILL).

That set wrongly includes **transient CLI invocations** that are not daemon
servers:

- `cli status`, `cli stop`, `cli logs`, `cli health`, `cli repair`,
  `cli check-truth-changes`, `cli generate-docs`, `cli validate-*`, …
- the hook forwarders (`claude_code_hooks_daemon.hooks.pre_tool_use`, etc.)
- the short-lived `cli start` / `cli restart` **parent** that polls for the PID
  file before exiting.

This is the substrate of the v3.18.2 field "exit 143" upgrade bug: a concurrent
daemon start ran enforcement and SIGTERMed the in-flight starter. v3.18.2 fixed
the *user-visible symptom* (`restart_daemon_verified` now defers to its status
poll). This plan fixes the *root cause*: enforcement must only ever target
genuine daemon **server** processes.

## Goals

- `find_all_daemon_processes` returns ONLY genuine daemon server processes.
- Transient CLI helpers and hook forwarders are never returned (so enforcement
  never SIGTERMs them).
- **Zero false negatives**: every real daemon server is still found (missing one
  would let two daemons coexist — the exact failure enforcement prevents).
- Project-root scoping behaviour (Plan from v3.18.0) is preserved unchanged.

## Non-Goals

- No change to `enforce_single_daemon` policy (container-kills / non-container
  conservative cleanup stays as-is).
- No process-title/argv mutation of the daemon server.
- No ppid/session-leader heuristics (reaper-dependent → could reintroduce false
  negatives under a subreaper; rejected — see Decision 2).

## Context & Background (verified facts)

Verified by reading `daemon/cli.py`:

- Daemonization (`os.fork` ×2, `os.setsid`, `HooksDaemon(...)`,
  `asyncio.run(daemon.start())`) happens **only** in `cmd_start`.
- `cmd_start` is reached only from the `start` subcommand dispatch and from
  `cmd_restart` (the `restart` subcommand), which calls `cmd_start(args)`.
- `os.fork()` does not rewrite argv, so the detached daemon's
  `/proc/<pid>/cmdline` is the original invocation: `... cli [--project-root X] start` for a start-launched daemon, `... cli restart` for a restart-launched
  one. (Confirmed live: a running daemon shows `python -m claude_code_hooks_daemon.daemon.cli --project-root /workspace start`, ppid 1.)
- Therefore the set of subcommands that can produce a daemon server is exactly
  `{start, restart}` — provably complete.

The daemon server's `proc.name()` is `python` / `python3.11`, never
`claude_code_hooks_daemon`, so the existing name-based match is dead for real
daemons and only ever produced false positives.

## Technical Decisions

### Decision 1: Match by cli module + launch subcommand (allowlist)

A process is a daemon **server** iff its cmdline contains the cli module token
`claude_code_hooks_daemon.daemon.cli` AND a later token equals one of the
launch subcommands `("start", "restart")`.

**Why an allowlist of subcommands**: provably complete (only start/restart reach
`cmd_start`), so zero false negatives. Excludes every transient helper and the
hook forwarders. Adding a future daemonizing subcommand requires adding it here —
guarded by a test that cross-references `cmd_restart → cmd_start`.

### Decision 2: Do NOT add ppid==1 / session-leader filtering

The detached daemon has ppid==1 (this container) but that depends on the reaper.
Under a subreaper (tini, systemd-in-container, a wrapper that
`PR_SET_CHILD_SUBREAPER`s) the daemon reparents to the subreaper, not 1. Filtering
on ppid==1 would then MISS a real daemon — a false negative, the dangerous
direction. Rejected.

### Decision 3: Accept the benign start/restart-parent residual

The short-lived `start`/`restart` parent (and a manual `cli restart`) share the
subcommand with the server, so concurrent enforcement may still SIGTERM them.
This is benign: the detached child survives (reparented), and v3.18.2
`restart_daemon_verified` tolerates a superseded starter. Documented, not fixed —
fixing it needs the rejected ppid/session heuristics.

### Decision 4: Correct the synthetic test fixtures

Existing `test_process_verification.py` fixtures use unrealistic cmdlines
(`...daemon.server`, bare `...daemon.cli` with no subcommand) and assert they
match. Those encode the buggy broad contract. They are updated to realistic
daemon-server cmdlines (`...daemon.cli ... start`) so they still test their
intent (scoping, current-pid exclusion, error handling) under the corrected
contract. New tests assert transient helpers / hook forwarders are NOT matched.
This is correcting a buggy spec under explicit mandate — not weakening tests to
fit broken code.

## Tasks

### Phase 1: TDD — corrected matching contract

- [x] **Task 1.1**: Add RED tests in
  `tests/unit/daemon/test_process_verification.py`:
  - transient subcommands NOT matched: `status`, `stop`, `logs`, `health`,
    `repair`, `check-truth-changes`, `generate-docs`
  - hook forwarder cmdline NOT matched
  - bare `...daemon.cli` (no subcommand) NOT matched
  - `...daemon.cli ... start` matched; `...daemon.cli restart` matched
  - `--project-root` scoping still works with realistic start cmdlines
- [x] **Task 1.2**: Implement `_DAEMON_CLI_MODULE` +
  `_DAEMON_LAUNCH_SUBCOMMANDS` constants and a precise
  `_is_daemon_server_process(cmdline)`; rewire `find_all_daemon_processes`;
  drop the name-only match.
- [x] **Task 1.3**: Update existing fixtures (Decision 4) to realistic
  cmdlines; keep their intent. GREEN.

### Phase 2: Integration & regression

- [x] **Task 2.1**: Verify `test_enforcement.py` still passes (mocks
  `find_all_daemon_processes`); adjust only if it constructs unrealistic
  cmdlines.
- [x] **Task 2.2**: Add a guard test that documents the allowlist completeness
  (a comment-backed test pinning `_DAEMON_LAUNCH_SUBCOMMANDS == ("start", "restart")` with the cmd_restart→cmd_start rationale).

### Phase 3: QA + daemon load + commit

- [x] **Task 3.1**: `./scripts/qa/llm_qa.py all` → 13/13.
- [x] **Task 3.2**: Restart daemon, verify RUNNING (load test).
- [x] **Task 3.3**: Commit with regression context.

## Success Criteria

- [x] Transient CLI helpers + hook forwarders never returned by
  `find_all_daemon_processes`.
- [x] Real daemon servers (start- AND restart-launched) still found.
- [x] Project-root scoping unchanged.
- [x] QA 13/13, daemon restarts RUNNING.

## Notes & Updates

### 2026-06-04

- Plan created. Root-cause follow-up to the v3.18.2 patch (commit eca7f77) which
  fixed only the user-visible false-failure symptom.
- Complete. `find_all_daemon_processes` now matches only daemon **server**
  cmdlines (cli module + `start`/`restart` launch subcommand) via
  `_is_daemon_server_process`; the broad name/substring match and
  `DAEMON_PROCESS_NAME` are removed. Transient CLI helpers (status/stop/logs/
  health/repair/check-truth-changes/generate-docs) and hook forwarders are no
  longer killable by single-daemon enforcement. Allowlist proven complete
  (os.fork/os.setsid/HooksDaemon/asyncio.run live only in cmd_start, reachable
  only via start/restart) → zero false negatives; guarded by a unit test.
  Project-root scoping preserved. 8 new/repurposed tests; existing synthetic
  fixtures corrected to realistic server cmdlines (Decision 4). QA 13/13 (8470
  tests, 95.0%), daemon restart RUNNING with no enforcement errors. Delivered in
  the Plan 00119 closure commit.
