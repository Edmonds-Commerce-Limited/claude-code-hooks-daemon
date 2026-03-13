# Plan 00088: Hooks Daemon Install Bugs

**Status**: In Progress
**Created**: 2026-03-13
**Owner**: TBD
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A fresh install of the hooks daemon on a brand new repo (no remote origin, default settings) revealed 6 bugs ranging from critical to minor. The installer silently fails at Step 11, swallows daemon error output, has a version mismatch, displays misleading status line data, and provides no guidance on plan workflow or handler enablement.

These bugs affect the first-run experience for every new user. Fixing them turns a 30-minute manual post-install configuration into a smooth automated setup.

## Goals

- Fix all 6 bugs documented in BUGS.md
- Ensure installer fails fast with actionable messages when prereqs are not met
- Surface daemon error output when startup fails
- Fix version number mismatch between pyproject.toml and `__version__`
- Fix misleading effort level display in status line
- Add plan workflow bootstrapping to installer
- Add handler profile selection to installer

## Non-Goals

- Rewriting the installer from scratch
- Changing the daemon architecture
- Adding new handlers

## Context & Background

Full bug report with reproduction steps, root cause analysis, and suggested fixes: [BUGS.md](BUGS.md)

### Bug Summary

| Bug | Severity | Component | Description |
|-----|----------|-----------|-------------|
| 1 | Critical | install.sh | Prereq checks incomplete - no git remote origin validation |
| 2 | Major | install_version.sh | Daemon error output silenced at Step 11 |
| 3 | Minor | pyproject.toml / version.py | Version mismatch (uv reports 2.21.1, `__version__` reports 2.4.0) |
| 4 | Major | optimal_config_checker + model_context | Status line shows wrong effort level |
| 5 | Medium | installer | No plan workflow setup offered |
| 6 | Minor | installer | No handler profile selection |

## Tasks

### Phase 1: Critical & Major Fixes (Bugs 1, 2, 4)

- [x] **Task 1.1**: Add git remote origin check to installer prereqs (Bug 1) ✅
  - [x] Add `git remote get-url origin` check to install.sh Layer 1
  - [x] Add `check_git_remote_origin()` to prerequisites.sh (Layer 2)
  - [x] Add manual test to test_prerequisites_manual.sh
  - [x] Verify installer aborts cleanly before writing any files

- [x] **Task 1.2**: Surface daemon error output on startup failure (Bug 2) ✅
  - [x] Capture stderr/stdout from daemon start command in daemon_control.sh
  - [x] Print daemon error inline when exit code is non-zero
  - [x] Removed `2>/dev/null` that was swallowing actionable error messages

- [x] **Task 1.3**: Fix effort level display mismatch (Bug 4) ✅
  - [x] Investigated: no Claude Code runtime effort API exists
  - [x] Changed `_EFFORT_DEFAULT` from "medium" to "high" in model_context
  - [x] Daemon users expect high effort (optimal_config_checker enforces it)
  - [x] When effortLevel IS in settings, that explicit value is used as before

### Phase 2: Version & UX Improvements (Bugs 3, 5, 6)

- [x] **Task 2.1**: Fix version number mismatch (Bug 3) ✅
  - [x] Fixed: `__init__.py` now imports `__version__` from `version.py` (SSOT)
  - [x] Was hardcoded to "2.4.0" while version.py had "2.21.1"
  - [ ] Add version consistency check to QA suite (follow-up)

- [ ] **Task 2.2**: Add plan workflow setup to installer (Bug 5)
  - [ ] Add optional Step 12 to installer for plan workflow bootstrapping
  - [ ] Create CLAUDE/Plan/README.md template for new projects
  - [ ] Enable plan workflow handlers when user opts in
  - [ ] Handle existing CLAUDE/Plan/ directory detection

- [ ] **Task 2.3**: Add handler profile selection to installer (Bug 6)
  - [ ] Define handler profiles (Minimal, Recommended, Strict)
  - [ ] Add profile selection prompt to installer
  - [ ] Apply profile to hooks-daemon.yaml during install
  - [ ] Document profile differences

### Phase 3: Verification

- [ ] **Task 3.1**: End-to-end install test
  - [ ] Test fresh install on repo with no remote (should fail fast with clear message)
  - [ ] Test fresh install on repo with remote (should succeed fully)
  - [ ] Verify status line shows correct effort level
  - [ ] Verify plan workflow setup works
  - [ ] Run full QA: `./scripts/qa/run_all.sh`

## Dependencies

- None

## Success Criteria

- [ ] Fresh install on repo without remote: fails immediately with actionable message, zero files written
- [ ] Fresh install on repo with remote: daemon starts, status line accurate, plan workflow offered
- [ ] Version numbers consistent across all files
- [ ] All QA checks passing
- [ ] Daemon restart verification passes

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Installer changes break existing installs | High | Low | Test upgrade path from current version |
| No runtime effort API exists | Medium | High | Fall back to advisory-only approach |
| Handler profiles add maintenance burden | Low | Medium | Keep profiles simple, document clearly |

## Notes & Updates

### 2026-03-13
- Plan created from bug report discovered during fresh install testing
- Bug report moved from untracked/ to plan folder as BUGS.md
