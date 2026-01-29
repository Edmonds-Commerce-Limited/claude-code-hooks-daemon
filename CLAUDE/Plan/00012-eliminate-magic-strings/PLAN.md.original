# Plan 00012: Eliminate Magic Strings and Magic Numbers

**Status**: In Progress
**Created**: 2026-01-29
**Owner**: Claude
**Priority**: High
**Estimated Effort**: 12-16 hours

## Overview

This plan addresses a critical code quality issue: magic strings and magic numbers scattered throughout the codebase. Handler names, config keys, event types, priorities, timeouts, and file paths are currently hardcoded strings/numbers with no single source of truth. This causes bugs, makes refactoring dangerous, and violates DRY principles.

The goal is to create a comprehensive constants system with strict type safety, eliminate all magic values, centralize naming conversion logic, and add custom QA rules to prevent regression.

## Goals

- Eliminate all magic strings for handler identifiers, event types, and config keys
- Create single source of truth for all handler priorities, timeouts, paths, and thresholds
- Centralize naming conversion utilities (currently duplicated in 3 files)
- Add custom QA rules to detect and block magic strings/numbers
- Enforce STRICT DRY principles with automated validation
- Improve type safety with Literal types and enums

## Non-Goals

- Changing handler behavior or functionality
- Modifying hook event protocol
- Altering config file format (YAML structure stays the same)
- Performance optimization (unless constants improve it)

## Context & Background

### Current Problems

**Handler Naming Chaos** (3 different formats):
- Class name: `DestructiveGitHandler` (PascalCase with "Handler" suffix)
- Config key: `destructive_git` (snake_case, no suffix)
- Display name: `prevent-destructive-git` (kebab-case, descriptive)

**Event Type Formats** (4 different formats):
- Enum: `EventType.PRE_TOOL_USE` (SCREAMING_SNAKE_CASE)
- Config: `pre_tool_use` (snake_case)
- Bash scripts: `pre-tool-use` (kebab-case)
- JSON protocol: `"PreToolUse"` (PascalCase)

**Duplicated Conversion Logic**:
- `_to_snake_case()` function exists in 3 files:
  - `handlers/registry.py`
  - `config/models.py`
  - `config/validator.py`

**Magic Numbers Everywhere**:
- 40+ handler priorities hardcoded (10, 11, 12, 15, 20, 25, 26, 27, 28, 30, 35, 40, 42, 45, 50, 55, 60)
- 15+ timeout values (600, 30, 120, 300, 2000, 30000, 600000)
- 20+ file paths hardcoded
- Buffer sizes, thresholds, retry counts scattered throughout

**Recent Bug Example**:
Plan 00011 implementation suffered multiple bugs due to handler name format confusion:
- Tried `shares_options_with="markdown-organization"` (display name) - WRONG
- Tried `shares_options_with="enforce-markdown-organization"` (wrong display name) - WRONG
- Fixed: `shares_options_with="markdown_organization"` (config key) - CORRECT

This wasted significant time and caused user frustration.

### Root Cause

**No single source of truth** - Identifiers are defined inline everywhere, with no central registry to ensure consistency.

## Tasks

### Phase 1: Design Constants System

- [ ] ⬜ **Design HandlerID system**
  - [ ] ⬜ Create `HandlerIDMeta` dataclass with class_name, config_key, display_name
  - [ ] ⬜ Define `HandlerID` registry with all 40+ handlers
  - [ ] ⬜ Add type: `HandlerKey = Literal["destructive_git", "sed_blocker", ...]`

- [ ] ⬜ **Design EventID system**
  - [ ] ⬜ Create `EventIDMeta` dataclass with enum_value, config_key, bash_key, json_key
  - [ ] ⬜ Define `EventID` registry for all event types
  - [ ] ⬜ Add type: `EventKey = Literal["pre_tool_use", "post_tool_use", ...]`

