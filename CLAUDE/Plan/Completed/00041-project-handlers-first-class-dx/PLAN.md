# Plan 00041: Project-Level Handlers - First-Class Developer Experience

**Created**: 2026-02-10
**Status**: Complete (2026-02-12)
**Priority**: High
**Branch**: feature/project-handlers-dx

## Required Reading

- @CLAUDE/PlanWorkflow.md
- @CLAUDE/ARCHITECTURE.md
- @CLAUDE/HANDLER_DEVELOPMENT.md
- @CLAUDE/CodeLifecycle/Features.md
- @./design-document.md (Opus research output)

## Overview

Implement first-class developer experience for project-level handler development. The hooks-daemon already has 90% of the infrastructure (PluginLoader, Handler ABC, dispatch pipeline). This plan adds the missing developer experience layer: convention-based discovery, scaffolding, validation, test infrastructure, and comprehensive documentation.

**Goal**: Make creating project-specific handlers as smooth and well-supported as developing built-in handlers.

## Progress

- [x] ✅ Create feature branch from latest main
- [x] ✅ Phase 1: Core Infrastructure
- [x] ✅ Phase 2: Developer Experience CLI
- [x] ✅ Phase 3: Documentation & Examples
- [x] ✅ Phase 4: Dogfooding & Refinement
- [x] ✅ Phase 5: Release

## Implementation Phases

### Phase 1: Core Infrastructure

**Goal**: Convention-based project handler loading with config support

#### Tasks

- [x] ✅ **Create config models** (TDD)

  - [x] ✅ Add `ProjectHandlersConfig` to `config/models.py`
  - [x] ✅ Add `project_handlers` field to root `Config` model
  - [x] ✅ Schema: `enabled`, `path`, `handlers_config`
  - [x] ✅ Write tests for config validation
  - [x] ✅ Verify config loads from YAML correctly

- [x] ✅ **Create ProjectHandlerLoader** (TDD)

  - [x] ✅ New file: `src/handlers/project_loader.py`
  - [x] ✅ Implement `discover_handlers(path: Path) -> list[Handler]`
  - [x] ✅ Use `importlib.util.spec_from_file_location` (same as PluginLoader)
  - [x] ✅ Walk event-type subdirectories (pre_tool_use/, post_tool_use/, etc.)
  - [x] ✅ Skip files starting with `_` or `test_`
  - [x] ✅ Write comprehensive unit tests (95%+ coverage)

- [x] ✅ **Integrate with DaemonController** (TDD)

  - [x] ✅ Add `_load_project_handlers()` method
  - [x] ✅ Call after built-in handlers and legacy plugins in `initialise()`
  - [x] ✅ Pass project_handlers config and workspace_root
  - [x] ✅ Register loaded handlers with EventRouter
  - [x] ✅ Write integration tests for loading pipeline

- [x] ✅ **Conflict Detection** (TDD)

  - [x] ✅ Check for handler_id conflicts with built-in handlers
  - [x] ✅ Check for priority collisions (log warnings)
  - [x] ✅ Prefer built-in handlers on conflict (log warning)
  - [x] ✅ Write tests for conflict scenarios

- [x] ✅ **Run full QA**: `./scripts/qa/run_all.sh` — All 7 checks passed, coverage 95.0%

- [x] ✅ **Verify daemon restarts**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`

### Phase 2: Developer Experience CLI

**Goal**: Scaffolding, validation, and test running commands

#### Tasks

- [x] ✅ **Create `init-project-handlers` command** (TDD)

  - [x] ✅ Implemented in `src/daemon/cli.py` (cmd_init_project_handlers)
  - [x] ✅ Create `.claude/project-handlers/` structure
  - [x] ✅ Generate event-type subdirectories
  - [x] ✅ Create `conftest.py` with standard fixtures
  - [x] ✅ Create example handler with test
  - [x] ✅ Update `hooks-daemon.yaml` if missing `project_handlers` section
  - [x] ✅ 9 tests in `tests/unit/daemon/test_cli_init_project_handlers.py`

- [x] ✅ **Create `validate-project-handlers` command** (TDD)

  - [x] ✅ Implemented in `src/daemon/cli.py` (cmd_validate_project_handlers)
  - [x] ✅ Discover project handlers via ProjectHandlerLoader
  - [x] ✅ Attempt to import and instantiate each handler
  - [x] ✅ Verify subclasses `Handler`
  - [x] ✅ Verify `get_acceptance_tests()` returns tests
  - [x] ✅ Output formatted report with counts per event type
  - [x] ✅ 7 tests in `tests/unit/daemon/test_cli_validate_project_handlers.py`

- [x] ✅ **Create `test-project-handlers` command** (TDD)

  - [x] ✅ Implemented in `src/daemon/cli.py` (cmd_test_project_handlers)
  - [x] ✅ Run pytest on `.claude/project-handlers/` directory
  - [x] ✅ Pass correct `--import-mode=importlib`
  - [x] ✅ Capture and display output
  - [x] ✅ 8 tests in `tests/unit/daemon/test_cli_test_project_handlers.py`

- [x] ✅ **Update playbook generator** (TDD)

  - [x] ✅ Modified `src/daemon/playbook_generator.py`
  - [x] ✅ Include project handler acceptance tests in output
  - [x] ✅ Section header: "## Project Handlers"
  - [x] ✅ 7 tests in `tests/unit/daemon/test_playbook_generator_project_handlers.py`

- [x] ✅ **Wire CLI subcommands**

  - [x] ✅ Added 3 subcommands to `src/daemon/cli.py` main()
  - [x] ✅ Added help text and examples
  - [x] ✅ Tests verify CLI invocation

- [x] ✅ **Run full QA**: `./scripts/qa/run_all.sh` — ALL CHECKS PASSED

- [x] ✅ **Verify daemon restarts**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart` — Status: RUNNING (PID 121279)

