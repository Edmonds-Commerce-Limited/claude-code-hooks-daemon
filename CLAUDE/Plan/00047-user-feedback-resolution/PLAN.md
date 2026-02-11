# Plan 00047: User Feedback Resolution (v2.10.0)

**Status**: Not Started
**Created**: 2026-02-11
**Owner**: Claude
**Priority**: High

## Overview

Three detailed user feedback reports were submitted against v2.10.0 covering fresh install, upgrade (v2.3.0→v2.9.0), and upgrade (v2.9.0→v2.10.0) experiences. This plan triages all issues, deduplicates across reports, and implements fixes in priority order.

Several issues from the v2.3.0→v2.9.0 upgrade report were already resolved by Plan 00046 (Upgrade System Overhaul). This plan focuses on issues that remain outstanding in the current codebase.

## Feedback Sources

All three feedback files are archived in this plan directory:

- `feedback/hooks-daemon-install-feedback-20260211.md` - Fresh install on v2.10.0 (Linux container)
- `feedback/hooks-daemon-upgrade-feedback.md` - Upgrade v2.3.0→v2.9.0 (Fedora, deep path)
- `feedback/upgrade-feedback-v2.9.0-to-v2.10.0-fresh.md` - Upgrade v2.9.0→v2.10.0

## Goals

- Fix all P0/P1 issues so fresh installs work without manual intervention
- Eliminate DEGRADED MODE on first install
- Ensure installer exit code reflects actual success/failure
- Auto-create `.claude/.gitignore` instead of just warning
- Suppress noisy container warnings
- Fix documentation inconsistencies

## Non-Goals

- Interactive config wizard (P3 - future enhancement)
- Smoke-test CLI command (P3 - separate plan)
- Creating all missing upgrade guides v2.1→v2.9 (historic, low value)

## Issue Triage

### Already Fixed by Plan 00046 (Upgrade System Overhaul)

These were reported in the v2.3.0→v2.9.0 upgrade feedback but are resolved:

- ~~Layer 1 checks for Layer 2 BEFORE checkout~~ → Fixed (checkout-first strategy)
- ~~Python version detection (3.9 vs 3.11+)~~ → Fixed (Python version scanning)
- ~~AF_UNIX socket path too long (Python side)~~ → Fixed (XDG_RUNTIME_DIR fallback)
- ~~No venv creation in legacy fallback~~ → Fixed (legacy fallback dropped)
- ~~Config not repaired during upgrade~~ → Fixed (Layer 2 handles)
- ~~Hook scripts not deployed by legacy upgrade~~ → Fixed (Layer 2 handles)
- ~~settings.json not updated during upgrade~~ → Fixed (Layer 2 handles)

### P0 - Critical (Breaks Out-of-Box Experience)

#### Issue 1: `stats_cache_reader` in Default Config Template
**Source**: Install feedback Issue #1
**Files**: `.claude/hooks-daemon.yaml.example` (line ~269)
**Problem**: Default config includes `stats_cache_reader` as a handler entry with `priority: 70`, but `stats_cache_reader.py` is a **utility module** (only contains functions), NOT a handler class. No `StatsCacheReaderHandler` class exists. Fresh installs using this config get DEGRADED MODE immediately with two errors:
1. "Unknown handler 'stats_cache_reader'"
2. "Priority 70 out of range 5-60"
**Fix**: Remove `stats_cache_reader` entry from `.claude/hooks-daemon.yaml.example`
**Also**: Remove orphaned `get_acceptance_tests()` method at line 118 of `stats_cache_reader.py` (floating at module level, not inside any class)
**Also**: Remove `STATS_CACHE_READER` from `HandlerID` constants and `VALID_STATUS_LINE_HANDLER_KEYS` since no handler class exists

#### Issue 2: Duplicate Priorities in Default Config
**Source**: Upgrade feedback Issue #5
**Files**: `.claude/hooks-daemon.yaml.example`
**Problem**: 18+ duplicate priorities across handlers (e.g., 6 handlers at priority 10, 3 at 15). Generates noisy warnings on every daemon start/stop/status.
**Fix**: Assign unique priorities to all handlers in the example config. Each handler within an event type must have a unique priority.

