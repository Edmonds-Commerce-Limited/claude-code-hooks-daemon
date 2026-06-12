# Plan 00123: macOS Portability Follow-ups

**Status**: In Progress
**Created**: 2026-06-12
**Owner**: Claude (Opus)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded (small, focused shell fixes)

## Overview

Plan 00122 fixed 6 macOS bugs from a downstream field report. During release
preparation for v3.19.0, a dedicated macOS-gotcha hunt (read-only recon agent)
surfaced four further BSD/bash-3.2 incompatibilities that the original report
did not cover. Two are on the per-hook runtime hot path and one (`init.sh`
`realpath` under `set -euo pipefail`) can abort every hook on macOS versions
that lack `realpath`. These must be fixed before the v3.19.0 release.

## Goals

- Remove the unguarded `realpath` call from `init.sh` (it is also dead code).
- Make the `resolve_venv.sh` hot-path cache `stat` portable (GNU `stat -c %Y`
  with BSD `stat -f %m` fallback) so the cache actually hits on macOS.
- Fix the `pgrep` GNU-BRE alternation in `daemon_control.sh` so the
  daemon-process fallback works on BSD `pgrep`.
- Make the `readlink -f` self-install short-circuit in `hooks_deploy.sh`
  portable on BSD (no `readlink -f`).

## Non-Goals

- The deferred LOW items from the hunt (`sort -V` in an error message,
  `echo -e`/`&>` under the documented bash shebang, hardcoded `/tmp`). These
  work under documented invocation and are not release-blocking.

## Context & Background

macOS default bash is 3.2.57 and ships BSD coreutils. Findings (verified
against source before fixing):

1. **CRITICAL** `init.sh:389` — `_abs_project_path=$(realpath "$PROJECT_PATH")`.
   Runs on every hook under `set -euo pipefail`; `realpath` is absent on macOS
   < 12.3, so the substitution fails and aborts init.sh → every hook breaks.
   The variable is never referenced anywhere (dead code) → delete the line.
2. **HIGH** `scripts/lib/resolve_venv.sh:191,233` — `stat -c %Y` (GNU-only) with
   `2>/dev/null`. On macOS it returns empty, the cache-mtime compare always
   fails → cache never hits → Python fingerprint spawn on every hook
   (blows the \<5ms budget). Mirror the `init.sh:346-354` `-c`/`-f` fallback.
3. **MEDIUM** `scripts/install/daemon_control.sh:259` — `pgrep -f "a\|b"`. The
   `\|` BRE alternation is GNU-only; BSD `pgrep` matches the literal → never
   matches a real daemon → false "failed to start" on slow macOS. Use two
   `pgrep` invocations OR ERE.
4. **MEDIUM** `scripts/install/hooks_deploy.sh:122` — `readlink -f` (BSD has no
   `-f`); both sides fall back to unresolved literals that differ → the
   self-install "already in place, skip" short-circuit never fires on macOS.
   Use a portable abs-path resolver.

## Tasks

### Phase 1: HIGH/CRITICAL hot-path fixes

- [ ] **Task 1.1**: Extract a portable `_rv_dir_mtime` helper in resolve_venv.sh
  (`stat -c %Y` → `stat -f %m` fallback); use at both call sites. TDD with
  a BSD-stat stub asserting cache hit.
- [ ] **Task 1.2**: Delete dead `_abs_project_path` realpath line from init.sh.
  Regression test: init.sh contains no unguarded `realpath`.

### Phase 2: MEDIUM install/restart-path fixes

- [ ] **Task 2.1**: Fix `daemon_control.sh` pgrep alternation. Test stub pgrep.
- [ ] **Task 2.2**: Fix `hooks_deploy.sh` readlink -f → portable resolver.

### Phase 3: Verify

- [ ] **Task 3.1**: shellcheck + full QA (`./scripts/qa/llm_qa.py all`).
- [ ] **Task 3.2**: Daemon restart RUNNING.

## Success Criteria

- [ ] All four constructs are portable on bash 3.2 / BSD coreutils.
- [ ] New regression tests pass; existing suite green; QA 13/13.
- [ ] Daemon restarts cleanly.

## Notes & Updates

### 2026-06-12

- Created during v3.19.0 release prep from macOS-gotcha hunt findings.