- [ ] ⬜ **Design Priority system**
  - [ ] ⬜ Create `Priority` class with named constants
  - [ ] ⬜ Define ranges: SAFETY (5-20), QUALITY (25-35), WORKFLOW (36-55), ADVISORY (56-60)
  - [ ] ⬜ Map each handler to specific priority constant

- [ ] ⬜ **Design Timeout and Path systems**
  - [ ] ⬜ Create `Timeout` class for all timeout values
  - [ ] ⬜ Create `DaemonPath` class for daemon-related paths
  - [ ] ⬜ Create `ProjectPath` class for project-relative paths

### Phase 2: Create Constants Module

- [ ] ⬜ **Create `src/claude_code_hooks_daemon/constants/__init__.py`**
  - [ ] ⬜ Export all public constants and types
  - [ ] ⬜ Add module docstring explaining usage

- [ ] ⬜ **Create `constants/handlers.py`**
  ```python
  from dataclasses import dataclass
  from typing import Literal

  @dataclass(frozen=True)
  class HandlerIDMeta:
      """Metadata for a handler identifier."""
      class_name: str      # PascalCase with Handler suffix
      config_key: str      # snake_case, no suffix
      display_name: str    # kebab-case, descriptive

  class HandlerID:
      """Single source of truth for all handler identifiers."""
      DESTRUCTIVE_GIT = HandlerIDMeta(
          class_name="DestructiveGitHandler",
          config_key="destructive_git",
          display_name="prevent-destructive-git"
      )
      # ... 40+ more handlers

  # Type-safe config key literal
  HandlerKey = Literal[
      "destructive_git",
      "sed_blocker",
      # ... all config keys
  ]
  ```

- [ ] ⬜ **Create `constants/events.py`**
  ```python
  @dataclass(frozen=True)
  class EventIDMeta:
      """Metadata for an event type identifier."""
      enum_value: str    # SCREAMING_SNAKE_CASE
      config_key: str    # snake_case
      bash_key: str      # kebab-case
      json_key: str      # PascalCase

  class EventID:
      """Single source of truth for all event type identifiers."""
      PRE_TOOL_USE = EventIDMeta(
          enum_value="PRE_TOOL_USE",
          config_key="pre_tool_use",
          bash_key="pre-tool-use",
          json_key="PreToolUse"
      )
      # ... all event types
  ```

- [ ] ⬜ **Create `constants/priority.py`**
  ```python
  class Priority:
      """Handler priority constants with semantic meaning."""
      # Test handlers
      HELLO_WORLD = 5

      # Safety handlers (10-20)
      DESTRUCTIVE_GIT = 10
      SED_BLOCKER = 11
      ABSOLUTE_PATH = 12
      WORKTREE_FILE_COPY = 15
      GIT_STASH = 20

      # Code quality handlers (25-35)
      ESLINT_DISABLE = 25
      PYTHON_QA_SUPPRESSION = 26
      PHP_QA_SUPPRESSION = 27
      GO_QA_SUPPRESSION = 28
      PLAN_NUMBER_HELPER = 30
      TDD_ENFORCEMENT = 35

      # Workflow handlers (36-55)
      GH_ISSUE_COMMENTS = 40
      MARKDOWN_ORGANIZATION = 42
      NPM_AUDIT = 45
      WEB_SEARCH_YEAR = 55

      # Advisory handlers (56-60)
      BRITISH_ENGLISH = 60
  ```

- [ ] ⬜ **Create `constants/timeout.py`**
  ```python
  class Timeout:
      """Timeout constants in milliseconds."""
      BASH_DEFAULT = 120_000      # 2 minutes
      BASH_MAX = 600_000          # 10 minutes
      DAEMON_IDLE = 600           # 10 minutes (seconds)
      REQUEST = 30                # 30 seconds
      HOOK_DISPATCH = 5000        # 5 seconds
  ```

