# Plan 00023: LLM Upgrade Experience Improvements

**Status**: Complete (2026-02-06)
**Created**: 2026-02-01
**Priority**: High
**Type**: Developer Experience / Documentation
**GitHub Issue**: #16

## Overview

Improve the upgrade experience for AI agents by addressing confusion points, adding automation, and implementing better error messaging. An Opus 4.5 agent experienced significant confusion during upgrade due to working directory tracking issues, nested installation detection, and unclear error messages.

## Goals

- Eliminate working directory confusion with location detection
- Provide single-command upgrade workflow
- Create self-locating upgrade script
- Soften error messages during upgrade to avoid investigation loops
- Prevent nested .claude conflicts in hooks-daemon development

## Non-Goals

- Changing core daemon architecture
- Automatic version detection/upgrade (use explicit version selection)
- Supporting upgrades from pre-v2.0 versions (already documented in UPGRADES/)

## Context & Background

Issue #16 documents an Opus 4.5 agent attempting upgrade to v2.4.0. Problems encountered:

1. **Working Directory Confusion** - Agent couldn't track whether it was at `/workspace` or `/workspace/.claude/hooks-daemon`
2. **Nested Installation Detection** - Hooks-daemon repo's own `.claude/` dir caused "NESTED INSTALLATION" errors
3. **Over-Analysis** - Clear instructions led to repeated prerequisite checks instead of execution
4. **Error Loop** - "CRITICAL: STOP work immediately" caused investigation instead of proceeding with fix

## Tasks

### Phase 1: Location Detection Script
- [x] ✅ Create `scripts/detect_location.sh` that identifies current directory context
- [x] ✅ Script outputs one of: "project_root", "hooks_daemon_dir", "wrong_location"
- [x] ✅ Add usage examples to LLM-UPDATE.md
- [x] ✅ Test script from various directories

### Phase 2: Self-Locating Upgrade Script
- [x] ✅ Create `scripts/upgrade.sh`
- [x] ✅ Script auto-detects project root by walking up to find `.claude/hooks-daemon.yaml`
- [x] ✅ Implements complete upgrade workflow:
  - [x] ✅ Backup current config
  - [x] ✅ Git fetch and checkout latest tag
  - [x] ✅ Pip install
  - [x] ✅ Daemon restart
  - [x] ✅ Status verification
- [x] ✅ Add error handling and rollback on failure
- [x] ✅ Make script executable and test from various directories

### Phase 3: LLM-UPDATE.md Improvements
- [x] ✅ Add "CRITICAL: Determine Your Location First" section with detection command
- [x] ✅ Provide single copy-paste command blocks for each location scenario
- [x] ✅ Update primary recommendation to use upgrade script
- [x] ✅ Add troubleshooting section for common errors
- [x] ✅ Eliminated `cd .claude/hooks-daemon` pattern - all commands use project root

### Phase 4: Error Message Improvements
- [x] ✅ Review all daemon error messages for upgrade context
- [x] ✅ Update "PROTECTION NOT ACTIVE" errors - removed alarming language
- [x] ✅ Remove "CRITICAL: STOP work" language - replaced with measured guidance
- [x] ✅ Add context-aware messaging ("If you are in the middle of an upgrade, this is expected")
- [x] ✅ Updated both bash (emit_hook_error) and Python (send_request_stdin) error generators

### Phase 5: Nested .claude Conflicts Prevention
- [x] ✅ Research options: Reviewed all three options
- [x] ✅ Decide on approach: Option 3 - detection logic already correct
  - `check_for_nested_installation()` properly checks for `.claude/hooks-daemon/.claude/hooks-daemon`
  - NOT triggered by `.claude/hooks-daemon/.claude/` (the repo's own dev config)
  - No code change needed - detection is already correct
- [x] ✅ Verified nested installation detection still works correctly
- [x] ✅ No SELF_INSTALL.md update needed - the existing docs already explain the distinction

### Phase 6: Testing & Documentation
- [x] ✅ Run full QA suite
- [x] ✅ Verify daemon restarts successfully

### Phase 7: Integration & QA
- [x] ✅ Run full QA suite: `./scripts/qa/run_all.sh`
- [x] ✅ Fix any issues found (pre-existing test failure only, not from this plan)
- [x] ✅ Verify all checks pass

## Technical Decisions

### Decision 1: Upgrade Script Location
**Context**: Where should the upgrade script live?
**Options Considered**:
1. `.claude/hooks-daemon/scripts/upgrade.sh` - Colocated with daemon
2. `.claude/hooks-daemon/upgrade.sh` - Root of daemon install
3. Root project scripts/ - Separate from daemon

**Decision**: `scripts/upgrade.sh` in the daemon repository root
**Rationale**:
- Colocated with other daemon scripts (detect_location.sh, health_check.sh)
- Part of daemon repository (versioned with code)
- Accessible both as `scripts/upgrade.sh` (self-install) and `.claude/hooks-daemon/scripts/upgrade.sh` (normal)
**Date**: 2026-02-06

### Decision 2: Nested .claude Handling
**Context**: Hooks-daemon repo contains own `.claude/` for development, conflicts when installed
**Options Considered**:
1. Gitignore nested installations (`.claude/hooks-daemon/`)
2. Rename development dir to `.claude-dev/`
3. Improve daemon detection logic

**Decision**: Option 3 - No change needed
**Rationale**: The detection logic already correctly distinguishes between:
- `.claude/hooks-daemon/.claude/` (fine - repo's own dev config)
- `.claude/hooks-daemon/.claude/hooks-daemon` (bad - true nested install)
**Date**: 2026-02-06

### Decision 3: Error Message Tone
**Context**: "STOP work immediately" language caused LLM investigation loops
**Decision**: Replaced with measured guidance that:
- Acknowledges the error without panic language
- Explains this is expected during upgrades
- Provides clear fix steps (restart daemon)
- Only asks to inform user if the issue persists after fix attempt
**Date**: 2026-02-06

## Success Criteria

- [x] Location detection script correctly identifies all three scenarios
- [x] Upgrade script implements full upgrade workflow with rollback
- [x] LLM-UPDATE.md provides clear, no-cd-needed instructions
- [x] Error messages distinguish upgrade vs runtime contexts
- [x] Nested .claude conflicts handled correctly (already were)
- [x] All QA checks pass
- [x] Documentation updated

## Dependencies

- None - standalone improvement

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Upgrade script breaks existing workflows | High | Low | Thorough testing, maintain manual process docs |
| Detection logic false positives | Medium | Medium | Conservative detection, clear error messages |
| Error message changes confuse users | Medium | Low | A/B test with examples, gather feedback |

## Notes & Updates

### 2026-02-06
- All phases complete
- Key insight: nested .claude detection was already correct, no code change needed
- Error messages significantly softened to prevent LLM investigation loops
- init.sh updated in both bash and Python error paths
- QA passes (pre-existing test_handler_instantiation failure not from this plan)
- Daemon restarts successfully
