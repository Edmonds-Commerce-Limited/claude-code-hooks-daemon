# Plan 00122: macOS Portability Fixes

**Status**: Complete
**Created**: 2026-06-11
**Owner**: Claude (Opus)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded (TDD per bug, checkpoint commit each)

## Overview

A downstream client (client-a / supplier-integration) filed a detailed bug
report (`untracked/mac-issues/2026-06-11-macos-incompatibility.md`) showing the
daemon is non-functional on macOS. Six defects were identified and all six
have been reproduced/confirmed against the source. The most severe (BUG 1) is
not strictly macOS-specific: it affects **any environment where `HOSTNAME` is
unset** (default on macOS/zsh, common on minimal Linux/CI images).

This plan fixes each defect with TDD, restarts the daemon, and runs full QA.

## Goals

- Daemon reaches a manageable RUNNING state on macOS (and any HOSTNAME-unset env)
- `start`/`status`/`stop` agree on the same socket/PID path every time
- Installer venv creation no longer emits a stray `stat` error on BSD/macOS
- Diagnostic tooling (`health-check.sh`, `debug_info.py`) is honest about failure
- Docs reconciled with actual behaviour; bash-3.2 portability addressed

## Non-Goals

- Rewriting the hostname-isolation architecture
- Supporting overlayfs detection on macOS (overlayfs is Linux-only)

## Context & Background

Confirmed root causes (verified against source on 2026-06-11):

- **BUG 1 (CRITICAL)** `daemon/paths.py` `_get_hostname_suffix()` — when
  `HOSTNAME` is empty it derives the suffix from `time.time()` and is not
  memoised, so every call returns a different suffix. socket/PID/discovery
  files each get a different suffix → daemon unmanageable.
- **BUG 2 (HIGH)** `scripts/install/venv.sh:474` — `stat -f -c %T` mixes GNU
  coreutils flags; on BSD/macOS `-f` is the format flag so the call errors.
- **BUG 3 (MEDIUM)** `skills/.../scripts/install.sh:100` — "already installed"
  guard only checks `[ -d "$DAEMON_DIR" ]`; a broken/partial install can't be
  repaired without `--force`.
- **BUG 4 (MEDIUM)** `skills/.../scripts/health-check.sh` exits non-zero with
  no reason on some failures; `scripts/debug_info.py` misreports project root
  and degrades poorly when `init.sh` path detection fails.
- **BUG 5 (LOW)** `CLAUDE.md` "Hostname-Based Isolation" documents the broken
  time-hash branch as a normal edge case.
- **BUG 6 (LOW)** Apple `/bin/bash` is 3.2.57; latent risk from bash-4 constructs.

## Tasks

### Phase 1: BUG 1 — deterministic hostname suffix (CRITICAL)

**Both** the Python daemon (`paths.py`) AND the bash hook forwarder
(`init.sh:300`) independently compute the suffix, and BOTH use the broken
time-hash fallback. They must use the SAME deterministic source
(`socket.gethostname()` ≈ `hostname` command) so the forwarder and daemon
agree on the socket/PID path. `scripts/upgrade.sh:429-431` already uses the
correct `${HOSTNAME:-}` → `hostname` pattern (reference).

Antipattern sweep result (user request "catch other stupid stuff like this"):
the ONLY two sites abusing time-as-identity are these two hostname fallbacks.
All other `time.time()`/`random` uses are legitimate (durations, TTLs, idle
detection, advisory sampling).

The multi-host fail-fast (`_cli_resolve_venv`, `paths.py:1498`) intentionally
asks a DIFFERENT question — "did the operator EXPLICITLY pin `$HOSTNAME`" for
NFS disambiguation — so it stays a direct env check (must NOT resolve via
`gethostname()`), with a cross-reference comment.

- [x] **Task 1.1**: RED (Python) — rewrote `test_empty_hostname_gets_time_hash`
  (asserts the defect) + determinism / blank-hostname / constant-fallback
  tests; added a bash↔Python suffix parity test (HOSTNAME unset)
- [x] **Task 1.2**: GREEN (Python) — added DRY memoised `resolve_hostname()`
  helper (series: `$HOSTNAME` → `socket.gethostname()` → constant); routed
  `_get_hostname_suffix()` and `cmd_bug_report` through it
