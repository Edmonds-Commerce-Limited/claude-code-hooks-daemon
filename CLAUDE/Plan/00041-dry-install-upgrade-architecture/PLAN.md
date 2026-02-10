# Plan 00041: DRY Install/Upgrade Architecture Refactoring

**Status**: In Progress
**Created**: 2026-02-10
**Owner**: Claude Sonnet 4.5
**Priority**: High
**Estimated Effort**: 5-7 days

## Overview

Refactor the install and upgrade scripts to eliminate code duplication, implement modular architecture with version-specific sub-scripts, and add robust config preservation and rollback capabilities. This addresses the architectural debt where install and upgrade paths have diverged significantly, leading to maintenance burden and inconsistent behavior.

The refactoring implements a two-layer architecture: stable curl-fetched entry scripts (Layer 1) that delegate to version-specific modular sub-scripts (Layer 2). Upgrade will follow the philosophy "Upgrade = Clean Reinstall + Config Preservation", ensuring every upgrade produces the same clean state as a fresh installation while preserving only user customizations.

## Goals

- Eliminate ALL code duplication between install and upgrade paths (achieve DRY principle)
- Implement modular shared library components for common operations
- Add robust config preservation with diff/merge/validate for custom user settings
- Implement full state rollback capability (code, config, hooks, venv, gitignore)
- Reduce entry script complexity (target: under 100 lines each)
- Maintain backward compatibility with older tags via feature detection
- Ensure upgrade produces identical clean state to fresh install

## Non-Goals

- Rewriting the entire installation system from scratch (refactor incrementally)
- Changing the user-facing installation commands or URLs
- Supporting self-install mode improvements (self-install is development-only, not for clients)
- Backward compatibility for tags older than v2.0 (focus on recent versions)
- GUI or interactive installation workflows

## CRITICAL CONSTRAINTS

### Install/Upgrade Scripts Must ABORT in Self-Install Mode

**ABSOLUTE REQUIREMENT**: `install.sh` and `upgrade.sh` have NO BUSINESS operating in self-install mode. They must detect and ABORT immediately.

**Why**: Self-install mode is the daemon's development repository. The daemon is already "installed" as the repository itself. Running install/upgrade would:
- Break the development environment
- Create circular symlinks (hooks pointing to themselves)
- Corrupt the git state
- Damage the working codebase

**What to do instead**:
- Update code: `git pull`
- Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
- Test install: Create dummy project in `/tmp` and install there

**Implementation**:
- `scripts/install/mode_guard.sh` provides `ensure_normal_mode_only()`
- Both `install.sh` and `upgrade.sh` MUST call this function at startup
- Function detects self-install mode and aborts with clear error message
- Testing must use `/tmp` dummy projects, NEVER the live daemon repo

## Context & Background

### Current State (Code Duplication)

The codebase has significant duplication between install and upgrade:

| Component | Install Location | Upgrade Location | Duplication Type |
|-----------|------------------|------------------|------------------|
| Prerequisites | `install.sh` lines 73-108 | `upgrade.sh` (partial) | Different implementations |
| Project detection | `install.sh` lines 114-146 + `install.py` lines 166-195 | `upgrade.sh` lines 120-133 | Three separate implementations |
| Venv management | `install.sh` lines 218-241 (uv sync) | `upgrade.sh` lines 330-343 (pip install -e) | Inconsistent tooling |
| Hook deployment | `install.py` lines 217-312 (Python templates) | `upgrade.sh` lines 380-408 (file copy) | Completely different approaches |
| Config handling | `install.py` lines 583-748 (inline template) | None (backup only) | No merge/migration |
| Gitignore management | `install.sh` lines 189-213 + `install.py` lines 1040-1135 | Missing entirely | Critical gap |
| Daemon lifecycle | Both scripts | Different error handling | Inconsistent |
| Slash commands | `install.py` lines 427-458 | `upgrade.sh` lines 353-376 | Duplicated logic |
| Validation | `install.py` via ClientInstallValidator | `upgrade.sh` via inline heredoc Python | Duplicated |

