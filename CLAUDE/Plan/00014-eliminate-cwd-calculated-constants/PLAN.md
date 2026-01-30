# Plan 00014: Eliminate CWD, Implement Calculated Constants

**Status**: Not Started
**Created**: 2026-01-30
**Owner**: To be assigned
**Priority**: High (FAIL FAST violation, reliability issue)
**Estimated Effort**: 4-6 hours

## Overview

The codebase has 14 dynamic CWD calls (`Path.cwd()`, `os.getcwd()`) spread across handlers, utilities, and CLI code. CWD is inherently unreliable -- the daemon process's working directory could change or be deleted, and it conflates "where the process was started" with "where the project lives." The project root is already known at daemon startup (via `get_project_path()` in `cli.py` line 43), and is already passed to `DaemonController.initialise()` as `workspace_root` (line 289). However, many handlers bypass this and call `Path.cwd()` directly.

This plan eliminates all dynamic CWD lookups in favor of calculated constants determined once at daemon launch and made available to all handlers.

## Goals

- Eliminate ALL dynamic `Path.cwd()` and `os.getcwd()` calls from handler and core code
- Calculate project root, git repo name, and git toplevel once at daemon launch
- Provide a clean API for handlers to access these constants
- FAIL FAST if constants cannot be calculated at launch
- Maintain backward compatibility with handler API

## Non-Goals

- Changing config file structure
- Modifying the CLI's `get_project_path()` (it uses CWD legitimately for discovery)
- Changing `install.py` (installer runs interactively, CWD is fine)
- Changing `scripts/debug_info.py` (diagnostic tool, CWD is fine)
- Changing test files that use `cwd=tmp_path` in subprocess calls (correct usage)

## Context & Background

### Current CWD Usage Audit

#### Category 1: Handler code using CWD directly (MUST FIX)

| File | Line | Usage | Purpose |
|------|------|-------|---------|
| `src/.../handlers/status_line/git_repo_name.py` | 51 | `Path.cwd()` | Get project root for git commands |
| `src/.../handlers/pre_tool_use/markdown_organization.py` | 51 | `Path.cwd()` | Default workspace root (overridden by options) |
| `src/.../handlers/pre_tool_use/plan_number_helper.py` | 43 | `Path.cwd()` | Default workspace root (overridden by options) |
| `src/.../handlers/session_start/yolo_container_detection.py` | 88, 150 | `Path.cwd()` | Check if running in /workspace container |

#### Category 2: Core code using CWD as fallback (MUST FIX)

| File | Line | Usage | Purpose |
|------|------|-------|---------|
| `src/.../core/utils.py` | 74 | `Path.cwd()` | Fallback in `get_workspace_root()` |
| `src/.../core/front_controller.py` | 183 | `get_workspace_root()` | Error logging path |

#### Category 3: Handlers using `get_workspace_root()` which falls back to CWD (MUST FIX)

| File | Line | Usage | Purpose |
|------|------|-------|---------|
| `src/.../handlers/pre_tool_use/validate_plan_number.py` | 54 | `get_workspace_root()` | Workspace root for plan validation |
| `src/.../handlers/post_tool_use/validate_eslint_on_write.py` | 46 | `get_workspace_root()` | Workspace root for eslint |
| `src/.../handlers/session_start/workflow_state_restoration.py` | 43 | `get_workspace_root()` | Workspace root for state files |
| `src/.../handlers/pre_compact/workflow_state_pre_compact.py` | 48 | `get_workspace_root()` | Workspace root for state files |

#### Category 4: CLI code using CWD for project discovery (ACCEPTABLE)

| File | Line | Usage | Purpose |
|------|------|-------|---------|
| `src/.../daemon/cli.py` | 65 | `Path.cwd()` | Walk up to find `.claude` directory |
| `src/.../daemon/cli.py` | 81 | `Path.cwd()` | Error message showing current directory |
| `src/.../daemon/cli.py` | 718 | `Path.cwd()` | Config generation: walk up for project root |

These are **acceptable** because CLI commands are run interactively and CWD is the correct starting point for project discovery.

#### Category 5: Install/diagnostic scripts (OUT OF SCOPE)

| File | Line | Usage | Purpose |
|------|------|-------|---------|
| `install.py` | 183 | `Path.cwd()` | Installer project discovery |
| `daemon.sh` | 72 | `os.getcwd()` | Log path generation |
| `scripts/debug_info.py` | 126 | `Path.cwd()` | Diagnostic output |

