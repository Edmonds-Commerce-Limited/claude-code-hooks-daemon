# Plan 00061: Hooks Daemon User-Facing Skill

**Status**: Not Started
**Created**: 2026-02-17
**Owner**: AI Agent
**Priority**: High
**Recommended Executor**: Sonnet | Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Implement a user-facing `/hooks-daemon` skill that gets deployed to user projects during daemon installation. The skill provides daemon management commands (upgrade, health check, project handler development) through a single skill with argument-driven subcommands.

**Key Insight**: Installation skill makes no sense (chicken-and-egg problem). Users install via `scripts/install.sh`, THEN the skill becomes available for post-installation operations.

## Goals

- Deploy `/hooks-daemon` skill to user projects during installation
- Implement subcommands: upgrade, health, dev-handlers, logs
- Provide clear, actionable error messages for daemon issues
- Fix v2.13.0 breaking change: better error messages for abstract method violations in plugin handlers
- Follow Claude Code skill system conventions (single skill with routing)

## Non-Goals

- Installation skill (impossible - need daemon to provide skills)
- Skills for every minor operation (use subcommands instead)
- Automated upgrades without user approval
- Skills in this project's `.claude/skills/` (these are for DEPLOYMENT to user projects)

## Context & Background

**User Feedback (v2.13.0 upgrade):**
> The `get_acceptance_tests()` becoming abstract is a silent breaking change for plugin handler authors. The upgrade completed successfully and the daemon even reported running, but the plugin handlers failed to load with a Python "Can't instantiate abstract class" error — only visible in the restart output, not flagged during the upgrade itself.

**Problem**: Generic Python errors instead of clear, version-aware guidance like the DEGRADED MODE messages provide.

**Solution**: Enhanced error detection and user-friendly messages for plugin load failures.

## Tasks

### Phase 1: Skill Structure Design

- [ ] Create skill directory structure in daemon source
  - [ ] `src/claude_code_hooks_daemon/skills/hooks-daemon/SKILL.md`
  - [ ] `src/claude_code_hooks_daemon/skills/hooks-daemon/upgrade.md`
  - [ ] `src/claude_code_hooks_daemon/skills/hooks-daemon/health.md`
  - [ ] `src/claude_code_hooks_daemon/skills/hooks-daemon/dev-handlers.md`
  - [ ] `src/claude_code_hooks_daemon/skills/hooks-daemon/references/troubleshooting.md`

- [ ] Create skill scripts
  - [ ] `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/upgrade.sh`
  - [ ] `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/health-check.sh`
  - [ ] `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/init-handlers.sh`
  - [ ] `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/daemon-cli.sh`

### Phase 2: Skill Deployment System

- [ ] **Write failing tests** for skill deployment logic
  - [ ] Test skill files copied to user `.claude/skills/hooks-daemon/`
  - [ ] Test skill scripts are executable
  - [ ] Test version alignment (daemon version matches skill version)
  - [ ] Test upgrade refreshes skill files

- [ ] **Implement skill deployment** (TDD)
  - [ ] Create `src/claude_code_hooks_daemon/install/skills.py`
  - [ ] Add `deploy_skills()` function
  - [ ] Integrate with installer (`scripts/install.sh`)
  - [ ] Add to upgrade workflow

- [ ] **Run QA suite**: `./scripts/qa/run_all.sh`