**Total duplication**: ~800 lines of duplicated or divergent logic across 3 files (install.sh, install.py, upgrade.sh)

### Architecture Gaps

1. **Config Preservation**: Currently only backs up config, no merge or migration. Custom handler settings, priorities, and plugin configs are lost on upgrade.

2. **Rollback Limitations**: Only git checkout + config restore. Missing: venv state, hook scripts, gitignore, settings.json.

3. **No Version-Specific Scripts**: All install logic in current tag means Layer 1 can't evolve independently of Layer 2.

4. **Gitignore Drift**: Install checks/fixes gitignore, upgrade doesn't. Users can end up with incorrect .gitignore after upgrades.

### User's Vision

**Two-Layer Architecture**:
- Layer 1 (curl-fetched, stable): Minimal logic, always from `main` branch
- Layer 2 (versioned per tag): Complete install/upgrade logic, lives in each tag

**Upgrade Philosophy**: "Clean reinstall + config preservation" means replace ALL code, ALL default files, recreate venv from scratch, preserve ONLY custom config.

## Tasks

### Phase 1: Shared Library Modules (`scripts/install/`)

- [x] **Task 1.1**: Create `scripts/install/output.sh`
  - [x] Extract colour output functions from install.sh and upgrade.sh
  - [x] Add terminal detection for colour support
  - [x] Single source of truth for logging and output formatting
  - [x] Write tests (bats framework + manual test script)

- [x] **Task 1.2**: Create `scripts/install/prerequisites.sh`
  - [x] Extract git/python3/uv prerequisite checks
  - [x] Unified `check_all_prerequisites()` function
  - [x] Version validation for python3 (3.11+)
  - [x] Write tests (manual test script)

- [x] **Task 1.3**: Create `scripts/install/project_detection.sh`
  - [x] Extract and unify `detect_project_root()` logic
  - [x] Extract `validate_project_root()` checks
  - [x] Add `detect_install_mode()` (self-install detection)
  - [x] Single function returning project root + mode
  - [x] Write tests (manual test script)

- [x] **Task 1.4**: Create `scripts/install/venv.sh`
  - [x] Standardize on uv for venv management
  - [x] Implement `create_venv()` (fresh install)
  - [x] Implement `recreate_venv()` (delete + create for upgrade)
  - [x] Implement `verify_venv()` (import check)
  - [x] Implement `install_package_editable()` (bonus)
  - [x] Write tests (manual test script)

- [x] **Task 1.5**: Create `scripts/install/daemon_control.sh`
  - [x] Extract daemon lifecycle patterns
  - [x] Implement `stop_daemon_safe()`, `start_daemon_safe()`, `restart_daemon_verified()`
  - [x] Status check with output capture
  - [x] Additional functions: `check_daemon_running()`, `wait_for_daemon_stop()`, `restart_daemon_quick()`
  - [x] Write tests (manual test script)

- [x] **Task 1.6**: Create `scripts/install/hooks_deploy.sh`
  - [x] Unify hook script deployment (replace Python templates AND file copy)
  - [x] Source of truth: actual hook scripts in `.claude/hooks/` directory
  - [x] Implement `deploy_hook_scripts()`, `deploy_init_script()`, `set_executable_permissions()`
  - [x] Handle git core.fileMode=false case
  - [x] CRITICAL FIX: Never create symlinks for hooks, always copy
  - [x] CRITICAL FIX: Skip deployment in self-install when source=target (prevents circular symlinks)
  - [x] Write tests (manual test script)

- [x] **Task 1.7**: Create `scripts/install/gitignore.sh`
  - [x] Unify root `.gitignore` and `.claude/.gitignore` handling
  - [x] Implement `ensure_root_gitignore()`, `verify_claude_gitignore()`, `show_gitignore_instructions()`
  - [x] Additional functions: `create_daemon_untracked_gitignore()`, `verify_gitignore_complete()`, `setup_all_gitignores()`
  - [x] Content validation (not just existence)
  - [x] Write tests (manual test script)