- [ ] ⬜ **Create `constants/paths.py`**
  ```python
  class DaemonPath:
      """Daemon-related path components."""
      CLAUDE_DIR = ".claude"
      HOOKS_DAEMON_DIR = "hooks-daemon"
      CONFIG_FILE = "hooks-daemon.yaml"
      SOCKET_FILE = "daemon.sock"
      PID_FILE = "daemon.pid"
      LOG_DIR = "logs"

  class ProjectPath:
      """Project-relative path constants."""
      PLAN_DIR = "CLAUDE/Plan"
      PLAN_WORKFLOW_DOC = "CLAUDE/PlanWorkflow.md"
      ARCHITECTURE_DOC = "CLAUDE/ARCHITECTURE.md"
  ```

### Phase 3: Create Centralized Naming Utilities

- [ ] ⬜ **Create `src/claude_code_hooks_daemon/utils/__init__.py`**

- [ ] ⬜ **Create `utils/naming.py`**
  ```python
  """Centralized naming conversion utilities.

  Single source of truth for converting between naming formats.
  Eliminates duplication of _to_snake_case() across 3 files.
  """
  import re

  def class_name_to_config_key(class_name: str) -> str:
      """Convert handler class name to config key.

      Examples:
          DestructiveGitHandler -> destructive_git
          SedBlockerHandler -> sed_blocker
      """
      # Remove Handler suffix first
      name = class_name.removesuffix("Handler")
      # Convert to snake_case
      s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
      return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

  def config_key_to_display_name(config_key: str) -> str:
      """Convert config key to display name.

      Examples:
          destructive_git -> destructive-git
          sed_blocker -> sed-blocker
      """
      return config_key.replace("_", "-")

  def display_name_to_config_key(display_name: str) -> str:
      """Convert display name back to config key.

      Examples:
          destructive-git -> destructive_git
          sed-blocker -> sed_blocker
      """
      return display_name.replace("-", "_")
  ```

- [ ] ⬜ **Add comprehensive tests for naming utilities**
  - [ ] ⬜ Test all handler class names convert correctly
  - [ ] ⬜ Test edge cases (acronyms, numbers, single words)
  - [ ] ⬜ Test round-trip conversions

### Phase 4: Migrate Handler Base Class

- [ ] ⬜ **Update `core/handler.py`**
  - [ ] ⬜ Add `handler_id: HandlerIDMeta | None` parameter to `__init__`
  - [ ] ⬜ Auto-derive config_key from handler_id if provided
  - [ ] ⬜ Deprecate passing raw `name` string (keep for backward compat)
  - [ ] ⬜ Add `config_key` property that returns the snake_case key

  ```python
  from claude_code_hooks_daemon.constants import HandlerIDMeta

  class Handler:
      __slots__ = ("name", "priority", "tags", "terminal", "handler_id", "config_key")

      def __init__(
          self,
          name: str | None = None,  # Deprecated, use handler_id instead
          *,
          handler_id: HandlerIDMeta | None = None,
          priority: int = 50,
          # ... other params
      ):
          if handler_id:
              self.handler_id = handler_id
              self.name = handler_id.display_name
              self.config_key = handler_id.config_key
          elif name:
              # Legacy mode
              self.name = name
              self.config_key = display_name_to_config_key(name)
          else:
              raise ValueError("Must provide either handler_id or name")
  ```

### Phase 5: Migrate All 40+ Handlers (TDD)

- [ ] ⬜ **Migrate safety handlers (Priority 10-20)**
  - [ ] ⬜ Write tests verifying handler_id usage
  - [ ] ⬜ Update DestructiveGitHandler
  - [ ] ⬜ Update SedBlockerHandler
  - [ ] ⬜ Update AbsolutePathHandler
  - [ ] ⬜ Update WorktreeFileCopyHandler
  - [ ] ⬜ Update GitStashHandler
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

