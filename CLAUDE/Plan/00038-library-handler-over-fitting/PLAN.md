# Plan 00038: Library Handler Over-fitting to Project-Specific Assumptions

**Status**: Not Started
**Created**: 2026-02-09
**Owner**: Unassigned
**Priority**: High
**Estimated Effort**: 3-5 days

## Overview

Multiple handlers in the codebase contain project-specific assumptions that make them NOT reusable as library handlers. This violates the core library design principle that handlers should be GENERIC and configurable rather than hardcoded to a specific project's structure.

The TDD enforcement handler is the primary example, but investigation reveals this is a systemic issue affecting multiple handlers across different categories (planning, testing, markdown organization, etc.).

This plan documents all affected handlers, categorizes them by severity, and outlines a phased approach to make handlers truly project-agnostic through configuration and multi-language support.

## Goals

- Document all handlers with project-specific assumptions
- Categorize handlers by severity (blocking vs minor issues)
- Design configuration-based solutions for path mapping
- Add multi-language test file convention support
- Create migration strategy that doesn't break existing functionality
- Establish design patterns for future handlers

## Non-Goals

- Rewriting all handlers immediately (phased approach instead)
- Removing project-specific handlers entirely (they serve a purpose for this project)
- Breaking existing functionality for this project during migration

## Context & Background

The daemon was originally built to dogfood itself on the hooks daemon project. As it evolved into a library, many handlers retained project-specific assumptions:

- Hardcoded paths (e.g., `CLAUDE/Plan/`, `src/`, `tests/`)
- Python-only test conventions (e.g., `test_*.py`)
- Project name assumptions (e.g., `claude_code_hooks_daemon`)
- Single-language assumptions

These assumptions make handlers less useful (or broken) when used in other projects with different structures.

## Investigation Summary

### Handlers with Project-Specific Logic

#### **CRITICAL SEVERITY** (Blocks multi-language or multi-project use)

1. **TddEnforcementHandler** (`pre_tool_use/tdd_enforcement.py`)
   - **Issue**: Hardcoded Python test convention (`test_*.py`)
   - **Issue**: Hardcoded path patterns (`tests/unit/handlers/{event_type}/test_{handler}.py`)
   - **Issue**: Workspace root detection assumes `/workspace` fallback
   - **Issue**: Only checks Python files (`.py` extension)
   - **Impact**: Cannot enforce TDD for Go, PHP, TypeScript, Rust, Java, etc.
   - **Lines**: 44-59 (matches), 108-159 (_get_test_file_path)

2. **MarkdownOrganizationHandler** (`pre_tool_use/markdown_organization.py`)
   - **Issue**: Hardcoded directory structure (`CLAUDE/`, `docs/`, `eslint-rules/`)
   - **Issue**: Hardcoded plan path (`CLAUDE/Plan/`)
   - **Issue**: Project-specific page patterns (`src/pages/articles/`)
   - **Impact**: Unusable in projects without these exact directories
   - **Lines**: 42-44 (plan path check), 76-83 (project markers), 378-397 (CLAUDE/ check)

3. **ValidatePlanNumberHandler** (`pre_tool_use/validate_plan_number.py`)
   - **Issue**: Hardcoded plan path (`CLAUDE/Plan/`)
   - **Issue**: Assumes specific numbering format (`NNN-description`)
   - **Impact**: Only works for projects using this exact plan structure
   - **Lines**: 69 (plan path pattern), 176 (plan root)

4. **PlanNumberHelperHandler** (`pre_tool_use/plan_number_helper.py`)
   - **Issue**: Config-based but still assumes plan directory structure
   - **Issue**: Hardcoded plan path format
   - **Impact**: Moderate - at least uses config, but structure assumptions remain
   - **Lines**: 72 (plan_dir usage), 138 (plan_base path)

5. **PlanWorkflowHandler** (`pre_tool_use/plan_workflow.py`)
   - **Issue**: Hardcoded plan path pattern (`CLAUDE/Plan/*/PLAN.md`)
   - **Issue**: Hardcoded workflow doc reference (`CLAUDE/PlanWorkflow.md`)
   - **Impact**: Only useful for projects with exact same structure
   - **Lines**: 44 (path pattern)