- [x] **Task 1.8**: Create `scripts/install/config_preserve.sh`
  - [x] Implement `backup_config()` (timestamped backup)
  - [x] Implement `extract_custom_config()` (calls Python differ)
  - [x] Implement `merge_custom_config()` (calls Python merger)
  - [x] Implement `validate_merged_config()` (calls Python validator)
  - [x] Implement `report_incompatibilities()` (user guidance)
  - [x] Implement `preserve_config_for_upgrade()` (high-level workflow)
  - [x] Integration tested with Python CLI

- [x] **Task 1.9**: Create `scripts/install/validation.sh`
  - [x] Wrap ClientInstallValidator calls
  - [x] Implement `run_pre_install_checks()`, `run_post_install_checks()`
  - [x] Additional functions: `cleanup_stale_runtime_files()`, `verify_config_valid()`
  - [x] Standardized error reporting
  - [x] Write tests (manual test script)

- [x] **Task 1.10**: Create `scripts/install/rollback.sh`
  - [x] Implement `create_state_snapshot()` (config, settings, hooks, gitignore, version, git ref)
  - [x] Implement `restore_state_snapshot()` (atomic restoration)
  - [x] Implement `list_snapshots()`, `cleanup_old_snapshots()`
  - [x] Additional functions: `get_latest_snapshot()`, `get_snapshot_dir()`
  - [x] Define snapshot directory structure and manifest format (JSON manifest + files/)
  - [x] Snapshot location: `{daemon_dir}/untracked/upgrade-snapshots/{timestamp}/`

- [x] **Task 1.11**: Create `scripts/install/slash_commands.sh`
  - [x] Extract slash command deployment logic
  - [x] Implement `deploy_slash_commands()` (copy or symlink based on mode)
  - [x] Additional functions: `verify_slash_commands_deployed()`, `list_slash_commands()`, `remove_slash_command()`, `deploy_single_slash_command()`
  - [x] Write tests (manual test script)

- [x] **Task 1.12**: Create `scripts/install/mode_guard.sh`
  - [x] CRITICAL: Implement self-install mode detection and abort
  - [x] Implement `detect_self_install_mode()` (checks for daemon repo indicators)
  - [x] Implement `ensure_normal_mode_only()` (aborts script if self-install detected)
  - [x] Clear error message explaining why install/upgrade can't run in self-install mode
  - [x] Must be called at start of install.sh and upgrade.sh

- [x] **Task 1.13**: Create `scripts/install/test_helpers.sh`
  - [x] Test infrastructure for creating dummy projects in /tmp
  - [x] Implement `create_test_project()` (normal and self-install modes)
  - [x] Implement `create_test_daemon_dir()` (minimal daemon structure with hooks)
  - [x] Implement `cleanup_test_project()` (safe removal with guards)
  - [x] Implement `run_test_with_cleanup()` (automatic cleanup on success/failure)
  - [x] Implement `create_test_config()`, `verify_test_structure()`
  - [x] Safety guards: only remove /tmp/hooks_daemon_test_* directories

**Phase 1 Status**: 14/14 tasks complete (100%) ✅ (Task 1.8 completed with Phase 3)

### Phase 2: Config Preservation Engine (Python)

- [ ] **Task 2.1**: Create `src/claude_code_hooks_daemon/install/config_differ.py`
  - [ ] Write failing tests for config diff extraction
  - [ ] Implement `ConfigDiffer` class
  - [ ] Compare two YAML configs (user vs version example)
  - [ ] Output structured diff (added handlers, changed priorities, custom options, plugins)
  - [ ] Handle nested dict comparison
  - [ ] Refactor and verify 95%+ coverage

- [ ] **Task 2.2**: Create `src/claude_code_hooks_daemon/install/config_merger.py`
  - [ ] Write failing tests for config merge
  - [ ] Implement `ConfigMerger` class
  - [ ] Apply diff onto new default config
  - [ ] Handle conflicts (removed handlers, renamed options)
  - [ ] Output merged config + conflict list
  - [ ] Refactor and verify 95%+ coverage