- [ ] ⬜ **Migrate code quality handlers (Priority 25-35)**
  - [ ] ⬜ Write tests for each handler
  - [ ] ⬜ Update ESLintDisableHandler
  - [ ] ⬜ Update PythonQASuppressionHandler
  - [ ] ⬜ Update PHPQASuppressionHandler
  - [ ] ⬜ Update GoQASuppressionHandler
  - [ ] ⬜ Update PlanNumberHelperHandler
  - [ ] ⬜ Update TDDEnforcementHandler
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

- [ ] ⬜ **Migrate workflow handlers (Priority 36-55)**
  - [ ] ⬜ Write tests for each handler
  - [ ] ⬜ Update MarkdownOrganizationHandler
  - [ ] ⬜ Update GhIssueCommentsHandler
  - [ ] ⬜ Update NpmAuditHandler
  - [ ] ⬜ Update WebSearchYearHandler
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

- [ ] ⬜ **Migrate advisory handlers (Priority 56-60)**
  - [ ] ⬜ Write tests for each handler
  - [ ] ⬜ Update BritishEnglishHandler
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

- [ ] ⬜ **Migrate all other event type handlers**
  - [ ] ⬜ PostToolUse handlers
  - [ ] ⬜ SessionStart/SessionEnd handlers
  - [ ] ⬜ Stop/SubagentStop handlers
  - [ ] ⬜ Notification handlers
  - [ ] ⬜ StatusLine handlers
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

### Phase 6: Migrate Registry and Config

- [ ] ⬜ **Update `handlers/registry.py`**
  - [ ] ⬜ Replace `_to_snake_case()` with import from `utils.naming`
  - [ ] ⬜ Use HandlerKey type for config keys
  - [ ] ⬜ Use EventKey type for event type keys
  - [ ] ⬜ Remove hardcoded string comparisons
  - [ ] ⬜ Write tests for registry with new constants
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

- [ ] ⬜ **Update `config/models.py`**
  - [ ] ⬜ Replace `_to_snake_case()` with import from `utils.naming`
  - [ ] ⬜ Use HandlerKey and EventKey types
  - [ ] ⬜ Add validation that config keys match HandlerID registry
  - [ ] ⬜ Write tests for config validation
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

- [ ] ⬜ **Update `config/validator.py`**
  - [ ] ⬜ Replace `_to_snake_case()` with import from `utils.naming`
  - [ ] ⬜ Use constants for validation rules
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

- [ ] ⬜ **Update `daemon/init_config.py`**
  - [ ] ⬜ Use Priority constants for all handlers
  - [ ] ⬜ Use Timeout constants
  - [ ] ⬜ Verify generated config uses correct keys
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

### Phase 7: Migrate Core and Daemon Components

- [ ] ⬜ **Update `core/event.py`**
  - [ ] ⬜ Use EventID constants
  - [ ] ⬜ Add EventKey literal type
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

- [ ] ⬜ **Update `daemon/paths.py`**
  - [ ] ⬜ Use DaemonPath constants
  - [ ] ⬜ Remove hardcoded path strings
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

- [ ] ⬜ **Update `daemon/server.py`**
  - [ ] ⬜ Use Timeout constants
  - [ ] ⬜ Use DaemonPath constants
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

- [ ] ⬜ **Update all bash scripts in `hooks/`**
  - [ ] ⬜ Document mapping between bash event names and Python EventID
  - [ ] ⬜ Add comments with EventID references
  - [ ] ⬜ Consider generating bash scripts from Python constants

### Phase 8: Create Custom QA Rules

- [ ] ⬜ **Research Python linting extensibility**
  - [ ] ⬜ Investigate Ruff custom rules (if possible)
  - [ ] ⬜ Investigate Pylint custom checkers
  - [ ] ⬜ Investigate flake8 plugins as alternative