### How Project Root Already Flows

The daemon startup path already determines project root correctly:

1. `cli.py:get_project_path()` walks up from CWD to find `.claude` directory
2. `cli.py:_start_daemon()` (line 207) calls `get_project_path()`
3. Line 289: `controller.initialise(handler_config, workspace_root=project_path)`
4. `DaemonController.initialise()` passes `workspace_root` to `HandlerRegistry.register_all()`
5. Registry injects `workspace_root` into handler options (line 218)

**The problem**: Not all handlers use the injected `workspace_root`. Some call `Path.cwd()` directly in `__init__()` as a default, and some call `get_workspace_root()` which has a CWD fallback.

### How workspace_root reaches handlers today

The `HandlerRegistry` (line 217-218) injects `workspace_root` into the options dict. Handlers that declare `_workspace_root` as an attribute get it set via the options system. But this only works for handlers that:
1. Declare `_workspace_root` or `workspace_root` as an attribute
2. Are configured with options in the YAML

Handlers like `GitRepoNameHandler` and `YoloContainerDetectionHandler` don't use the options system at all.

## Tasks

### Phase 1: Create Calculated Constants Module

- [ ] **Task 1.1**: Create `src/claude_code_hooks_daemon/core/project_context.py`
  - [ ] Define `ProjectContext` dataclass with fields:
    - `project_root: Path` (absolute path to project directory)
    - `git_toplevel: Path | None` (from `git rev-parse --show-toplevel`)
    - `git_repo_name: str | None` (parsed from git remote URL)
    - `config_dir: Path` (project_root / ".claude")
    - `is_git_repo: bool`
  - [ ] Write `ProjectContext.from_project_root(root: Path) -> ProjectContext` factory
  - [ ] Factory calculates all git values once, FAIL FAST on project_root not existing
  - [ ] Git failures are non-fatal (set `is_git_repo=False`, `git_repo_name=None`)
  - [ ] Write failing tests first (TDD)

- [ ] **Task 1.2**: Create module-level singleton access
  - [ ] `_context: ProjectContext | None = None` module-level variable
  - [ ] `init_project_context(root: Path) -> ProjectContext` - called once at daemon startup
  - [ ] `get_project_context() -> ProjectContext` - returns cached context, raises RuntimeError if not initialized (FAIL FAST)
  - [ ] Write tests for singleton lifecycle

### Phase 2: Wire Into Daemon Startup

- [ ] **Task 2.1**: Initialize context in `DaemonController.initialise()`
  - [ ] Call `init_project_context(workspace_root)` at start of `initialise()`
  - [ ] If `workspace_root` is None, raise ValueError (FAIL FAST)
  - [ ] Store reference on controller: `self._project_context`

- [ ] **Task 2.2**: Update `HandlerRegistry` to pass context
  - [ ] Pass `ProjectContext` to `register_all()` instead of raw `workspace_root: Path`
  - [ ] Inject `project_context` into handler options alongside `workspace_root`
  - [ ] Keep `workspace_root` in options for backward compatibility

### Phase 3: Update Handlers to Use Constants

- [ ] **Task 3.1**: Update `GitRepoNameHandler`
  - [ ] Remove `_get_repo_name()` method with its 3 subprocess calls
  - [ ] Use `get_project_context().git_repo_name` instead
  - [ ] Remove `Path.cwd()` call (line 51)
  - [ ] Update tests

- [ ] **Task 3.2**: Update `YoloContainerDetectionHandler`
  - [ ] Replace `Path.cwd() == Path("/workspace")` with `get_project_context().project_root == Path("/workspace")`
  - [ ] Replace `Path(".claude").exists()` with `get_project_context().config_dir.exists()`
  - [ ] Update tests

- [ ] **Task 3.3**: Update `MarkdownOrganizationHandler` and `PlanNumberHelperHandler`
  - [ ] These already get `_workspace_root` from options injection
  - [ ] Change default from `Path.cwd()` to `None`, validate in `matches()`/`handle()` that it's set
  - [ ] Or use `get_project_context().project_root` as default instead of `Path.cwd()`
  - [ ] Update tests

- [ ] **Task 3.4**: Update handlers using `get_workspace_root()`
  - [ ] `validate_plan_number.py`: Use `get_project_context().project_root`
  - [ ] `validate_eslint_on_write.py`: Use `get_project_context().project_root`
  - [ ] `workflow_state_restoration.py`: Use `get_project_context().project_root`
  - [ ] `workflow_state_pre_compact.py`: Use `get_project_context().project_root`
  - [ ] Update tests

