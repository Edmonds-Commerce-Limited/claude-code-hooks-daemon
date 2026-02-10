# Plan 00041: Project-Level Handlers - First-Class Developer Experience

**Created**: 2026-02-10
**Status**: In Progress
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

- [✓] Create feature branch from latest main
- [✓] Phase 1: Core Infrastructure
- [ ] Phase 2: Developer Experience CLI
- [ ] Phase 3: Documentation & Examples
- [ ] Phase 4: Dogfooding & Refinement
- [ ] Phase 5: Release

## Implementation Phases

### Phase 1: Core Infrastructure

**Goal**: Convention-based project handler loading with config support

#### Tasks

- [✓] **Create config models** (TDD)
  - [✓] Add `ProjectHandlersConfig` to `config/models.py`
  - [✓] Add `project_handlers` field to root `Config` model
  - [✓] Schema: `enabled`, `path`, `handlers_config`
  - [✓] Write tests for config validation
  - [✓] Verify config loads from YAML correctly

- [✓] **Create ProjectHandlerLoader** (TDD)
  - [✓] New file: `src/handlers/project_loader.py`
  - [✓] Implement `discover_handlers(path: Path) -> list[Handler]`
  - [✓] Use `importlib.util.spec_from_file_location` (same as PluginLoader)
  - [✓] Walk event-type subdirectories (pre_tool_use/, post_tool_use/, etc.)
  - [✓] Skip files starting with `_` or `test_`
  - [✓] Write comprehensive unit tests (95%+ coverage)

- [✓] **Integrate with DaemonController** (TDD)
  - [✓] Add `_load_project_handlers()` method
  - [✓] Call after built-in handlers and legacy plugins in `initialise()`
  - [✓] Pass project_handlers config and workspace_root
  - [✓] Register loaded handlers with EventRouter
  - [✓] Write integration tests for loading pipeline

- [✓] **Conflict Detection** (TDD)
  - [✓] Check for handler_id conflicts with built-in handlers
  - [✓] Check for priority collisions (log warnings)
  - [✓] Prefer built-in handlers on conflict (log warning)
  - [✓] Write tests for conflict scenarios

- [✓] **Run full QA**: `./scripts/qa/run_all.sh`
- [ ] **Verify daemon restarts**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`

### Phase 2: Developer Experience CLI

**Goal**: Scaffolding, validation, and test running commands

#### Tasks

- [ ] **Create `init-project-handlers` command** (TDD)
  - [ ] New file: `src/daemon/commands/init_project_handlers.py`
  - [ ] Create `.claude/project-handlers/` structure
  - [ ] Generate `__init__.py` files
  - [ ] Create `conftest.py` with standard fixtures
  - [ ] Create example handler with test
  - [ ] Update `hooks-daemon.yaml` if missing `project_handlers` section
  - [ ] Write tests for scaffolding generation

- [ ] **Create `validate-project-handlers` command** (TDD)
  - [ ] New file: `src/daemon/commands/validate_project_handlers.py`
  - [ ] Discover project handlers without loading daemon
  - [ ] Attempt to import and instantiate each handler
  - [ ] Verify subclasses `Handler`
  - [ ] Verify `get_acceptance_tests()` returns tests
  - [ ] Check for conflicts with built-in handlers
  - [ ] Output formatted report
  - [ ] Write tests for validation logic

- [ ] **Create `test-project-handlers` command** (TDD)
  - [ ] New file: `src/daemon/commands/test_project_handlers.py`
  - [ ] Run pytest on `.claude/project-handlers/` directory
  - [ ] Pass correct `--import-mode=importlib`
  - [ ] Capture and display output
  - [ ] Write tests for test runner

- [ ] **Update playbook generator** (TDD)
  - [ ] Modify `src/daemon/playbook_generator.py`
  - [ ] Include project handler acceptance tests in output
  - [ ] Section header: "Project Handlers"
  - [ ] Write tests for playbook with project handlers

- [ ] **Wire CLI subcommands**
  - [ ] Add commands to `src/daemon/cli.py`
  - [ ] Add help text and examples
  - [ ] Test CLI invocation

- [ ] **Run full QA**: `./scripts/qa/run_all.sh`
- [ ] **Verify daemon restarts**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`