- [ ] ⬜ **Create custom QA rule: detect-magic-strings**
  - [ ] ⬜ Detect hardcoded handler names (string literals matching handler patterns)
  - [ ] ⬜ Detect hardcoded event type names
  - [ ] ⬜ Flag usage of `_to_snake_case()` outside utils.naming
  - [ ] ⬜ Require imports from constants module

- [ ] ⬜ **Create custom QA rule: detect-magic-numbers**
  - [ ] ⬜ Detect hardcoded priorities (10, 11, 15, 20, etc.)
  - [ ] ⬜ Detect hardcoded timeouts
  - [ ] ⬜ Allow number literals only in constants module
  - [ ] ⬜ Require Priority.* or Timeout.* for handler initialization

- [ ] ⬜ **Create custom QA rule: enforce-handler-id**
  - [ ] ⬜ Require all Handler subclass __init__ to use handler_id parameter
  - [ ] ⬜ Flag deprecated name parameter usage
  - [ ] ⬜ Verify handler_id comes from HandlerID registry

- [ ] ⬜ **Integrate custom rules into QA pipeline**
  - [ ] ⬜ Add to `scripts/qa/run_lint.sh`
  - [ ] ⬜ Document in CONTRIBUTING.md
  - [ ] ⬜ Test that rules catch violations
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

### Phase 9: Update Configuration Files

- [ ] ⬜ **Update `.claude/hooks-daemon.yaml`**
  - [ ] ⬜ Verify all handler config keys match HandlerID registry
  - [ ] ⬜ Add comments referencing constants module
  - [ ] ⬜ Test daemon starts with updated config

- [ ] ⬜ **Update all test configs**
  - [ ] ⬜ Update test fixtures to use correct config keys
  - [ ] ⬜ Run full test suite: `./scripts/qa/run_tests.sh`

### Phase 10: Documentation

- [ ] ⬜ **Create `CLAUDE/CODING_STANDARDS.md`**
  - [ ] ⬜ Document DRY principles
  - [ ] ⬜ Document constants usage requirements
  - [ ] ⬜ Document naming conventions
  - [ ] ⬜ Document how to add new handlers (must add to HandlerID registry)
  - [ ] ⬜ Document custom QA rules

- [ ] ⬜ **Update `CLAUDE/HANDLER_DEVELOPMENT.md`**
  - [ ] ⬜ Show examples using HandlerID
  - [ ] ⬜ Show examples using Priority constants
  - [ ] ⬜ Explain handler_id parameter

- [ ] ⬜ **Update `CLAUDE/ARCHITECTURE.md`**
  - [ ] ⬜ Document constants module structure
  - [ ] ⬜ Document naming utilities
  - [ ] ⬜ Update diagrams if needed

- [ ] ⬜ **Update `CLAUDE.md`**
  - [ ] ⬜ Add section on constants usage
  - [ ] ⬜ Reference CODING_STANDARDS.md
  - [ ] ⬜ Update quick reference examples

- [ ] ⬜ **Update `CONTRIBUTING.md`**
  - [ ] ⬜ Document custom QA rules
  - [ ] ⬜ Explain how violations are caught
  - [ ] ⬜ Add examples of correct vs incorrect code

### Phase 11: Final Verification

- [ ] ⬜ **Run complete QA suite**
  - [ ] ⬜ `./scripts/qa/run_all.sh` passes
  - [ ] ⬜ No magic strings detected by custom rules
  - [ ] ⬜ No magic numbers detected by custom rules
  - [ ] ⬜ All tests pass with 95%+ coverage

- [ ] ⬜ **Manual testing**
  - [ ] ⬜ Test daemon starts successfully
  - [ ] ⬜ Test all hook events trigger correctly
  - [ ] ⬜ Test handler matching works
  - [ ] ⬜ Test config validation catches errors

- [ ] ⬜ **Code review**
  - [ ] ⬜ Review all constant definitions for completeness
  - [ ] ⬜ Review all handler migrations
  - [ ] ⬜ Review custom QA rules effectiveness
  - [ ] ⬜ Verify no hardcoded strings/numbers remain