### Phase 3: Documentation & Examples

**Goal**: Comprehensive documentation for LLM and human developers

#### Tasks

- [x] ✅ **Create PROJECT_HANDLERS.md**

  - [x] ✅ Location: `CLAUDE/PROJECT_HANDLERS.md`
  - [x] ✅ Overview and motivation
  - [x] ✅ Quick start guide
  - [x] ✅ Directory structure conventions
  - [x] ✅ Handler development guide
  - [x] ✅ Testing best practices
  - [x] ✅ Common patterns and examples
  - [x] ✅ Troubleshooting section
  - [x] ✅ CLI reference

- [x] ✅ **Update ARCHITECTURE.md**

  - [x] ✅ Add "Project Handler Loading" section
  - [x] ✅ Document discovery mechanism
  - [x] ✅ Document config schema
  - [x] ✅ Update loading pipeline diagram

- [x] ✅ **Update HANDLER_DEVELOPMENT.md**

  - [x] ✅ Add "Project-Level Handlers" section
  - [x] ✅ Differences from built-in handlers
  - [x] ✅ Testing with daemon infrastructure
  - [x] ✅ Acceptance testing integration

- [x] ✅ **Create example handlers**

  - [x] ✅ Location: `examples/project-handlers/`
  - [x] ✅ Example 1: Vendor changes reminder (PreToolUse, advisory)
  - [x] ✅ Example 2: Branch naming enforcer (SessionStart, blocking)
  - [x] ✅ Example 3: Build asset checker (PostToolUse, advisory)
  - [x] ✅ Each with complete tests and documentation
  - [x] ✅ README.md explaining examples

- [x] ✅ **Update CLAUDE.md**

  - [x] ✅ Add "Project-Level Handlers" section
  - [x] ✅ Quick reference for LLM agents
  - [x] ✅ Links to detailed docs

### Phase 4: Dogfooding & Refinement

**Goal**: Use project handlers in real projects, fix issues discovered

#### Tasks

- [x] ✅ **Create handlers in checkout project** (see Plan 006 in checkout repo)

  - [x] ✅ Vendor changes reminder
  - [x] ✅ Build asset watcher
  - [x] ✅ Composer lock sync reminder
  - [x] ✅ Branch naming enforcer
  - [x] ✅ Document all issues found

- [x] ✅ **Iterate on DX**

  - [x] ✅ Fix any issues discovered during dogfooding
  - [x] ✅ Improve error messages
  - [x] ✅ Enhance validation output
  - [x] ✅ Improve scaffolding templates
  - [x] ✅ Each fix follows TDD cycle

- [x] ✅ **Acceptance testing**

  - [x] ✅ Add project handler tests to PLAYBOOK.md
  - [x] ✅ Execute playbook manually
  - [x] ✅ Document results

- [x] ✅ **Run full QA**: `./scripts/qa/run_all.sh`