### Phase 3: Documentation & Examples

**Goal**: Comprehensive documentation for LLM and human developers

#### Tasks

- [ ] **Create PROJECT_HANDLERS.md**
  - [ ] Location: `CLAUDE/PROJECT_HANDLERS.md`
  - [ ] Overview and motivation
  - [ ] Quick start guide
  - [ ] Directory structure conventions
  - [ ] Handler development guide
  - [ ] Testing best practices
  - [ ] Common patterns and examples
  - [ ] Troubleshooting section
  - [ ] CLI reference

- [ ] **Update ARCHITECTURE.md**
  - [ ] Add "Project Handler Loading" section
  - [ ] Document discovery mechanism
  - [ ] Document config schema
  - [ ] Update loading pipeline diagram

- [ ] **Update HANDLER_DEVELOPMENT.md**
  - [ ] Add "Project-Level Handlers" section
  - [ ] Differences from built-in handlers
  - [ ] Testing with daemon infrastructure
  - [ ] Acceptance testing integration

- [ ] **Create example handlers**
  - [ ] Location: `examples/project-handlers/`
  - [ ] Example 1: Vendor changes reminder (PreToolUse, advisory)
  - [ ] Example 2: Branch naming enforcer (SessionStart, blocking)
  - [ ] Example 3: Build asset checker (PostToolUse, advisory)
  - [ ] Each with complete tests and documentation
  - [ ] README.md explaining examples

- [ ] **Update CLAUDE.md**
  - [ ] Add "Project-Level Handlers" section
  - [ ] Quick reference for LLM agents
  - [ ] Links to detailed docs

### Phase 4: Dogfooding & Refinement

**Goal**: Use project handlers in real projects, fix issues discovered

#### Tasks

- [ ] **Create handlers in checkout project** (see Plan 006 in checkout repo)
  - [ ] Vendor changes reminder
  - [ ] Build asset watcher
  - [ ] Composer lock sync reminder
  - [ ] Branch naming enforcer
  - [ ] Document all issues found

- [ ] **Iterate on DX**
  - [ ] Fix any issues discovered during dogfooding
  - [ ] Improve error messages
  - [ ] Enhance validation output
  - [ ] Improve scaffolding templates
  - [ ] Each fix follows TDD cycle

- [ ] **Acceptance testing**
  - [ ] Add project handler tests to PLAYBOOK.md
  - [ ] Execute playbook manually
  - [ ] Document results

- [ ] **Run full QA**: `./scripts/qa/run_all.sh`
- [ ] **Verify daemon restarts**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`

### Phase 5: Release

**Goal**: Prepare for release and announce feature

#### Tasks

- [ ] **Create migration guide**
  - [ ] Document upgrade path for existing plugin users
  - [ ] Comparison: old plugins vs new project-handlers
  - [ ] When to use each approach

- [ ] **Update CHANGELOG.md**
  - [ ] Add entry for project-handlers feature
  - [ ] Breaking changes (if any)
  - [ ] New CLI commands

- [ ] **Update README.md**
  - [ ] Add "Project-Level Handlers" to features list
  - [ ] Link to PROJECT_HANDLERS.md

- [ ] **Final QA sweep**
  - [ ] Run full QA suite
  - [ ] Run acceptance playbook
  - [ ] Verify all examples work
  - [ ] Check all documentation links

- [ ] **Open PR**
  - [ ] Create PR from feature/project-handlers-dx to main
  - [ ] Reference this plan in PR description
  - [ ] Include before/after examples
  - [ ] Request review

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

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Breaking changes to existing plugin system | High | Low | Keep plugins working, add project-handlers alongside |
| Handler conflicts hard to debug | Medium | Medium | Clear validation output, good error messages |
| Test infrastructure complex | Medium | Low | Provide conftest.py template with fixtures |
| Documentation insufficient | High | Medium | Write docs while coding, dogfood immediately |

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