## Dependencies

- None (standalone refactoring plan)

## Technical Decisions

### Decision 1: Use Dataclasses for Metadata
**Context**: Need structured way to store multiple naming formats for handlers/events
**Options Considered**:
1. Simple dicts - flexible but no type safety
2. Dataclasses - structured, type-safe, immutable with frozen=True
3. NamedTuples - lightweight but less readable

**Decision**: Use frozen dataclasses with explicit field names
**Rationale**:
- Provides type safety and IDE autocomplete
- Self-documenting with field names
- Immutable prevents accidental modification
- Better error messages than tuples
**Date**: 2026-01-29

### Decision 2: Keep Display Names Separate from Config Keys
**Context**: Handlers have both config keys (snake_case) and display names (kebab-case with descriptions)
**Options Considered**:
1. Merge into single identifier - simpler but less flexible
2. Auto-generate display names from config keys - loses expressiveness
3. Keep separate - more explicit but requires maintenance

**Decision**: Keep both config_key and display_name as separate fields
**Rationale**:
- Config keys must be valid Python identifiers (snake_case)
- Display names can be more descriptive ("prevent-destructive-git" vs "destructive_git")
- Allows future expansion (e.g., display names with spaces for UI)
- Makes intent explicit in HandlerID registry
**Date**: 2026-01-29

### Decision 3: Centralize _to_snake_case in utils.naming
**Context**: Function currently duplicated in 3 files
**Options Considered**:
1. Keep duplicated - violates DRY
2. Move to utils module - single source of truth
3. Generate at build time - over-engineered

**Decision**: Move to utils.naming module with comprehensive tests
**Rationale**:
- DRY principle - one implementation
- Easier to fix bugs (only one place to change)
- Easier to test (single test suite)
- Clear import path signals centralized utility
**Date**: 2026-01-29

### Decision 4: Use Ruff Custom Rules (or Pylint if Ruff Unavailable)
**Context**: Need automated enforcement of no-magic-strings/numbers
**Options Considered**:
1. Manual code review - not scalable, error-prone
2. Ruff custom rules - modern, fast, integrated
3. Pylint custom checkers - mature, well-documented
4. Pre-commit hooks with grep - brittle, hard to maintain

**Decision**: Prefer Ruff custom rules, fall back to Pylint if needed
**Rationale**:
- Ruff is already in QA pipeline
- Fast execution (written in Rust)
- Modern Python syntax support
- If Ruff doesn't support custom rules, Pylint is proven alternative
**Date**: 2026-01-29

### Decision 5: Add handler_id Parameter (Not Replace name)
**Context**: Need backward compatibility while migrating 40+ handlers
**Options Considered**:
1. Breaking change - replace name with handler_id immediately
2. Gradual migration - support both, deprecate name
3. Automatic conversion - use handler_id if available, else convert name

**Decision**: Add handler_id as new parameter, keep name for backward compat
**Rationale**:
- Allows incremental migration (phase by phase)
- Doesn't break existing handlers during development
- Clear deprecation path (can remove name in future release)
- Tests can verify both old and new approaches work
**Date**: 2026-01-29

## Success Criteria

- [ ] Zero magic strings for handler/event identifiers in codebase
- [ ] Zero magic numbers for priorities, timeouts, and thresholds
- [ ] All 40+ handlers use HandlerID constants
- [ ] All event type references use EventID constants
- [ ] `_to_snake_case()` exists in only ONE place (utils.naming)
- [ ] Custom QA rules detect and block new magic values
- [ ] All tests pass with 95%+ coverage maintained
- [ ] Full QA suite passes: `./scripts/qa/run_all.sh`
- [ ] Documentation updated (CODING_STANDARDS.md created)
- [ ] Daemon starts and all hooks work correctly

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Breaking existing handlers during migration | High | Medium | Use TDD - write tests before changing each handler. Keep backward compat. |
| Custom QA rules too strict (false positives) | Medium | Medium | Start with warnings, refine rules, allow explicit exceptions. |
| Ruff doesn't support custom rules | Low | Medium | Fall back to Pylint custom checkers (well-documented). |
| Missing edge cases in naming conversions | Medium | Low | Comprehensive test suite with all 40+ handler names. |
| Performance impact of constants module | Low | Very Low | Constants are frozen dataclasses (minimal overhead). Measure if concerned. |

