# Plan 00046: Upgrade System Overhaul

**Status**: Not Started
**Created**: 2026-02-11
**Owner**: TBD
**Priority**: High
**Estimated Effort**: 6-10 hours

## Overview

Two real-world upgrade attempts (v2.3.0 and v2.4.0 to v2.9.0) exposed critical failures in the upgrade system. The root cause is a flawed Layer 1 script that checks for Layer 2 BEFORE checking out the target version, meaning any upgrade from a pre-Layer-2 version always falls into a broken legacy fallback path. Additional issues include missing Python version detection, AF_UNIX socket path length limits, missing config generation, and incomplete documentation.

**Design Decision**: Drop the legacy fallback strategy entirely. The upgrade flow becomes: checkout target version FIRST, THEN run Layer 2. If Layer 2 doesn't exist in the target (ancient version), that's an error - the user needs to install fresh.

## Source Feedback

Two production upgrade feedback reports are co-located in this plan folder:

- `feedback-prod-data-v2.3-to-v2.9.md` - External project, Fedora 42, Python 3.9, deep nested path (9 issues)
- `feedback-self-install-v2.4-to-v2.9.md` - Self-install mode dogfooding (7 issues)

## Goals

- Eliminate the broken legacy fallback path from Layer 1
- Fix checkout-then-delegate ordering so Layer 2 always runs
- Add Python version detection and compatible interpreter search
- Add AF_UNIX socket path length validation with automatic fallback
- Improve error messages for config validation failures
- Update LLM-UPDATE.md with missing documentation
- Ensure upgrade works for: no venv, no config, deep paths, old Python
- Fix nested installation problem: `.claude/` tracked in git causes nested path detection in normal installs

## Non-Goals

- Rewriting Layer 2 (it works correctly when it actually runs)
- Creating upgrade guides for every historical version pair
- Changing the config preservation pipeline (works when invoked)
- Supporting upgrades FROM versions that predate Layer 2 in their TARGET (ancient-to-ancient)

## Context & Background

### Root Cause Analysis

**Issue 7 from prod-data feedback is the ROOT CAUSE of most other issues.**

Current Layer 1 flow (BROKEN):
```
1. Detect project root
2. Check if Layer 2 script exists at CURRENT version   <-- BUG: checks BEFORE checkout
3. If exists: delegate to Layer 2
4. If not: legacy fallback (checkout, pip install, start) <-- BROKEN: no config, no venv creation, no hooks deploy
```

The fix is simple but the impact is massive:
```
1. Detect project root
2. Stop daemon (safe, best-effort)
3. Checkout target version                              <-- MOVED UP
4. Layer 2 script NOW EXISTS in the checked-out code
5. Delegate to Layer 2                                  <-- ALWAYS succeeds for any modern target
6. If Layer 2 missing: ERROR (target too old, use fresh install)
```

### Issue Inventory (Consolidated from Both Reports)

| # | Issue | Source | Severity | Phase |
|---|-------|--------|----------|-------|
| 1 | Layer 1 checks Layer 2 BEFORE checkout | Both | P0 | 1 |
| 2 | Legacy fallback is broken (no venv, no config, no hooks) | prod-data | P0 | 1 |
| 3 | No Python version detection (3.9 vs 3.11+ requirement) | prod-data | P0 | 2 |
| 4 | AF_UNIX socket path too long for deep paths | prod-data | P0 | 3 |
| 5 | No venv creation when missing | prod-data | P0 | 1 |
| 6 | Config not generated when missing | prod-data | P1 | 1 |
| 7 | Hook forwarders not deployed by legacy path | prod-data | P1 | 1 |
| 8 | settings.json not mentioned in upgrade docs | prod-data | P1 | 5 |
| 9 | Duplicate priority warnings (18 on startup) | prod-data | P2 | 4 |
| 10 | Silent failures (|| true swallows errors) | prod-data | P1 | 1 |
| 11 | Config validation errors not user-friendly | self-install | P1 | 4 |
| 12 | No Claude Code restart instruction in docs | prod-data | P1 | 5 |
| 13 | Self-install mode path duplication in socket path | self-install | P2 | 3 |
| 14 | LLM-UPDATE.md missing Python version requirement | prod-data | P1 | 5 |
| 15 | LLM-UPDATE.md missing socket path troubleshooting | prod-data | P1 | 5 |
| 16 | Plugin event_type breaking change not documented | self-install | P1 | 5 |

### Resolution Strategy