- [ ] **Verify daemon loads**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`

### Phase 3: Main Skill Implementation (SKILL.md)

- [ ] **Write main skill frontmatter**
  - [ ] `name: hooks-daemon`
  - [ ] `argument-hint: "[upgrade|health|dev-handlers|logs] [args...]"`
  - [ ] `disable-model-invocation: true`
  - [ ] `allowed-tools: Bash, Read, Write, Edit`

- [ ] **Write skill router logic**
  - [ ] Parse `$ARGUMENTS` for subcommand
  - [ ] Route to appropriate script or documentation
  - [ ] Provide usage examples for each subcommand

- [ ] **Test skill invocation** (manual)
  - [ ] Install daemon in test project
  - [ ] Verify `/hooks-daemon` appears in skill list
  - [ ] Test each subcommand invocation

### Phase 4: Upgrade Subcommand

- [ ] **Write upgrade.md documentation**
  - [ ] Quick upgrade: `/hooks-daemon upgrade`
  - [ ] Specific version: `/hooks-daemon upgrade 2.14.0`
  - [ ] Upgrade process steps
  - [ ] Rollback instructions

- [ ] **Write failing tests** for upgrade.sh
  - [ ] Test version detection
  - [ ] Test backup creation
  - [ ] Test rollback on failure
  - [ ] Test skill file refresh

- [ ] **Implement upgrade.sh** (TDD)
  - [ ] Validate current daemon state
  - [ ] Backup current installation
  - [ ] Download new version
  - [ ] Verify new daemon starts
  - [ ] Refresh skill files
  - [ ] Rollback on failure

- [ ] **Run QA**: `./scripts/qa/run_all.sh`

### Phase 5: Health Check Subcommand

- [ ] **Write health.md documentation**
  - [ ] Quick status: `/hooks-daemon health`
  - [ ] View logs: `/hooks-daemon logs`
  - [ ] Stream logs: `/hooks-daemon logs --follow`
  - [ ] Troubleshooting guide link

- [ ] **Write failing tests** for health-check.sh
  - [ ] Test daemon running detection
  - [ ] Test handler load status
  - [ ] Test config validation
  - [ ] Test degraded mode detection

- [ ] **Implement health-check.sh** (TDD)
  - [ ] Check daemon status (running/stopped)
  - [ ] Check handler load counts
  - [ ] Detect DEGRADED MODE
  - [ ] Check config file validity
  - [ ] Display recent errors from logs

- [ ] **Run QA**: `./scripts/qa/run_all.sh`

### Phase 6: Project Handler Development Subcommand

- [ ] **Write dev-handlers.md documentation**
  - [ ] Scaffold handler: `/hooks-daemon dev-handlers`
  - [ ] Handler template structure
  - [ ] Testing workflow
  - [ ] Registration instructions

- [ ] **Write failing tests** for init-handlers.sh
  - [ ] Test handler scaffolding
  - [ ] Test creates handler + test files
  - [ ] Test registers in config
  - [ ] Test provides TDD instructions

- [ ] **Implement init-handlers.sh** (TDD)
  - [ ] Prompt for handler details (name, event type, priority)
  - [ ] Create `.claude/project-handlers/{event_type}/handler.py`
  - [ ] Create co-located test file
  - [ ] Generate boilerplate with TDD structure
  - [ ] Add to `.claude/hooks-daemon.yaml`
  - [ ] Display next steps (write tests, implement)

- [ ] **Run QA**: `./scripts/qa/run_all.sh`

### Phase 7: Enhanced Error Messages (v2.13.0 Breaking Change Fix)

- [ ] **Write failing tests** for plugin load error detection
  - [ ] Test detects abstract method violations
  - [ ] Test detects `get_acceptance_tests()` missing
  - [ ] Test provides version-aware guidance
  - [ ] Test matches DEGRADED MODE clarity

- [ ] **Implement enhanced error messages** (TDD)
  - [ ] Create `src/claude_code_hooks_daemon/utils/error_formatter.py`
  - [ ] Detect "Can't instantiate abstract class" errors
  - [ ] Parse missing method name from traceback
  - [ ] Map method to version that made it mandatory
  - [ ] Format user-friendly error with fix instructions
  - [ ] Reference HANDLER_DEVELOPMENT.md

- [ ] **Integrate with daemon startup**
  - [ ] Catch plugin load exceptions
  - [ ] Format with enhanced error messages
  - [ ] Display before DEGRADED MODE message
  - [ ] Log to daemon logs

- [ ] **Run QA**: `./scripts/qa/run_all.sh`
- [ ] **Verify daemon loads**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`

### Phase 8: Documentation & Testing

- [ ] **Update CLAUDE/HANDLER_DEVELOPMENT.md**
  - [ ] Document `get_acceptance_tests()` requirement
  - [ ] Provide implementation examples
  - [ ] Link from error messages

- [ ] **Create troubleshooting.md**
  - [ ] Common upgrade issues
  - [ ] Plugin load failures
  - [ ] DEGRADED MODE recovery
  - [ ] Abstract method violations

- [ ] **Add acceptance tests** to handlers
  - [ ] Skill deployment verification
  - [ ] Upgrade script functionality
  - [ ] Health check accuracy
  - [ ] Error message clarity