## Timeline

- Phase 1-2 (Design & Create): 2-3 hours
- Phase 3 (Naming Utils): 1 hour
- Phase 4 (Handler Base): 1 hour
- Phase 5 (Migrate Handlers): 4-5 hours (40+ handlers, TDD)
- Phase 6-7 (Registry & Core): 2-3 hours
- Phase 8 (Custom QA Rules): 2-3 hours
- Phase 9-10 (Config & Docs): 1-2 hours
- Phase 11 (Verification): 1 hour

**Target Completion**: 2-3 days of focused work

## Notes & Updates

### 2026-01-29 - Plan Created
- Comprehensive exploration completed with 3 parallel agents
- Discovered extensive magic string/number issues
- User feedback: "STRICT DRY NO MAGIC" - high priority
- Root cause: No single source of truth for identifiers
- Estimated 40+ handlers need migration
- Plan follows TDD workflow throughout

### 2026-01-29 - Progress Update: Phases 1-3 Complete
**Completed Work:**
- ✅ Phase 1: Designed HandlerID, EventID, Priority, Timeout, and Path constants systems
- ✅ Phase 2: Created complete constants module with all 54 handlers cataloged
  - Created `constants/__init__.py` with public API
  - Created `constants/handlers.py` with HandlerID registry (54 handlers)
  - Created `constants/events.py` with EventID registry (11 event types)
  - Created `constants/priority.py` with Priority constants
  - Created `constants/timeout.py` with Timeout constants
  - Created `constants/paths.py` with DaemonPath and ProjectPath constants
- ✅ Phase 3: Created centralized naming utilities
  - Created `utils/__init__.py` module
  - Created `utils/naming.py` with conversion functions
  - Created comprehensive test suite: `tests/unit/utils/test_naming.py`
  - All 23 tests passing

**Next Steps:**
- Phase 4: Migrate Handler base class to support handler_id parameter
- Phase 5+: Migrate all 54 handlers to use constants

### 2026-01-29 - Progress Update: Phase 4 Complete
**Completed Work:**
- ✅ Phase 4: Migrated Handler base class to support handler_id parameter
  - Added `handler_id: HandlerIDMeta | None` parameter to Handler.__init__()
  - Added `config_key: str` attribute automatically derived from handler_id or name
  - Maintained full backward compatibility with `name` parameter
  - Added validation that at least one identifier is provided
  - handler_id takes precedence when both are provided
  - Created comprehensive test suite: `tests/unit/core/test_handler_with_handler_id.py` (15 tests)
  - Updated existing test to reflect new validation behavior
  - All 2916 tests passing with 96.95% coverage
  - Full QA suite passes (format, lint, type check, tests, security)

**Key Implementation Details:**
- Used TYPE_CHECKING import to avoid circular dependency with HandlerIDMeta
- Imported display_name_to_config_key() locally in __init__ to avoid circular import
- handler_id mode: Sets name to display_name, config_key to config_key from HandlerIDMeta
- Legacy mode: Derives config_key from name using display_name_to_config_key()
- Added handler_id and config_key to __slots__ for memory efficiency

**Next Steps:**
- Phase 5: Migrate all 54 handlers to use HandlerID constants
  - This is a large task requiring careful migration of each handler
  - Should be done incrementally with QA checks after each batch
  - Will require updating shares_options_with references to use config_key format