- [ ] **Task 2.3**: Create `src/claude_code_hooks_daemon/install/config_validator.py`
  - [ ] Write failing tests for validation
  - [ ] Use Pydantic `Config.model_validate()` to validate merged config
  - [ ] Return structured result (valid/invalid + field errors)
  - [ ] Generate user-friendly guidance for incompatibilities
  - [ ] Refactor and verify 95%+ coverage

- [ ] **Task 2.4**: Create CLI entry points for config operations
  - [ ] Add `config-diff` command to daemon CLI
  - [ ] Add `config-merge` command to daemon CLI
  - [ ] Add `config-validate` command to daemon CLI
  - [ ] Write tests for CLI interface
  - [ ] Integration with `scripts/install/config_preserve.sh`

### Phase 3: Layer 2 Front Controllers

- [x] **Task 3.1**: Create `scripts/install_version.sh`
  - [x] Source all `scripts/install/*.sh` modules
  - [x] Orchestrate fresh install workflow (11 steps)
  - [x] Steps: safety checks → prerequisites → venv → hooks → settings.json → env → config → gitignore → slash commands → daemon start → validation
  - [x] Replace logic currently in install.sh + install.py
  - [x] Includes generate_settings_json() fallback for older daemon versions
  - [x] Syntax validated, daemon restart verified

- [x] **Task 3.2**: Create `scripts/upgrade_version.sh`
  - [x] Source all `scripts/install/*.sh` modules
  - [x] Orchestrate upgrade workflow (15 steps)
  - [x] Steps: safety → pre-checks → snapshot → stop daemon → config backup → checkout → recreate venv → redeploy hooks → settings.json → config preserve/merge → gitignore → slash commands → restart → post-validation → cleanup
  - [x] Implement "Upgrade = Clean Reinstall + Config Preservation" philosophy
  - [x] Full rollback trap with snapshot restore on failure
  - [x] Syntax validated, daemon restart verified

### Phase 4: Layer 1 Simplification

- [ ] **Task 4.1**: Simplify `install.sh` to minimal Layer 1
  - [ ] Only: validate prerequisites → determine version/tag → clone repo → handoff to `scripts/install_version.sh`
  - [ ] Feature detection: check for `scripts/install_version.sh`, fall back to legacy `install.py` if missing
  - [ ] Target: under 100 lines (from 308)
  - [ ] Write tests
  - [ ] Run QA

- [ ] **Task 4.2**: Simplify `scripts/upgrade.sh` to minimal Layer 1
  - [ ] Only: validate prerequisites → detect project → fetch tags → determine version → handoff to `scripts/upgrade_version.sh`
  - [ ] Feature detection: check for `scripts/upgrade_version.sh`, fall back to legacy inline logic if missing
  - [ ] Target: under 100 lines (from 612)
  - [ ] Write tests
  - [ ] Run QA

### Phase 5: install.py Migration

- [ ] **Task 5.1**: Move hook script generation to bash templates
  - [ ] Create `scripts/templates/` directory for hook script templates
  - [ ] Move forwarder script generation from Python strings to template files
  - [ ] Update `scripts/install/hooks_deploy.sh` to use templates
  - [ ] Write tests
  - [ ] Run QA

- [ ] **Task 5.2**: Move settings.json generation to template
  - [ ] Create `scripts/templates/settings.json`
  - [ ] Update `scripts/install/hooks_deploy.sh` to use template
  - [ ] Write tests
  - [ ] Run QA

- [ ] **Task 5.3**: Make `.example` config the single source of truth
  - [ ] Ensure `.claude/hooks-daemon.yaml.example` is complete
  - [ ] Update install to copy example instead of generating inline
  - [ ] Write tests
  - [ ] Run QA

- [ ] **Task 5.4**: Deprecate or reduce `install.py` to thin shim
  - [ ] Add deprecation notice pointing to `install.sh` + `scripts/install_version.sh`
  - [ ] Optionally: reduce to thin wrapper that calls bash scripts
  - [ ] Retain Python modules in `src/claude_code_hooks_daemon/install/` (ClientInstallValidator, config differ/merger)
  - [ ] Write tests
  - [ ] Run QA