- [x] **Task 1.3**: GREEN (bash) — fixed `init.sh:_get_hostname_suffix()` to
  fall back to the `hostname` command, never a time hash
- [x] **Task 1.4**: `import time` still used elsewhere (durations) — N/A
- [x] **Task 1.5**: QA (12/13; format autofixed) + daemon restart (RUNNING) +
  commit. Also reconciled CLAUDE.md Hostname-Based Isolation doc (BUG 5 part).

### Phase 2: BUG 2 — portable filesystem-type probe in venv.sh (HIGH)

- [x] **Task 2.1**: RED — test that on Darwin the `stat -c` probe is skipped
  (no stray error, hardlink-first), Linux branch unchanged
- [x] **Task 2.2**: GREEN — gated the fs probe on `uname -s` = Linux
- [x] **Task 2.3**: QA (12 venv.sh tests pass; shellcheck clean) + commit

### Phase 3: BUG 3 — health-aware install guard (MEDIUM)

- [x] **Task 3.1**: RED — extract-and-source tests for `_installation_is_healthy`
  - static guard-wiring contract test
- [x] **Task 3.2**: GREEN — `_installation_is_healthy` (venv python imports);
  unhealthy dir auto-escalates to `--force` repair instead of `exit 0`
- [x] **Task 3.3**: Updated existing skill-install fixture to a healthy install
  (+ mktemp on stripped PATH); 33 install/skill/H-1 tests pass; shellcheck clean

### Phase 4: BUG 4 — honest diagnostics (MEDIUM)

- [x] **Task 4.1**: `health-check.sh` EXIT trap emits script/exit-code/line on
  any non-zero exit (silent set-e death made honest)
- [x] **Task 4.2**: `debug_info.py` detects client root via `.claude/hooks-daemon.yaml`
  (not the clone dir) + degrades gracefully (dumps runtime files/venv/processes)
- [x] **Task 4.3**: 16 tests (debug_info 3, health-check 1, diagnostic H-1 12)
  pass; shellcheck clean; commit

### Phase 5: BUG 5 / BUG 6 — docs + bash portability (LOW)

- [x] **Task 5.1**: Reconciled `CLAUDE.md` Hostname-Based Isolation section +
  `init.sh`/`paths.py` docstrings (done in Phase 1)
- [x] **Task 5.2**: Swept user-facing scripts — already bash-3.2 clean; the only
  bash-4 construct was `mapfile` in the dev-only `run_shell_check.sh`, now a
  portable while-read loop. Added a regression-guard test scanning all repo
  shell scripts for bash-4-only syntax. (No preflight — it would wrongly reject
  bash 3.2, which the scripts already support.)
- [x] **Task 5.3**: bash32 test + shellcheck clean; run_shell_check.sh still
  finds 56 scripts and passes; commit

## Success Criteria

- [x] All new + existing tests pass; coverage ≥ 95% (8527 passed, 0 failed, 95.1%)
- [x] `llm_qa.py all` passes (13/13)
- [x] Daemon restarts to RUNNING after each phase
- [x] Two consecutive `get_socket_path()` calls with `HOSTNAME` unset are equal
  (pinned by `test_empty_hostname_suffix_is_deterministic`)

## Notes & Updates

### 2026-06-11

- Plan created from downstream macOS bug report; all six bugs reproduced.
- User explicitly confirmed BUG 1 fix direction: use `$(hostname)` /
  `socket.gethostname()` when `HOSTNAME` is unset.
- Delivery commits: Phase 1 `8d72594` (BUG 1, + BUG 5 doc), Phase 2 `e71df0c`
  (BUG 2), Phase 3 `28745d2` (BUG 3), Phase 4 `ec27240` (BUG 4). BUG 1 CLAUDE.md
  doc landed via the daemon's auto-regen commit `8802b08`.
- Antipattern sweep (user directive): the time-as-identity abuse existed only at
  the two hostname fallbacks (`paths.py` + `init.sh`); both fixed. All other
  `time.time()`/`random` uses are legitimate.
- DRY: single memoised `resolve_hostname()` is the SSOT on the Python side
  (routed: `_get_hostname_suffix`, `cmd_bug_report`); `init.sh` mirrors it for
  bash. The `_cli_resolve_venv` multi-host check stays a raw env check by design.