6. **PlanCompletionAdvisorHandler** (`pre_tool_use/plan_completion_advisor.py`)
   - **Issue**: Hardcoded plan path pattern (`CLAUDE/Plan/`)
   - **Issue**: Assumes `Completed/` subdirectory structure
   - **Impact**: Only works with exact directory layout
   - **Lines**: 21 (pattern), 102-103 (git mv advice)

#### **MODERATE SEVERITY** (Works but has language-specific assumptions)

7. **PythonQaSuppressionBlocker** (`pre_tool_use/python_qa_suppression_blocker.py`)
   - **Issue**: Language-specific but GOOD - uses LanguageConfig
   - **Issue**: Hardcoded skip directories (`tests/fixtures/`, `migrations/`)
   - **Impact**: Skip directories might not match other projects
   - **Lines**: 49 (skip_directories check)

8. **GoQaSuppressionBlocker** (`pre_tool_use/go_qa_suppression_blocker.py`)
   - **Issue**: Same as Python - hardcoded skip directories
   - **Impact**: Minor - good use of LanguageConfig otherwise
   - **Lines**: 49 (skip_directories check)

9. **PhpQaSuppressionBlocker** (`pre_tool_use/php_qa_suppression_blocker.py`)
   - **Issue**: Same pattern as Python/Go
   - **Impact**: Minor
   - **Lines**: 49 (skip_directories check)

10. **EslintDisableHandler** (`pre_tool_use/eslint_disable.py`)
    - **Issue**: Hardcoded skip directories (`node_modules`, `dist`, `.build`)
    - **Issue**: Hardcoded file extensions (`.ts`, `.tsx`, `.js`, `.jsx`)
    - **Impact**: Minor - common conventions but not configurable
    - **Lines**: 27 (extensions), 58 (skip directories)

#### **LOW SEVERITY** (Project-specific but intentional)

11. **DaemonRestartVerifierHandler** (`pre_tool_use/daemon_restart_verifier.py`)
    - **Issue**: Uses `is_hooks_daemon_repo()` - intentionally project-specific
    - **Issue**: Hardcoded command (`$PYTHON -m claude_code_hooks_daemon.daemon.cli`)
    - **Impact**: Intentionally only for this project (dogfooding)
    - **Lines**: 62 (repo check), 91 (command)

## Multi-Language Test File Conventions

Based on research and industry standards:

| Language | Test File Pattern | Example | Framework |
|----------|------------------|---------|-----------|
| **Python** | `test_*.py` or `*_test.py` | `test_auth.py` | pytest, unittest |
| **Go** | `*_test.go` | `auth_test.go` | testing |
| **PHP** | `*Test.php` | `AuthTest.php` | PHPUnit |
| **JavaScript/TypeScript** | `*.test.{js,ts}` or `*.spec.{js,ts}` | `auth.test.ts` | Jest, Vitest |
| **Rust** | `tests/*.rs` or inline `#[cfg(test)]` | `tests/integration.rs` | cargo test |
| **Java** | `*Test.java` | `AuthTest.java` | JUnit |
| **Ruby** | `*_spec.rb` or `test_*.rb` | `auth_spec.rb` | RSpec, Minitest |
| **C#** | `*Tests.cs` or `*.Tests.cs` | `AuthTests.cs` | xUnit, NUnit |

### Common Patterns