### Phase 6: Rollback Enhancement

- [ ] **Task 6.1**: Implement state snapshot format
  - [ ] Write failing tests for snapshot creation
  - [ ] Define snapshot directory structure: `.claude/hooks-daemon/untracked/upgrade-snapshots/{timestamp}/`
  - [ ] Define manifest.json format (file list, checksums, metadata)
  - [ ] Implement `create_state_snapshot()` in `scripts/install/rollback.sh`
  - [ ] Refactor and verify tests pass

- [ ] **Task 6.2**: Implement state restoration
  - [ ] Write failing tests for restore scenarios
  - [ ] Implement `restore_state_snapshot()` (atomic restore of all state)
  - [ ] Venv recreation after code rollback
  - [ ] Daemon restart verification after rollback
  - [ ] Refactor and verify tests pass

- [ ] **Task 6.3**: Integrate rollback into upgrade flow
  - [ ] Update `scripts/upgrade_version.sh` to create snapshot before changes
  - [ ] Add automatic rollback on failure (any step)
  - [ ] Point-of-no-return detection and handling
  - [ ] Write tests for rollback triggers
  - [ ] Run QA

### Phase 7: Testing

- [ ] **Task 7.1**: Unit tests for config differ/merger/validator
  - [ ] Write tests for all merge scenarios (TDD)
  - [ ] Edge cases: empty configs, missing sections, conflicts
  - [ ] Schema evolution scenarios (renamed fields, removed handlers)
  - [ ] Verify 95%+ coverage
  - [ ] Run QA

- [ ] **Task 7.2**: Integration tests for bash library modules
  - [ ] Install bats (Bash Automated Testing System)
  - [ ] Write tests for each `scripts/install/*.sh` module
  - [ ] Test on clean directory structure
  - [ ] Verify all modules work in isolation
  - [ ] Run QA

- [ ] **Task 7.3**: End-to-end upgrade path tests
  - [ ] Simulate v2.5 to v2.6 upgrade
  - [ ] Test config preservation across upgrade
  - [ ] Test rollback after failed upgrade
  - [ ] Test fresh install from scratch
  - [ ] Run QA for each scenario

- [ ] **Task 7.4**: Full QA verification
  - [ ] Run complete QA suite: `./scripts/qa/run_all.sh`
  - [ ] Verify daemon restart after install
  - [ ] Verify daemon restart after upgrade
  - [ ] Verify coverage maintained at 95%+
  - [ ] Fix any issues

### Phase 8: Documentation

- [ ] **Task 8.1**: Update `CLAUDE/LLM-INSTALL.md`
  - [ ] Document new architecture (Layer 1 + Layer 2)
  - [ ] Update installation workflow
  - [ ] Update troubleshooting section
  - [ ] Add modular library module reference

- [ ] **Task 8.2**: Update `CLAUDE/LLM-UPDATE.md`
  - [ ] Document new upgrade flow
  - [ ] Explain config preservation mechanism
  - [ ] Document rollback capabilities
  - [ ] Add upgrade troubleshooting

- [ ] **Task 8.3**: Update `CLAUDE/UPGRADES/README.md`
  - [ ] Document state snapshot system
  - [ ] Document rollback procedure
  - [ ] Add manual rollback instructions

- [ ] **Task 8.4**: Create `scripts/install/README.md`
  - [ ] Document all library modules
  - [ ] Function signatures and usage
  - [ ] Examples for each module
  - [ ] Maintenance guidelines

## Dependencies

- **No external plan dependencies**: Plans 00032 and 00034 are independent
- **Internal dependencies**:
  - Phase 2 (Python config engine) must complete before Phase 3 (front controllers)
  - Phase 1 (shared lib) must complete before Phases 3 and 4
  - Phase 5 (install.py migration) depends on Phase 3 completion
  - Phase 6 (rollback) can proceed in parallel with Phases 3-5

## Technical Decisions

### Decision 1: Bash vs Python for Layer 2