### Phase 4: Clean Up Core Utils

- [ ] **Task 4.1**: Update `get_workspace_root()` in `core/utils.py`
  - [ ] Replace CWD fallback with `get_project_context().project_root`
  - [ ] Or deprecate/remove `get_workspace_root()` entirely if all callers migrated
  - [ ] Update `front_controller.py` error logging to use `get_project_context()`

- [ ] **Task 4.2**: Audit for any remaining CWD calls
  - [ ] Grep for `Path.cwd()`, `os.getcwd()` in `src/`
  - [ ] Verify zero results (excluding CLI discovery code which is acceptable)
  - [ ] Add a ruff/QA rule or comment documenting that CWD is banned in handler/core code

### Phase 5: Testing & QA

- [ ] **Task 5.1**: Write integration tests
  - [ ] Test `ProjectContext` creation with real git repo
  - [ ] Test `ProjectContext` creation with non-git directory
  - [ ] Test singleton lifecycle (init, get, re-init)
  - [ ] Test FAIL FAST when context not initialized

- [ ] **Task 5.2**: Run full QA suite
  - [ ] `./scripts/qa/run_all.sh`
  - [ ] Verify 95%+ coverage maintained
  - [ ] Verify zero CWD calls remain in handler/core code

- [ ] **Task 5.3**: Live testing
  - [ ] Start daemon, verify git repo name displays correctly
  - [ ] Verify git branch displays correctly
  - [ ] Verify planning mode handlers work
  - [ ] Verify eslint handler works

## Technical Decisions

### Decision 1: Singleton Module vs Dependency Injection

**Context**: How should handlers access calculated constants?

**Options Considered**:
1. **Singleton module** (`get_project_context()`) - Simple import, works everywhere
2. **Dependency injection** (pass context through handler init) - More testable but requires API changes
3. **Both** - Singleton for convenience, DI for testing

**Decision**: Option 3 - Both. Use singleton for production, but all handlers that currently accept `workspace_root` as a constructor param keep that for testability. The singleton provides the fallback when no explicit value is passed.

### Decision 2: Where to Extract Git Repo Name Logic

**Context**: `GitRepoNameHandler._get_repo_name()` has URL parsing logic that should be reusable.

**Decision**: Move git remote URL parsing into `ProjectContext.from_project_root()`. The handler becomes a thin wrapper that reads from context.

### Decision 3: FAIL FAST Strategy

**Context**: What happens if project root doesn't exist or git fails?

**Decision**:
- `project_root` not existing: FAIL FAST (raise ValueError at daemon startup)
- Not a git repo: Non-fatal (set `is_git_repo=False`, handlers degrade gracefully)
- Git commands timeout: Non-fatal (log warning, set git fields to None)
- Context not initialized when `get_project_context()` called: FAIL FAST (RuntimeError)

## Success Criteria

- [ ] Zero `Path.cwd()` or `os.getcwd()` calls in `src/claude_code_hooks_daemon/` (excluding CLI discovery in `cli.py`)
- [ ] `get_workspace_root()` either removed or no longer has CWD fallback
- [ ] Git repo name calculated once at startup, not per-request
- [ ] Project root derived from config path, not CWD
- [ ] FAIL FAST on missing project root or uninitialized context
- [ ] All tests passing with 95%+ coverage
- [ ] All QA checks pass
- [ ] Live daemon shows correct repo name and branch

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Handlers instantiated before context initialized (e.g., in tests) | High | Medium | Allow DI override in constructors; singleton raises clear error |
| Breaking handler tests that mock CWD | Medium | High | Update tests to use DI or mock `get_project_context()` |
| `YoloContainerDetectionHandler` needs actual CWD for container detection | Medium | Low | Container detection uses project_root which IS where daemon was started from; functionally equivalent |
| Self-install mode behaves differently | Medium | Low | `project_root` is already correctly set for self-install mode via `get_project_path()` |

## Notes & Updates

### 2026-01-30

- Plan created based on comprehensive codebase audit
- Found 14 CWD usage sites across handlers, core, and CLI
- Existing `workspace_root` injection mechanism covers ~50% of cases but is incomplete
- `GitRepoNameHandler` is the most impactful fix (eliminates 3 subprocess calls per daemon startup that depend on CWD)
