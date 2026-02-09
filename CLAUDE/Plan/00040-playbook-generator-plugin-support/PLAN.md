# Plan 00040: Playbook Generator Plugin Support

**Status**: Not Started
**Created**: 2026-02-09
**Owner**: Unassigned
**Priority**: Medium

## Overview

The acceptance test playbook generator currently only includes library handlers from `src/claude_code_hooks_daemon/handlers/`, missing project-specific plugin handlers from `.claude/hooks/handlers/`.

This was discovered during Layer 3 QA for Plan 00038. The dogfooding_reminder plugin (SessionStart handler) has acceptance tests defined but they don't appear in the generated playbook.

## Goals

- Include plugin handlers in generated acceptance test playbooks
- Maintain backward compatibility with existing playbook generation
- Ensure plugins are properly validated and included in QA

## Non-Goals

- Changing plugin loader architecture (already works correctly)
- Modifying acceptance test format or structure
- Adding new acceptance test features

## Context & Background

**Current behavior**:
- `cli.py` line 905-906 only calls `HandlerRegistry().discover()` (library handlers)
- `PlaybookGenerator` only receives the registry, not plugins
- Plugin handlers are loaded separately by daemon but not by playbook generator

**Impact**:
- Plugin handlers with acceptance tests are not tested during Layer 3 QA
- Users must manually verify plugin handlers outside the playbook

**Root cause**:
The playbook generator was designed before the plugin system was fully separated from the library.

## Tasks

### Phase 1: TDD - Add failing tests

- [ ] **Task 1.1**: Read existing playbook generator tests
  - [ ] Understand current test structure
  - [ ] Identify where to add plugin tests

- [ ] **Task 1.2**: Write failing test for plugin inclusion
  - [ ] Test: generate_playbook with plugin configured should include plugin tests
  - [ ] Mock plugin handler with get_acceptance_tests()
  - [ ] Assert plugin tests appear in generated markdown
  - [ ] Run test: Should FAIL (plugins not included yet)

### Phase 2: Implementation

- [ ] **Task 2.1**: Modify cli.py cmd_generate_playbook()
  - [ ] After registry.discover(), load plugins
  - [ ] Call: `plugins = PluginLoader.load_from_plugins_config(config.plugins)`
  - [ ] Pass plugins to PlaybookGenerator constructor

- [ ] **Task 2.2**: Update PlaybookGenerator constructor
  - [ ] Add optional `plugins` parameter (default: empty list)
  - [ ] Store plugins alongside registry

- [ ] **Task 2.3**: Update PlaybookGenerator.generate_markdown()
  - [ ] After collecting tests from registry handlers
  - [ ] Iterate through plugin handlers
  - [ ] Call get_acceptance_tests() on each plugin
  - [ ] Add plugin tests to tests_by_handler list
  - [ ] Ensure proper sorting by priority (plugins + library together)

- [ ] **Task 2.4**: Verify tests now pass
  - [ ] Run failing test from Phase 1
  - [ ] Expected: Now PASS (plugins included)

### Phase 3: Integration Testing

- [ ] **Task 3.1**: Generate playbook with dogfooding plugin
  - [ ] Run: `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook`
  - [ ] Verify dogfooding_reminder appears in output
  - [ ] Verify test details are correct

- [ ] **Task 3.2**: Test with no plugins configured
  - [ ] Temporarily disable plugins in config
  - [ ] Generate playbook
  - [ ] Verify no errors, only library handlers shown

- [ ] **Task 3.3**: Test with disabled plugin
  - [ ] Set plugin enabled: false
  - [ ] Generate playbook
  - [ ] Verify plugin not included

### Phase 4: QA

- [ ] **Task 4.1**: Run full QA suite
  - [ ] `./scripts/qa/run_all.sh`
  - [ ] Expected: All 7 checks pass

- [ ] **Task 4.2**: Restart daemon verification
  - [ ] `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
  - [ ] `$PYTHON -m claude_code_hooks_daemon.daemon.cli status`
  - [ ] Expected: Status RUNNING

- [ ] **Task 4.3**: Manual verification
  - [ ] Generate playbook
  - [ ] Count handlers: Should be 71 (70 library + 1 dogfooding)
  - [ ] Verify dogfooding test appears with correct details

## Technical Decisions

### Decision 1: Where to load plugins
**Context**: Need to load plugins for playbook generation
**Options**:
1. In PlaybookGenerator (tightly coupled to plugin system)
2. In cli.py before calling PlaybookGenerator (cleaner separation)

**Decision**: Load in cli.py (Option 2)
**Rationale**:
- Keeps PlaybookGenerator focused on formatting
- cli.py already loads config, natural place for plugin loading
- Easier to test (can mock plugin list)

**Date**: 2026-02-09

### Decision 2: How to pass plugins
**Context**: PlaybookGenerator needs access to plugin handlers
**Options**:
1. Pass plugins as separate parameter
2. Merge plugins into registry
3. Create unified handler collection

**Decision**: Pass as separate parameter (Option 1)
**Rationale**:
- Maintains registry as library-only (cleaner architecture)
- Explicit separation of library vs plugin handlers
- Backward compatible (parameter optional)

**Date**: 2026-02-09

## Success Criteria

- [ ] Generated playbook includes plugin handlers with acceptance tests
- [ ] Dogfooding plugin appears in playbook with 1 test
- [ ] Backward compatible: works with no plugins configured
- [ ] Tests pass with 95%+ coverage
- [ ] All QA checks pass
- [ ] Daemon restarts successfully

## Files Modified

| File | Change |
|------|--------|
| `src/claude_code_hooks_daemon/daemon/cli.py` | Load plugins, pass to PlaybookGenerator |
| `src/claude_code_hooks_daemon/daemon/playbook_generator.py` | Accept plugins parameter, iterate plugins |
| `tests/unit/daemon/test_playbook_generator.py` | Add plugin inclusion tests |

## Dependencies

- Depends on: None (plugin system already complete)
- Blocks: None (nice-to-have improvement)

## Notes & Updates

### 2026-02-09
- Plan created after discovering issue during Plan 00038 Layer 3 QA
- Dogfooding plugin has acceptance tests but not in playbook
- Straightforward fix with clear scope