**Context**: Layer 2 scripts orchestrate multiple operations (git, venv, file copy, daemon control). Language choice impacts maintainability and error handling.

**Options Considered**:
1. Pure bash - Consistent with Layer 1, simple dependency chain
2. Pure Python - Better error handling, can use existing Pydantic models
3. Hybrid - Bash orchestration + Python for config operations

**Decision**: Option 3 (Hybrid)

**Rationale**: Config preservation requires structured YAML comparison (natural in Python, fragile in bash). Orchestration (stop daemon, copy files, restart) is natural in bash. This matches existing pattern in `upgrade.sh` (bash calls Python for validation).

**Date**: 2026-02-10

### Decision 2: Config Diff Strategy

**Context**: How to identify "custom" vs "default" config settings to preserve during upgrade.

**Options Considered**:
1. Key-based diff against version example config
2. Comment-based markers (user adds `# CUSTOM` comments)
3. Separate user override file (user config contains only overrides)

**Decision**: Option 1 (Key-based diff against example config)

**Rationale**: Option 2 requires user discipline (unreliable). Option 3 is a breaking change. Option 1 works transparently by comparing user config vs `.claude/hooks-daemon.yaml.example` from their current version.

**Date**: 2026-02-10

### Decision 3: Venv Strategy on Upgrade

**Context**: Should upgrade update existing venv or recreate from scratch?

**Options Considered**:
1. `pip install -e .` into existing venv (current approach)
2. Delete and recreate venv with `uv sync`
3. Create new venv alongside old, swap atomically

**Decision**: Option 2 (Delete and recreate)

**Rationale**: Per user's vision: "Recreate venv from scratch." Eliminates stale .pth files, Python version mismatches, orphaned packages. `uv sync` is fast enough (seconds) to make this practical. Aligns with "upgrade = clean reinstall" philosophy.

**Date**: 2026-02-10

### Decision 4: Forward Compatibility for Layer 1

**Context**: Layer 1 (curl-fetched from `main`) must work with any version's Layer 2 scripts. How to handle version differences?

**Options Considered**:
1. Feature detection: check if `scripts/install_version.sh` exists, fall back to `install.py`
2. Version flag file: each tag has `scripts/.layer2` marker
3. Minimum version: Layer 1 only supports tags >= minimum version

**Decision**: Option 1 (Feature detection)

**Rationale**: Provides full backward compatibility. Older tags (pre-refactoring) still work with no coordination required. Simple to implement and understand.

**Date**: 2026-02-10

### Decision 5: Snapshot Storage Location

**Context**: Where to store upgrade state snapshots for rollback.

**Options Considered**:
1. `.claude/hooks-daemon/untracked/upgrade-snapshots/`
2. `/tmp/hooks-daemon-snapshots/`
3. `.claude/upgrade-snapshots/`

**Decision**: Option 1 (Daemon untracked directory)

**Rationale**: Option 2 violates security policy (no `/tmp` usage per B108). Option 3 pollutes project `.claude/` directory. Option 1 follows existing pattern for runtime files, already gitignored.

**Date**: 2026-02-10

## Success Criteria

- [ ] `install.sh` reduced to under 100 lines (from 308)
- [ ] `scripts/upgrade.sh` reduced to under 100 lines (from 612)
- [ ] Zero code duplication between install and upgrade paths
- [ ] Config preservation works: custom handler settings, priorities, plugins survive upgrade
- [ ] Config incompatibilities reported with clear user guidance
- [ ] Full state rollback restores: code, config, hooks, settings.json, gitignore
- [ ] All QA checks pass: `./scripts/qa/run_all.sh`
- [ ] Daemon restarts successfully after fresh install
- [ ] Daemon restarts successfully after upgrade
- [ ] Backward compatibility: old tags still installable via feature detection
- [ ] 95%+ test coverage maintained for all new Python code

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Bash portability issues (macOS vs Linux) | Medium | Medium | Test on both platforms; use POSIX-compatible constructs; avoid bashisms |
| Config merge produces invalid YAML | High | Low | Pydantic validation gate; user approval before applying merged config |
| Old tags lack Layer 2 scripts | Medium | Certain | Feature detection fallback in Layer 1 to legacy `install.py` path |
| Venv recreation breaks on network issues | Medium | Low | Retain old venv until new one verified; atomic swap pattern |
| Snapshot storage grows unbounded | Low | Medium | Auto-cleanup: keep last 3 snapshots; document manual cleanup procedure |
| Breaking change confuses users | Medium | Low | Deprecation period: support both old and new paths for 2 minor versions |
| Bash modules not testable | Medium | Low | Use bats framework; write comprehensive integration tests |
| Config schema evolution unhandled | High | Medium | ConfigValidator detects schema mismatches; guide user to manual fixes |