1. **Suffix-based**: Most languages (Go, PHP, Java, C#, Ruby)
2. **Prefix-based**: Python (pytest default)
3. **Mixed**: JavaScript/TypeScript (both `.test` and `.spec`)
4. **Directory-based**: Rust, some Java projects (`tests/` directory)

## Technical Decisions

### Decision 1: Configuration-Driven Path Mapping

**Context**: Handlers hardcode paths like `CLAUDE/Plan/`, `tests/`, `src/` which don't work for other projects.

**Options Considered**:
1. **Keep hardcoded** - Simple but defeats library purpose
2. **Environment variables** - Flexible but complex, hard to document
3. **Handler config in YAML** - Clean, documented, per-handler control
4. **Project-level config section** - Centralized, easier to understand

**Decision**: Use project-level config section in `.claude/hooks-daemon.yaml` with handler-specific overrides

**Example**:
```yaml
project_paths:
  # Generic path mapping for all handlers
  plan_directory: "CLAUDE/Plan"  # or "docs/plans", "planning/", etc.
  test_directory: "tests"        # or "spec", "__tests__", etc.
  source_directory: "src"        # or "lib", "app", etc.
  docs_directory: "docs"         # or "documentation", etc.

handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
      # Override defaults if needed
      test_directory: "spec"  # Ruby project
      test_pattern: "{basename}_spec.rb"
```

**Rationale**:
- Single source of truth for paths
- Easy to understand and document
- Handlers can access via `ProjectContext` or registry
- Supports per-handler overrides when needed

**Date**: 2026-02-09

### Decision 2: Multi-Language Support via LanguageConfig Extension

**Context**: TDD handler only supports Python. Need to support Go, PHP, JS/TS, etc.

**Options Considered**:
1. **Separate handlers per language** - Duplicates logic, maintenance nightmare
2. **Language detection + config map** - Clean, extensible, DRY
3. **Plugin system** - Overkill for this use case

**Decision**: Extend existing `LanguageConfig` dataclass with test file patterns

**Implementation**:
```python
@dataclass(frozen=True)
class LanguageConfig:
    name: str
    extensions: tuple[str, ...]
    test_file_patterns: tuple[str, ...]  # NEW: Multiple patterns per language
    test_directory: str  # NEW: Default test directory
    qa_forbidden_patterns: tuple[str, ...]
    # ... existing fields ...
```

**Example configs**:
```python
PYTHON_CONFIG = LanguageConfig(
    name="Python",
    extensions=(".py",),
    test_file_patterns=("test_{filename}", "{basename}_test.py"),
    test_directory="tests",
    # ...
)

GO_CONFIG = LanguageConfig(
    name="Go",
    extensions=(".go",),
    test_file_patterns=("{basename}_test.go",),
    test_directory=".",  # Go tests colocated
    # ...
)

TYPESCRIPT_CONFIG = LanguageConfig(
    name="TypeScript",
    extensions=(".ts", ".tsx"),
    test_file_patterns=("{basename}.test.ts", "{basename}.spec.ts"),
    test_directory="__tests__",
    # ...
)
```

**Rationale**:
- Reuses existing LanguageConfig pattern
- One handler supports all languages
- Easy to add new languages
- Follows existing QA suppression blocker pattern

**Date**: 2026-02-09

### Decision 3: Graceful Degradation for Non-Configured Projects

**Context**: When handlers are enabled but project paths don't exist, what happens?

**Options Considered**:
1. **Fail hard** - Error if paths missing
2. **Disable silently** - No validation at all
3. **Warn and disable** - Log warning, skip handler
4. **Smart defaults** - Attempt common conventions

**Decision**: Smart defaults with opt-out

**Implementation**:
- Handlers check if paths exist before enforcing
- Use common conventions as defaults (e.g., `tests/`, `docs/`)
- Log info message when using defaults
- Allow explicit `enabled: false` to disable

**Example**:
```python
def matches(self, hook_input: dict) -> bool:
    # Get configured path or use default
    test_dir = self._config.get("test_directory", "tests")

    # Check if path exists in project
    if not (ProjectContext.project_root() / test_dir).exists():
        # Don't match if test directory doesn't exist
        return False

    # ... rest of matching logic
```

**Rationale**:
- Doesn't break when used in new projects
- Doesn't require extensive configuration for standard projects
- Provides flexibility without complexity

**Date**: 2026-02-09

## Tasks

### Phase 1: Design & Documentation
- [x] ⬜ **Investigate all handlers for project-specific logic**
  - [x] ⬜ Read TDD enforcement handler
  - [x] ⬜ Survey all handlers in src/claude_code_hooks_daemon/handlers/
  - [x] ⬜ Document issues by severity
  - [x] ⬜ Research multi-language testing conventions
- [ ] ⬜ **Design configuration schema**
  - [ ] ⬜ Define `project_paths` section in YAML schema
  - [ ] ⬜ Define handler-level overrides
  - [ ] ⬜ Update config validation
  - [ ] ⬜ Document configuration options
- [ ] ⬜ **Extend LanguageConfig for test patterns**
  - [ ] ⬜ Add `test_file_patterns` field
  - [ ] ⬜ Add `test_directory` field
  - [ ] ⬜ Create configs for: Go, PHP, TypeScript, Rust, Java
  - [ ] ⬜ Write tests for language detection

### Phase 2: Core Infrastructure (TDD)
- [ ] ⬜ **Implement ProjectPaths utility class**
  - [ ] ⬜ Write failing tests for path resolution
  - [ ] ⬜ Implement ProjectPaths.get_test_directory()
  - [ ] ⬜ Implement ProjectPaths.get_plan_directory()
  - [ ] ⬜ Implement ProjectPaths.get_source_directory()
  - [ ] ⬜ Add fallback to smart defaults
  - [ ] ⬜ Run full QA suite
- [ ] ⬜ **Extend LanguageConfig system**
  - [ ] ⬜ Write failing tests for test pattern matching
  - [ ] ⬜ Add test_file_patterns to LanguageConfig
  - [ ] ⬜ Implement pattern substitution ({filename}, {basename})
  - [ ] ⬜ Update language registry
  - [ ] ⬜ Run full QA suite

### Phase 3: Refactor Critical Handlers (TDD)
- [ ] ⬜ **Refactor TddEnforcementHandler (CRITICAL)**
  - [ ] ⬜ Write failing tests for multi-language support
  - [ ] ⬜ Replace hardcoded paths with ProjectPaths
  - [ ] ⬜ Add language detection via LanguageConfig
  - [ ] ⬜ Support all test file patterns
  - [ ] ⬜ Update error messages to be language-aware
  - [ ] ⬜ Verify 95%+ coverage
  - [ ] ⬜ Run full QA suite
  - [ ] ⬜ Restart daemon successfully
  - [ ] ⬜ Test with Python, Go, TypeScript files
- [ ] ⬜ **Refactor MarkdownOrganizationHandler (CRITICAL)**
  - [ ] ⬜ Write failing tests for configurable paths
  - [ ] ⬜ Replace hardcoded CLAUDE/ with config
  - [ ] ⬜ Replace hardcoded docs/ with config
  - [ ] ⬜ Make page patterns configurable
  - [ ] ⬜ Update guidance messages
  - [ ] ⬜ Run full QA suite
  - [ ] ⬜ Restart daemon successfully
- [ ] ⬜ **Refactor Plan-related handlers (CRITICAL)**
  - [ ] ⬜ ValidatePlanNumberHandler: use ProjectPaths
  - [ ] ⬜ PlanNumberHelperHandler: use ProjectPaths
  - [ ] ⬜ PlanWorkflowHandler: use ProjectPaths
  - [ ] ⬜ PlanCompletionAdvisorHandler: use ProjectPaths
  - [ ] ⬜ Run full QA suite for each
  - [ ] ⬜ Restart daemon successfully

### Phase 4: Refactor Moderate Severity Handlers (TDD)
- [ ] ⬜ **Make QA suppression blockers configurable**
  - [ ] ⬜ Move skip_directories to config
  - [ ] ⬜ Update PythonQaSuppressionBlocker
  - [ ] ⬜ Update GoQaSuppressionBlocker
  - [ ] ⬜ Update PhpQaSuppressionBlocker
  - [ ] ⬜ Run full QA suite
- [ ] ⬜ **Make EslintDisableHandler configurable**
  - [ ] ⬜ Move extensions to config
  - [ ] ⬜ Move skip directories to config
  - [ ] ⬜ Run full QA suite

### Phase 5: Update Project Configuration
- [ ] ⬜ **Update .claude/hooks-daemon.yaml for this project**
  - [ ] ⬜ Add project_paths section
  - [ ] ⬜ Set plan_directory: "CLAUDE/Plan"
  - [ ] ⬜ Set test_directory: "tests"
  - [ ] ⬜ Set source_directory: "src"
  - [ ] ⬜ Update handler configs to use new system
  - [ ] ⬜ Verify daemon restarts successfully
- [ ] ⬜ **Update documentation**
  - [ ] ⬜ Update CLAUDE.md with configuration guide
  - [ ] ⬜ Add multi-language support docs
  - [ ] ⬜ Create examples for different project types
  - [ ] ⬜ Update handler development guide

### Phase 6: Testing & Validation
- [ ] ⬜ **Integration testing**
  - [ ] ⬜ Test with Python project structure
  - [ ] ⬜ Test with Go project structure
  - [ ] ⬜ Test with TypeScript project structure
  - [ ] ⬜ Test with non-standard paths
  - [ ] ⬜ Test with missing directories (graceful degradation)
- [ ] ⬜ **Dogfooding verification**
  - [ ] ⬜ All dogfooding tests pass
  - [ ] ⬜ Daemon restarts successfully
  - [ ] ⬜ No behavior changes for this project
- [ ] ⬜ **Full QA suite**
  - [ ] ⬜ Run ./scripts/qa/run_all.sh
  - [ ] ⬜ All checks pass with ZERO failures

## Dependencies

- None (self-contained work)

## Success Criteria

- [ ] All handlers use configuration for paths (no hardcoded project-specific paths)
- [ ] TDD enforcement supports Python, Go, PHP, TypeScript, Rust, Java
- [ ] Handlers gracefully degrade when paths don't exist
- [ ] This project continues to work identically (dogfooding)
- [ ] Documentation includes examples for multiple project types
- [ ] All QA checks pass
- [ ] Daemon restarts successfully
- [ ] 95%+ test coverage maintained
- [ ] No breaking changes to existing handler APIs

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Breaking existing functionality | High | Medium | TDD + dogfooding tests catch regressions |
| Config complexity overwhelming users | Medium | Medium | Smart defaults, minimal required config |
| Performance impact from path lookups | Low | Low | Cache resolved paths in ProjectContext |
| Incomplete language coverage | Medium | High | Start with top 5 languages, document extension pattern |
| Migration effort too large | High | Medium | Phased approach, prioritize by severity |

## Timeline

- Phase 1 (Design): 1 day
- Phase 2 (Infrastructure): 1 day
- Phase 3 (Critical handlers): 1.5 days
- Phase 4 (Moderate handlers): 0.5 days
- Phase 5 (Config & docs): 0.5 days
- Phase 6 (Testing): 0.5 days
- **Target Completion**: 2026-02-14 (5 days)

## Notes & Updates

### 2026-02-09: Plan Created

Initial investigation complete. Key findings:

1. **11 handlers affected** (6 critical, 4 moderate, 1 low)
2. **TDD handler is worst offender** - Python-only, hardcoded paths
3. **Plan handlers all need work** - CLAUDE/Plan/ assumptions throughout
4. **Good pattern exists** - QA suppression blockers use LanguageConfig (just needs skip_directories made configurable)

**Most important fix**: TDD enforcement handler - blocks multi-language TDD enforcement entirely.

**Research findings**:
- ESLint uses glob patterns in `files` property for test matching
- Pytest uses configurable naming conventions (python_files, python_classes, python_functions)
- Language-agnostic testing is growing trend (TESTed framework example)
- Most languages follow suffix-based conventions (Go, PHP, Java, C#)
- Python is outlier with prefix convention (`test_*.py`)
- JavaScript/TypeScript support both `.test` and `.spec` suffixes

**Design approach**:
- Configuration-driven (YAML project_paths section)
- Multi-language via extended LanguageConfig
- Smart defaults with opt-out
- Graceful degradation
- No breaking changes for this project

**Next steps**: Get approval, begin Phase 1 implementation.

## Research Sources

- [ESLint Configuration Files](https://eslint.org/docs/latest/use/configure/configuration-files)
- [ESLint v10.0.0 Testing Enhancements](https://eslint.org/blog/2026/02/eslint-v10.0.0-released/)
- [Pytest Test Discovery Conventions](https://www.learnthatstack.com/interview-questions/testing/pytest/what-are-the-naming-conventions-for-pytest-test-discovery-25718)
- [Language-Agnostic Testing - TESTed Framework](https://www.sciencedirect.com/science/article/pii/S2352711023001000)
- [Go Testing Frameworks 2026](https://speedscale.com/blog/golang-testing-frameworks-for-every-type-of-test/)