- **Issues 1, 2, 5, 6, 7, 10**: ALL resolved by fixing Layer 1 to checkout first, then delegate to Layer 2 (which already handles venv, config, hooks, settings.json). The legacy fallback is DELETED.
- **Issue 3**: Add Python version check to Layer 1 (pre-flight) and to Layer 2's venv.sh
- **Issue 4, 13**: Add socket path length validation in paths.py with XDG_RUNTIME_DIR / /run/user fallback
- **Issues 8, 12, 14, 15, 16**: Documentation updates to LLM-UPDATE.md
- **Issue 9**: Already fixed in Plan 00039 (handler config key consistency)
- **Issue 11**: Improve config validation error messages in daemon startup

## Tasks

### Phase 1: Fix Layer 1 Script (Root Cause - Issues 1, 2, 5, 6, 7, 10)

- [ ] **Task 1.1**: Rewrite upgrade.sh to checkout-first-then-delegate
  - [ ] Remove entire legacy fallback block (lines 117-147)
  - [ ] Move `git checkout` BEFORE Layer 2 check
  - [ ] Add best-effort daemon stop before checkout (using old venv if exists)
  - [ ] After checkout, check for Layer 2 and `exec` into it
  - [ ] If Layer 2 missing after checkout: error with "target version too old, use fresh install"
  - [ ] Add pre-flight Python version check (find python3.11+)
- [ ] **Task 1.2**: Add Python version detection function to Layer 1
  - [ ] Check `python3 --version` against minimum 3.11
  - [ ] Search for `python3.13`, `python3.12`, `python3.11` if default too old
  - [ ] Fail with clear message if no compatible Python found
  - [ ] Pass discovered Python path to Layer 2 via environment variable

### Phase 2: Add Python Version Detection to Layer 2 (Issue 3)

- [ ] **Task 2.1**: Update `scripts/install/venv.sh` with Python version checking
  - [ ] Add `find_compatible_python()` function
  - [ ] Check `HOOKS_DAEMON_PYTHON` env var first (set by Layer 1)
  - [ ] Fall back to searching PATH for python3.13/3.12/3.11
  - [ ] Pass to `uv` via `--python` flag or `UV_PYTHON` env var
  - [ ] Clear error message if no compatible Python found
- [ ] **Task 2.2**: Update `scripts/install/prerequisites.sh`
  - [ ] Add Python version to prerequisite checks
  - [ ] Report which Python will be used

### Phase 3: Fix Socket Path Length (Issues 4, 13)

- [ ] **Task 3.1**: Add path length validation to `paths.py`
  - [ ] Write failing tests for paths exceeding 104 chars (108 limit minus safety margin)
  - [ ] Implement length check in `get_socket_path()`
  - [ ] When too long: fall back to `$XDG_RUNTIME_DIR/hooks-daemon-{project-hash}.sock`
  - [ ] If no XDG_RUNTIME_DIR: use `/run/user/{uid}/hooks-daemon-{project-hash}.sock`
  - [ ] If neither available: use `/tmp/hooks-daemon-{project-hash}.sock` with logged warning
  - [ ] Apply same logic to `get_pid_path()` and `get_log_path()`
  - [ ] Log which path strategy was used
- [ ] **Task 3.2**: Fix self-install mode path duplication
  - [ ] Investigate duplicate `.claude/hooks-daemon/.claude/hooks-daemon/` in self-install
  - [ ] Write failing test reproducing the doubled path
  - [ ] Fix `ProjectContext.daemon_untracked_dir()` for self-install mode
- [ ] **Task 3.3**: Update error message when socket creation fails
  - [ ] Catch `OSError` for AF_UNIX path too long
  - [ ] Suggest `CLAUDE_HOOKS_SOCKET_PATH` override in error message
  - [ ] Document the 108-byte limit

### Phase 4: Improve Config Validation UX (Issues 9, 11)

- [ ] **Task 4.1**: Add user-friendly config validation error messages
  - [ ] Catch Pydantic `ValidationError` at daemon startup
  - [ ] For "Field required" on plugins: show before/after format example
  - [ ] For unknown fields: suggest closest valid field name
  - [ ] Include link to upgrade guide if version change detected
- [ ] **Task 4.2**: Verify duplicate priority warnings are resolved
  - [ ] Confirm Plan 00039 fix is in v2.9.0
  - [ ] If not: reduce duplicate priority warning to DEBUG level

### Phase 5: Documentation Updates (Issues 8, 12, 14, 15, 16)