- [x] ✅ **Verify daemon restarts**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`

### Phase 5: Release

**Goal**: Prepare for release and announce feature

#### Tasks

- [x] ✅ **Create migration guide**

  - [x] ✅ Document upgrade path for existing plugin users (in README.md migration note)
  - [x] ✅ Comparison: old plugins vs new project-handlers
  - [x] ✅ When to use each approach

- [x] ✅ **Update CHANGELOG.md**

  - [x] ✅ Entry added in v2.8.0 release (already shipped)
  - [x] ✅ No breaking changes (legacy plugins still work)
  - [x] ✅ New CLI commands documented

- [x] ✅ **Update README.md**

  - [x] ✅ Updated features list: "Project-level handlers" replaces "Plugin system"
  - [x] ✅ Updated "Creating Your Own" section with project-handlers workflow
  - [x] ✅ Added migration note from plugins to project-handlers
  - [x] ✅ Link to PROJECT_HANDLERS.md

- [x] ✅ **Final QA sweep**

  - [x] ✅ Run full QA suite - ALL 7 CHECKS PASSED
  - [x] ✅ Daemon restarts successfully
  - [x] ✅ All examples documented in examples/project-handlers/
  - [x] ✅ Documentation links verified

- [N/A] **Open PR** - Work merged directly to main (not on feature branch)

## Technical Decisions

### Decision 1: Convention-Based Auto-Discovery ✅

**Chosen**: Scan `.claude/project-handlers/` using same pattern as built-in handlers

**Rationale**:

- Mirrors built-in handler system exactly (one pattern to learn)
- Zero config for new handlers (just add .py file in right directory)
- Event-type subdirectories make event mapping unambiguous
- Auto-discovery with optional per-handler config override

**Alternatives Considered**:

- Explicit listing in config (too much friction)
- Entry-points based (overkill for project-level, better for distributable packages)

### Decision 2: Tests Co-Located with Handlers ✅

**Chosen**: `test_handler.py` alongside `handler.py` in same directory

**Rationale**:

- Reduces friction for TDD
- Easy to find tests for a handler
- Mirrors pytest conventions
- Simpler than separate test tree

### Decision 3: Use Daemon's Python Environment ✅

**Chosen**: Project handlers run in daemon's venv, tests use daemon's pytest

**Rationale**:

- Handlers already need to import from daemon package
- No additional environment management
- Consistent Python version and dependencies

## Success Criteria

- [ ] `init-project-handlers` creates working scaffolding
- [ ] `validate-project-handlers` catches all common errors
- [ ] `test-project-handlers` runs tests successfully
- [ ] Project handlers load and execute in daemon
- [ ] Acceptance tests include project handlers in playbook
- [ ] Full documentation written (PROJECT_HANDLERS.md, examples)
- [ ] Dogfooding in checkout project successful
- [ ] All QA checks pass
- [ ] Daemon restarts successfully with project handlers
- [ ] All tests passing (95%+ coverage)

## Testing Strategy

### Unit Testing (Phase 1-2)

- All new classes have comprehensive unit tests
- Mock filesystem operations where needed
- Test error conditions (invalid handlers, conflicts, etc.)
- 95%+ coverage maintained

### Integration Testing (Phase 1-2)

- Test full loading pipeline (config → discovery → registration → dispatch)
- Test with real project-handlers directory
- Test handler execution through EventRouter
- Test acceptance test collection

### Manual Testing (Phase 4)

- Actually use project handlers in checkout project
- Verify CLI commands work as documented
- Run acceptance playbook
- Test all example handlers

## Risks & Mitigations

| Risk                                       | Impact | Probability | Mitigation                                           |
| ------------------------------------------ | ------ | ----------- | ---------------------------------------------------- |
| Breaking changes to existing plugin system | High   | Low         | Keep plugins working, add project-handlers alongside |
| Handler conflicts hard to debug            | Medium | Medium      | Clear validation output, good error messages         |
| Test infrastructure complex                | Medium | Low         | Provide conftest.py template with fixtures           |
| Documentation insufficient                 | High   | Medium      | Write docs while coding, dogfood immediately         |

## Dependencies

**Internal**:

- Existing PluginLoader patterns
- Handler ABC and dispatch pipeline
- Config system

**External**:

- None (all Python stdlib or existing deps)

## Branch Strategy

1. Checkout main: `git checkout main`
2. Fetch latest: `git fetch origin && git pull origin main`
3. Create feature branch: `git checkout -b feature/project-handlers-dx`
4. Work through phases sequentially
5. Commit after each major milestone
6. Push regularly: `git push origin feature/project-handlers-dx`
7. Open PR when Phase 4 complete and dogfooding successful

## Next Steps

1. Create feature branch from main
2. Begin Phase 1: Core Infrastructure (config models, ProjectHandlerLoader)
3. Follow TDD strictly (red → green → refactor)
4. Run QA after each phase
5. Verify daemon restart after each phase
6. Move to Phase 2 only after Phase 1 complete

---

**Related Plans**:

- Plan 006 in checkout repo: Dogfooding project handlers

**Last Updated**: 2026-02-10