### P1 - High (Requires Manual Intervention or Misleading)

#### Issue 3: Installer Exit Code 1 on Successful Install
**Source**: Install feedback Issue #2
**Files**: `scripts/install_version.sh` (line 310)
**Problem**: `setup_all_gitignores()` returns 1 when `.claude/.gitignore` verification fails (even though root .gitignore was created successfully). The installer doesn't catch this, so bash `set -e` (if enabled) or the final exit code propagates as failure.
**Fix**:
- Auto-create `.claude/.gitignore` with correct content (not just verify)
- Change `setup_all_gitignores` call to not fail the install on .gitignore warnings
- Only return 1 for actual fatal errors

#### Issue 4: `.claude/.gitignore` Not Auto-Created
**Source**: Install feedback Issue #3
**Files**: `scripts/install/gitignore.sh`
**Problem**: `verify_claude_gitignore()` checks if `.claude/.gitignore` exists but doesn't create it. The template exists at `.claude/hooks-daemon/.claude/.gitignore` but is never copied.
**Fix**: Add `ensure_claude_gitignore()` function that creates `.claude/.gitignore` with `hooks-daemon/untracked/` entry if it doesn't exist (normal mode only). Call it from `setup_all_gitignores()` before verification.

#### Issue 5: UV Hardlink Warning in Containers
**Source**: Install feedback Issue #4
**Files**: `scripts/install/venv.sh`
**Problem**: UV shows scary "Failed to hardlink files; falling back to full copy" warning in containers. Benign but alarming to users.
**Fix**: Set `UV_LINK_MODE=copy` before uv commands in `venv.sh`

#### Issue 6: Conflicting .gitignore Documentation
**Source**: Install feedback Issues #5, #6
**Files**: `CLAUDE/LLM-INSTALL.md`
**Problem**: Doc says both "you must create .gitignore" AND "sets up all .gitignore files". Contradictory.
**Fix**: After implementing Issue 4 fix, update docs to say "Installer creates .gitignore files automatically"

#### Issue 7: init.sh Socket Path Fallback Mismatch
**Source**: Upgrade feedback Issue #10
**Files**: `init.sh` (socket path computation)
**Problem**: When AF_UNIX path is too long, Python daemon falls back to `/run/user/{uid}/` or `/tmp/`, but `init.sh` always computes the default path. Hook forwarders can't find daemon.
**Note**: This only affects deep project paths (>108 chars for full socket path). Plan 00046 added the Python-side fallback but didn't add matching logic to init.sh.
**Fix**: Two options:
  - (A) Add matching fallback logic to init.sh
  - (B) Have daemon write actual socket path to a discovery file that init.sh reads

  Option B is simpler and eliminates dual-computation. Daemon writes socket path to `untracked/daemon.socket-path` on startup; init.sh reads it if the default socket doesn't exist.

### P2 - Medium (Documentation/UX)

#### Issue 8: No "Installation Success Criteria" in Docs
**Source**: Install feedback Issue #7
**Files**: `CLAUDE/LLM-INSTALL.md`
**Fix**: Add "Installation Success Criteria" section listing what success looks like

#### Issue 9: Restart Claude Code Not Prominently Documented
**Source**: Upgrade feedback Issue #9
**Files**: `CLAUDE/LLM-UPDATE.md`
**Fix**: Make "Restart Claude Code" a numbered step (not a footnote exception) for multi-version upgrades

#### Issue 10: Project-Level Handlers Template Directory Confusion
**Source**: v2.10.0 upgrade feedback Issue 3
**Files**: Documentation
**Fix**: Add note in upgrade docs explaining `.claude/` inside daemon repo is intentional for project-level handler templates, NOT a nested installation

## Tasks

### Phase 1: P0 Fixes (Config Template)