- [ ] **Task 5.1**: Update LLM-UPDATE.md
  - [ ] Add Python 3.11+ requirement prominently in Prerequisites
  - [ ] Add socket path length troubleshooting section
  - [ ] Add settings.json coverage (what it is, how upgrade handles it)
  - [ ] Change "No Claude Code restart needed" to prominent restart instruction for multi-version upgrades
  - [ ] Remove references to legacy fallback (it no longer exists)
  - [ ] Add "broken install recovery" section
- [ ] **Task 5.2**: Update CLAUDE.md
  - [ ] Add Python 3.11+ requirement to Quick Commands or Overview
- [ ] **Task 5.3**: Add breaking changes documentation
  - [ ] Document plugin `event_type` requirement in upgrade notes
  - [ ] Add to release checklist: "If breaking config changes, create upgrade guide"

### Phase 6: Testing & Verification

- [ ] **Task 6.1**: Unit tests for paths.py changes
  - [ ] Test socket path length > 104 triggers fallback
  - [ ] Test XDG_RUNTIME_DIR usage
  - [ ] Test /run/user/{uid} fallback
  - [ ] Test /tmp fallback with warning
  - [ ] Test self-install mode path resolution
- [ ] **Task 6.2**: Integration test for upgrade.sh
  - [ ] Test checkout-first flow works
  - [ ] Test error when Layer 2 missing in target
  - [ ] Test Python version detection finds alternatives
- [ ] **Task 6.3**: Full QA suite
  - [ ] Run `./scripts/qa/run_all.sh`
  - [ ] Daemon restart verification
- [ ] **Task 6.4**: Manual upgrade test
  - [ ] Test upgrade from a pre-Layer-2 tag (e.g., v2.3.0) to current
  - [ ] Verify Layer 2 runs after checkout
  - [ ] Verify config preservation works

## Dependencies

- None (standalone improvement)

## Technical Decisions

### Decision 1: Drop Legacy Fallback Entirely
**Context**: Legacy fallback exists for upgrades from pre-Layer-2 versions
**Options Considered**:
1. Fix legacy fallback to handle venv/config/hooks/settings - lots of duplication with Layer 2
2. Drop legacy fallback, checkout first then always use Layer 2

**Decision**: Option 2. The legacy fallback duplicates Layer 2 poorly. By checking out the target first, Layer 2 is always available. If someone targets an ancient version without Layer 2, that's an error - use fresh install.
**Date**: 2026-02-11

### Decision 2: Socket Path Fallback Strategy
**Context**: AF_UNIX has 108-byte path limit, deep project paths can exceed this
**Options Considered**:
1. Always use /tmp (violates security policy)
2. Use XDG_RUNTIME_DIR > /run/user/{uid} > /tmp fallback chain
3. Require user to set env var manually

**Decision**: Option 2. XDG_RUNTIME_DIR is the standard for per-user runtime files. /run/user/{uid} is the common implementation. /tmp is last resort with a warning. This respects security policy while handling real-world paths.
**Date**: 2026-02-11

### Decision 3: Python Version Detection Location
**Context**: System python3 may be too old (3.9), but python3.11+ may be available
**Options Considered**:
1. Only check in Layer 2 (venv.sh)
2. Check in Layer 1 pre-flight AND Layer 2

**Decision**: Option 2. Layer 1 should fail fast with a clear message before touching anything. Layer 2 also checks for defense in depth.
**Date**: 2026-02-11

## Success Criteria

- [ ] Upgrade from v2.3.0 to latest works without manual intervention (Layer 2 runs)
- [ ] Upgrade on system with Python 3.9 default finds and uses Python 3.11+
- [ ] Upgrade in deeply nested project (>108 char socket path) works automatically
- [ ] Config validation errors show helpful messages with before/after examples
- [ ] LLM-UPDATE.md covers Python requirement, socket paths, settings.json, restart instruction
- [ ] All QA checks pass
- [ ] Legacy fallback code is deleted from upgrade.sh

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Removing legacy fallback breaks ancient→ancient upgrades | Low | Low | Those users should fresh install; error message explains this |
| XDG_RUNTIME_DIR not set on some systems | Medium | Medium | /run/user/{uid} fallback, then /tmp with warning |
| Python detection misses exotic interpreter names | Low | Low | Allow HOOKS_DAEMON_PYTHON env var override |

## Notes & Updates

### 2026-02-11
- Plan created from two production upgrade feedback reports
- User decision: drop legacy fallback entirely, checkout first then run Layer 2