## Timeline

- **Phase 1**: 2 days (shared library modules)
- **Phase 2**: 1.5 days (config preservation Python)
- **Phase 3**: 1 day (Layer 2 front controllers)
- **Phase 4**: 0.5 days (Layer 1 simplification)
- **Phase 5**: 1 day (install.py migration)
- **Phase 6**: 1 day (rollback enhancement)
- **Phase 7**: 1.5 days (comprehensive testing)
- **Phase 8**: 0.5 days (documentation)
- **Target Completion**: 2026-02-19 (9 days from start)

## Notes & Updates

### 2026-02-10
- Plan created by Opus agent based on detailed research of current install/upgrade architecture
- Identified ~800 lines of duplication across 3 files
- Key insight: Config preservation requires diff against version-specific example config
- Critical files for implementation:
  - `/workspace/install.py` (1334 lines) - Core install logic to refactor
  - `/workspace/scripts/upgrade.sh` (612 lines) - Core upgrade logic to refactor
  - `/workspace/src/claude_code_hooks_daemon/config/models.py` - Pydantic config models
  - `/workspace/src/claude_code_hooks_daemon/install/client_validator.py` - Validation infrastructure
  - `/workspace/init.sh` - Runtime init script patterns
- **Phase 1 Status**: ✅ COMPLETE (13/13 modules - 100%)
  - ✅ Task 1.1: output.sh (color output, logging)
  - ✅ Task 1.2: prerequisites.sh (git, python3, uv checking)
  - ✅ Task 1.3: project_detection.sh (project root, mode detection)
  - ✅ Task 1.4: venv.sh (create, recreate, verify venv with uv)
  - ✅ Task 1.5: daemon_control.sh (stop, start, restart, status checking)
  - ✅ Task 1.6: hooks_deploy.sh (hook script deployment) - **CRITICAL FIX APPLIED**
  - ✅ Task 1.7: gitignore.sh (.gitignore management)
  - ✅ Task 1.9: validation.sh (ClientInstallValidator wrapper)
  - ✅ Task 1.10: rollback.sh (state snapshots, restoration)
  - ✅ Task 1.11: slash_commands.sh (slash command deployment)
  - ✅ Task 1.12: mode_guard.sh (self-install abort protection) - **NEW**
  - ✅ Task 1.13: test_helpers.sh (dummy project infrastructure) - **NEW**
  - ⬜ Task 1.8: config_preserve.sh (blocked - needs Phase 2 Python modules first)
- **CRITICAL INCIDENT**: Broke daemon by creating circular symlinks during testing
  - Root cause: Ran install scripts against live daemon repo (self-install mode)
  - Impact: All hooks broken, daemon non-functional
  - Fix: Restored hooks from git, fixed hooks_deploy.sh to never symlink hooks
  - Prevention: Created mode_guard.sh to abort install/upgrade in self-install mode
  - Lesson: **NEVER test install/upgrade against the daemon repo itself**
  - Solution: Created test_helpers.sh for safe /tmp dummy project testing
- **Key Architectural Decisions from Incident**:
  - Install/upgrade scripts MUST abort in self-install mode (no exceptions)
  - Hooks are NEVER deployed as symlinks (always copied)
  - In self-install mode, skip hook deployment when source=target
  - All testing must use /tmp dummy projects via test_helpers.sh