- [ ] **Task 1.1**: Remove `stats_cache_reader` handler entry from `.claude/hooks-daemon.yaml.example`
- [ ] **Task 1.2**: Remove orphaned `get_acceptance_tests()` from `stats_cache_reader.py` (lines 118-133)
- [ ] **Task 1.3**: Remove `STATS_CACHE_READER` from `HandlerID` enum and `VALID_STATUS_LINE_HANDLER_KEYS`
- [ ] **Task 1.4**: Assign unique priorities to ALL handlers in `.claude/hooks-daemon.yaml.example` (no duplicates within event types)
- [ ] **Task 1.5**: Run QA: `./scripts/qa/run_all.sh`
- [ ] **Task 1.6**: Restart daemon and verify no DEGRADED MODE

### Phase 2: P1 Fixes (Installer/UX)

- [ ] **Task 2.1**: Add `ensure_claude_gitignore()` to `scripts/install/gitignore.sh` that auto-creates `.claude/.gitignore`
- [ ] **Task 2.2**: Update `setup_all_gitignores()` to call `ensure_claude_gitignore()` before verification
- [ ] **Task 2.3**: Make `.gitignore` warnings non-fatal in `install_version.sh` (don't propagate exit code 1)
- [ ] **Task 2.4**: Set `UV_LINK_MODE=copy` in `scripts/install/venv.sh` before uv commands
- [ ] **Task 2.5**: Run QA: `./scripts/qa/run_all.sh`

### Phase 3: P1 Fix (Socket Path Discovery)

- [ ] **Task 3.1**: Write daemon socket path to discovery file on startup (`untracked/daemon.socket-path`)
  - File in `src/claude_code_hooks_daemon/daemon/server.py` or startup logic
- [ ] **Task 3.2**: Update `init.sh` to read discovery file when default socket doesn't exist
- [ ] **Task 3.3**: Write TDD tests for socket path discovery
- [ ] **Task 3.4**: Run QA: `./scripts/qa/run_all.sh`
- [ ] **Task 3.5**: Test with deep path scenario

### Phase 4: Documentation Updates

- [ ] **Task 4.1**: Fix conflicting .gitignore language in `CLAUDE/LLM-INSTALL.md`
- [ ] **Task 4.2**: Add "Installation Success Criteria" section to `CLAUDE/LLM-INSTALL.md`
- [ ] **Task 4.3**: Make "Restart Claude Code" a prominent numbered step in `CLAUDE/LLM-UPDATE.md`
- [ ] **Task 4.4**: Add note about `.claude/` template directory in upgrade docs
- [ ] **Task 4.5**: Review all docs for consistency with implemented fixes

### Phase 5: Verification

- [ ] **Task 5.1**: Full QA: `./scripts/qa/run_all.sh`
- [ ] **Task 5.2**: Daemon restart verification
- [ ] **Task 5.3**: Verify `.claude/hooks-daemon.yaml.example` loads without warnings
- [ ] **Task 5.4**: Checkpoint commit

## Dependencies

- None (standalone plan)

## Success Criteria

- [ ] Fresh install using `.claude/hooks-daemon.yaml.example` produces NO degraded mode warnings
- [ ] Zero duplicate priority warnings on daemon start
- [ ] Installer exits 0 on successful install
- [ ] `.claude/.gitignore` auto-created during install
- [ ] No UV hardlink warning in containers
- [ ] Documentation is consistent (no contradictions)
- [ ] All QA checks pass
- [ ] Daemon restarts successfully

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Removing HandlerID constant breaks imports | High | Low | Grep for all references before removing |
| Priority reassignment changes handler ordering | Medium | Medium | Only change example config, not live dogfood config |
| Socket discovery file not cleaned up | Low | Low | Daemon already manages PID files similarly |

## Notes & Updates

### 2026-02-11
- Plan created from three user feedback reports
- Verified stats_cache_reader.py is utility module, not handler class
- Confirmed 18+ duplicate priorities in yaml.example
- Confirmed .claude/.gitignore not auto-created (only verified)
- Confirmed UV_LINK_MODE not set anywhere