- [ ] **Integration testing**
  - [ ] Test full install → upgrade → health → dev-handlers flow
  - [ ] Test in fresh project (no prior daemon)
  - [ ] Test upgrade from v2.13.0 with broken plugin handler
  - [ ] Verify error messages match design

- [ ] **Run full QA**: `./scripts/qa/run_all.sh`

### Phase 9: Complete

- [ ] **Update README.md**
  - [ ] Document `/hooks-daemon` skill availability
  - [ ] Link to skill documentation

- [ ] **Update CHANGELOG.md**
  - [ ] Add skill deployment feature
  - [ ] Note breaking change fix

- [ ] **Update version** (if minor/patch release)

- [ ] **Mark plan complete**
  - [ ] Update status to Complete
  - [ ] Move to Completed/
  - [ ] Update README.md

## Dependencies

- Requires understanding of Claude Code skill system (completed via claude-code-guide agent)
- No blocking dependencies on other plans

## Technical Decisions

### Decision 1: Single Skill vs Multiple Skills
**Context**: Need to provide daemon management to users
**Options Considered**:
1. Multiple skills: `/hooks-daemon-upgrade`, `/hooks-daemon-health`, etc.
2. Single skill with subcommands: `/hooks-daemon upgrade`, `/hooks-daemon health`

**Decision**: Single skill with subcommands (Option 2)
**Rationale**:
- Cleaner namespace (one skill instead of 3+)
- Mirrors existing pattern (`.claude/skills/release/` uses arguments)
- More discoverable for users
- Related operations belong together
**Date**: 2026-02-17

### Decision 2: Where to Store Skill Files
**Context**: Skills need to be deployed to user projects
**Options Considered**:
1. Store in `.claude/skills/` in daemon repo
2. Store in `src/claude_code_hooks_daemon/skills/` for packaging
3. Download skills separately during installation

**Decision**: Store in `src/` and package with daemon (Option 2)
**Rationale**:
- Version alignment (daemon version = skill version)
- No external dependencies during install
- Skills are part of daemon distribution
- Easier to test and maintain
**Date**: 2026-02-17

### Decision 3: Manual vs Automatic Invocation
**Context**: Should Claude auto-invoke daemon management commands?
**Options Considered**:
1. Allow automatic invocation
2. Require manual invocation only (`disable-model-invocation: true`)

**Decision**: Manual invocation only (Option 2)
**Rationale**:
- Upgrades are critical operations requiring user approval
- Parallels `/release` skill pattern
- Prevents accidental daemon modifications
- Health checks are diagnostic, not automatic
**Date**: 2026-02-17

## Success Criteria

- [ ] Daemon installs skill to `.claude/skills/hooks-daemon/` in user projects
- [ ] `/hooks-daemon upgrade` successfully upgrades daemon version
- [ ] `/hooks-daemon health` displays accurate daemon status
- [ ] `/hooks-daemon dev-handlers` scaffolds project handler with tests
- [ ] Plugin load errors show clear, actionable messages (not raw Python exceptions)
- [ ] All acceptance tests pass
- [ ] All QA checks pass
- [ ] Documentation updated

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Skill deployment breaks existing installations | High | Low | Test on fresh project + upgrade path |
| Breaking change fix doesn't catch all errors | Medium | Medium | Comprehensive error testing with real plugin failures |
| Users confused by subcommand syntax | Low | Medium | Clear documentation + examples in SKILL.md |
| Upgrade script fails and corrupts installation | High | Low | Backup before upgrade, rollback on failure |

## Timeline

- Phase 1-2: Skill structure + deployment (1-2 hours)
- Phase 3: Main skill implementation (30 mins)
- Phase 4: Upgrade subcommand (1-2 hours)
- Phase 5: Health check subcommand (1 hour)
- Phase 6: Dev handlers subcommand (1 hour)
- Phase 7: Enhanced error messages (1-2 hours)
- Phase 8: Documentation + testing (1 hour)
- Phase 9: Complete (30 mins)

Target Completion: Same day

## Notes & Updates

### 2026-02-17
- Plan created based on claude-code-guide agent design
- User feedback incorporated: v2.13.0 breaking change requires better error messages
- Clarified that installation skill makes no sense (chicken-and-egg problem)
