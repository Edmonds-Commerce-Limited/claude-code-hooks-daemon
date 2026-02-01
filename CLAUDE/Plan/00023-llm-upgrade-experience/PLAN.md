# Plan 00023: LLM Upgrade Experience Improvements

**Status**: Not Started
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
4. **Error Loop** - "🛑 CRITICAL: STOP work immediately" caused investigation instead of proceeding with fix

## Tasks

### Phase 1: Location Detection Script
- [ ] ⬜ Create `scripts/detect_location.sh` that identifies current directory context
- [ ] ⬜ Script outputs one of: "project_root", "hooks_daemon_dir", "wrong_location"
- [ ] ⬜ Add usage examples to LLM-UPDATE.md
- [ ] ⬜ Test script from various directories

### Phase 2: Self-Locating Upgrade Script
- [ ] ⬜ Create `.claude/hooks-daemon/scripts/upgrade.sh`
- [ ] ⬜ Script auto-detects project root by walking up to find `.claude/hooks-daemon/`
- [ ] ⬜ Implements complete upgrade workflow:
  - [ ] ⬜ Backup current config
  - [ ] ⬜ Git fetch and checkout latest tag
  - [ ] ⬜ Pip install
  - [ ] ⬜ Daemon restart
  - [ ] ⬜ Status verification
- [ ] ⬜ Add error handling and rollback on failure
- [ ] ⬜ Make script executable and test from various directories

### Phase 3: LLM-UPDATE.md Improvements
- [ ] ⬜ Add "CRITICAL: Determine Your Location First" section with detection command
- [ ] ⬜ Provide single copy-paste command blocks for each location scenario
- [ ] ⬜ Update primary recommendation to use upgrade script
- [ ] ⬜ Add troubleshooting section for common errors
- [ ] ⬜ Include examples of expected vs actual output

### Phase 4: Error Message Improvements
- [ ] ⬜ Review all daemon error messages for upgrade context
- [ ] ⬜ Update "PROTECTION NOT ACTIVE" errors to distinguish upgrade vs runtime scenarios:
  - Upgrade context: "This is expected during upgrade. Continue with upgrade steps."
  - Runtime context: "Run daemon restart command"
- [ ] ⬜ Remove "🛑 CRITICAL: STOP work" language during known-safe scenarios
- [ ] ⬜ Add context-aware messaging in hook forwarders

### Phase 5: Nested .claude Conflicts Prevention
- [ ] ⬜ Research options:
  1. Add `.claude/hooks-daemon/` to repo's own `.gitignore`
  2. Rename dev setup to `.claude-dev/`
  3. Improve daemon's project root detection logic
- [ ] ⬜ Decide on approach and document rationale
- [ ] ⬜ Implement chosen solution
- [ ] ⬜ Test nested installation detection still works correctly
- [ ] ⬜ Update SELF_INSTALL.md if needed

### Phase 6: Testing & Documentation
- [ ] ⬜ Test upgrade script from clean installation
- [ ] ⬜ Test upgrade script from nested location
- [ ] ⬜ Test upgrade script with simulated failures (rollback)
- [ ] ⬜ Verify error messages in upgrade vs runtime contexts
- [ ] ⬜ Update RELEASES/v2.5.0.md with upgrade improvements
- [ ] ⬜ Add troubleshooting section to README.md

### Phase 7: Integration & QA
- [ ] ⬜ Run full QA suite: `./scripts/qa/run_all.sh`
- [ ] ⬜ Fix any issues found
- [ ] ⬜ Verify all checks pass
- [ ] ⬜ Update GitHub Issue #16 with implementation summary

## Technical Decisions

### Decision 1: Upgrade Script Location
**Context**: Where should the upgrade script live?
**Options Considered**:
1. `.claude/hooks-daemon/scripts/upgrade.sh` - Colocated with daemon
2. `.claude/hooks-daemon/upgrade.sh` - Root of daemon install
3. Root project scripts/ - Separate from daemon

**Decision**: Option 1 (`.claude/hooks-daemon/scripts/upgrade.sh`)
**Rationale**:
- Colocated with other daemon scripts
- Part of daemon repository (versioned with code)
- Clear organizational structure
**Date**: 2026-02-01

### Decision 2: Nested .claude Handling
**Context**: Hooks-daemon repo contains own `.claude/` for development, conflicts when installed
**Options Considered**:
1. Gitignore nested installations (`.claude/hooks-daemon/`)
2. Rename development dir to `.claude-dev/`
3. Improve daemon detection logic

**Decision**: TBD during implementation (Phase 5)
**Rationale**: Need to test trade-offs and ensure detection still works correctly

## Success Criteria

- [ ] Location detection script correctly identifies all three scenarios
- [ ] Upgrade script successfully upgrades from any valid location
- [ ] Upgrade script handles failures and provides rollback
- [ ] LLM-UPDATE.md provides clear, copy-paste instructions
- [ ] Error messages distinguish upgrade vs runtime contexts
- [ ] Nested .claude conflicts resolved
- [ ] All QA checks pass
- [ ] Documentation updated

## Dependencies

- None - standalone improvement

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Upgrade script breaks existing workflows | High | Low | Thorough testing, maintain manual process docs |
| Detection logic false positives | Medium | Medium | Conservative detection, clear error messages |
| Error message changes confuse users | Medium | Low | A/B test with examples, gather feedback |

## Notes & Updates

### 2026-02-01
- Plan created based on Issue #16 detailed analysis
- Prioritized as High due to impact on LLM developer experience
