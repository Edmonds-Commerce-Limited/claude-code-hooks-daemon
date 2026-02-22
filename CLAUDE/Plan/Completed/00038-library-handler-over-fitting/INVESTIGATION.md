# Investigation Report: Library Handler Over-fitting

**Date**: 2026-02-09
**Investigator**: Claude Code Agent
**Scope**: All handlers in `src/claude_code_hooks_daemon/handlers/`

## Executive Summary

Investigation identified **11 handlers with project-specific assumptions** that violate library design principles. The most critical issue is **TddEnforcementHandler**, which only supports Python and hardcodes test file paths, making it unusable for Go, PHP, TypeScript, and other languages.

**Impact**: Medium-to-high severity. The daemon is marketed as a library but several core handlers are project-specific, limiting adoption.

**Recommendation**: Phased refactoring using configuration-driven approach and multi-language support via extended LanguageConfig system.

## Methodology

1. **Code Review**: Read all handler implementations
2. **Pattern Analysis**: Identified hardcoded paths, language assumptions, project-specific logic
3. **Severity Classification**: Categorized by impact on library usability
4. **Research**: Investigated multi-language testing conventions and configuration best practices

## Detailed Findings

### Critical Severity (6 handlers)

#### 1. TddEnforcementHandler

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/tdd_enforcement.py`

**Issues**:
```python
# Line 44: Only checks Python files
if not file_path.endswith(".py"):
    return False

# Line 54: Hardcoded Python test convention
if "/tests/" in file_path or filename.startswith("test_"):
    return False

# Line 59: Hardcoded path patterns
return bool("handlers/" in file_path or "/src/" in file_path)

# Line 115: Hardcoded test file naming
test_filename = f"test_{handler_filename}"

# Line 122-141: Hardcoded path structure
if "claude_code_hooks_daemon" in path_parts and "handlers" in path_parts:
    workspace_root = Path(*workspace_parts) if workspace_parts else Path("/workspace")
    test_file_path = workspace_root / "tests" / "unit" / "handlers" / event_type / test_filename
```

**Impact**:
- ❌ Cannot enforce TDD for Go projects (`*_test.go`)
- ❌ Cannot enforce TDD for PHP projects (`*Test.php`)
- ❌ Cannot enforce TDD for TypeScript projects (`*.test.ts`, `*.spec.ts`)
- ❌ Cannot enforce TDD for Rust, Java, Ruby, C#
- ❌ Assumes specific directory structure (`tests/unit/handlers/`)
- ❌ Hardcoded workspace root fallback

**Severity**: **CRITICAL** - Completely blocks multi-language TDD support

#### 2. MarkdownOrganizationHandler

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/markdown_organization.py`

**Issues**:
```python
# Line 44: Hardcoded plan path
if "CLAUDE/Plan/" in normalized and normalized.lower().endswith("/plan.md"):

# Line 76-77: Hardcoded project markers
project_markers = ["CLAUDE/", "src/", ".claude/", "docs/", "eslint-rules/", "untracked/"]

# Line 129: Hardcoded page pattern (project-specific!)
re.match(r"^src/pages/articles/.*/article-[^/]+\.md$", normalized, re.IGNORECASE)

# Line 378-397: Hardcoded directory structure
if normalized.lower().startswith("claude/"):
    if normalized.lower().startswith("claude/plan/"):
        # Hardcoded format validation
```

**Impact**:
- ❌ Only works for projects with `CLAUDE/` directory
- ❌ Hardcoded `eslint-rules/` is project-specific
- ❌ `src/pages/articles/` pattern is specific to one project
- ❌ Cannot customize allowed markdown locations

**Severity**: **CRITICAL** - Forces specific directory structure

#### 3. ValidatePlanNumberHandler

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/validate_plan_number.py`

**Issues**:
```python
# Line 69: Hardcoded plan path pattern
if re.search(r"CLAUDE/Plan/(\d{3})-([^/]+)/", file_path):

# Line 176: Hardcoded plan root
plan_root = self.workspace_root / "CLAUDE/Plan"

# Line 189: Hardcoded completed subdirectory
completed_dir = plan_root / "Completed"
```

**Impact**:
- ❌ Only works for projects using `CLAUDE/Plan/` structure
- ❌ Assumes `Completed/` subdirectory
- ❌ Assumes 3-digit numbering format

**Severity**: **CRITICAL** - Planning workflow is project-specific

#### 4. PlanNumberHelperHandler

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_number_helper.py`

**Issues**:
```python
# Line 72: Config-based but still assumes structure
plan_dir = self._track_plans_in_project

# Line 90-91: Hardcoded path patterns in detection
rf"find\s+{re.escape(plan_dir)}",

# Line 138: Assumes specific plan base structure
plan_base = self._workspace_root / self._track_plans_in_project
```

**Impact**:
- ✓ Better than others (uses config)
- ❌ Still assumes plan directory structure
- ❌ Detection patterns are rigid

**Severity**: **CRITICAL** (but better than siblings)

#### 5. PlanWorkflowHandler

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_workflow.py`

**Issues**:
```python
# Line 44: Hardcoded plan path
return "CLAUDE/Plan/" in normalized and normalized.lower().endswith("/plan.md")

# Line 57: Hardcoded workflow doc reference
"See CLAUDE/PlanWorkflow.md for full guidelines."
```

**Impact**:
- ❌ Only matches `CLAUDE/Plan/*/PLAN.md` files
- ❌ References specific documentation file

**Severity**: **CRITICAL** - Planning feature unusable elsewhere

#### 6. PlanCompletionAdvisorHandler

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_completion_advisor.py`

**Issues**:
```python
# Line 21: Hardcoded plan path pattern
_PLAN_PATH_PATTERN = re.compile(r"CLAUDE/Plan/(\d+-[^/]+)/PLAN\.md$", re.IGNORECASE)

# Line 102-103: Hardcoded git mv advice
f"1. Move to Completed/: git mv CLAUDE/Plan/{folder_name} "
f"CLAUDE/Plan/Completed/\n"
```

**Impact**:
- ❌ Only works for `CLAUDE/Plan/` structure
- ❌ Assumes `Completed/` subdirectory
- ❌ Git advice is project-specific

**Severity**: **CRITICAL** - Planning completion workflow locked to structure

### Moderate Severity (4 handlers)

#### 7-9. QA Suppression Blockers (Python, Go, PHP)

**Files**:
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/python_qa_suppression_blocker.py`
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/go_qa_suppression_blocker.py`
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/php_qa_suppression_blocker.py`

**Issues**:
```python
# All three handlers (Lines 49-50):
if any(skip in file_path for skip in PYTHON_CONFIG.skip_directories):
    return False

# LanguageConfig has hardcoded skip directories:
skip_directories=(
    "tests/fixtures/",  # May not match all projects
    "migrations/",      # Django-specific
    "vendor/",
    ".venv/",
    "venv/",
),
```

**Impact**:
- ✓ Good pattern: Uses LanguageConfig
- ❌ Skip directories may not match other projects
- ⚠️ `migrations/` is Django-specific
- ⚠️ Projects might use different venv names

**Severity**: **MODERATE** - Mostly good, minor adjustments needed

#### 10. EslintDisableHandler

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/eslint_disable.py`

**Issues**:
```python
# Line 27: Hardcoded extensions
CHECK_EXTENSIONS: ClassVar[list[str]] = [".ts", ".tsx", ".js", ".jsx"]

# Line 58: Hardcoded skip directories
if any(skip in file_path for skip in ["node_modules", "dist", ".build", "coverage"]):
```

**Impact**:
- ⚠️ Extensions are common but not configurable
- ⚠️ Skip directories are typical but not all projects use them
- ⚠️ `.build` might be project-specific

**Severity**: **MODERATE** - Common conventions but inflexible

### Low Severity (1 handler)

#### 11. DaemonRestartVerifierHandler

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/daemon_restart_verifier.py`

**Issues**:
```python
# Line 62: Intentionally project-specific
if not is_hooks_daemon_repo(self._workspace_root):
    return False

# Line 91: Hardcoded command
"$PYTHON -m claude_code_hooks_daemon.daemon.cli restart\n"
```

**Impact**:
- ✓ Intentional: This is a dogfooding handler
- ✓ Uses `is_hooks_daemon_repo()` check (proper)
- ⚠️ Command is project-specific but documented

**Severity**: **LOW** - Intentionally project-specific (dogfooding)

## Pattern Analysis

### Anti-patterns Found

1. **Hardcoded Paths**: `CLAUDE/Plan/`, `/workspace`, `tests/unit/`
2. **Single Language**: Python-only assumptions
3. **Hardcoded Conventions**: `test_*.py`, `.py` only
4. **Project-Specific Logic**: `src/pages/articles/`, `eslint-rules/`
5. **Magic Strings**: Directory names scattered throughout

### Good Patterns Found

1. **LanguageConfig System**: QA suppression blockers use this well
2. **Configuration-Based**: Some handlers read from YAML
3. **ProjectContext**: Used for workspace root
4. **Graceful Checks**: Some handlers check if directories exist

## Impact Assessment

### Current State
- ✅ Works perfectly for this project (dogfooding)
- ❌ Breaks or is useless in other projects
- ❌ Cannot support multi-language projects
- ❌ Forces specific directory structure

### Desired State
- ✅ Works for any project structure
- ✅ Supports all major languages
- ✅ Configuration-driven with smart defaults
- ✅ Still works perfectly for this project (backward compatible)

## Root Cause Analysis

**Why did this happen?**

1. **Evolution**: Daemon started as project-specific tool, became library later
2. **Dogfooding Priority**: Focus on making it work for this project first
3. **Time Pressure**: Quick implementation without generalization
4. **Lack of Design Review**: No library design checklist
5. **Missing Tests**: No tests with different project structures

**Why wasn't it caught earlier?**

1. **No Multi-Project Testing**: All tests use this project's structure
2. **No External Users**: Hasn't been adopted widely yet
3. **Documentation Implied Generic**: Docs didn't reveal limitations
4. **Dogfooding Blindness**: Working perfectly here masked the issue

## Comparison: Industry Standards

### ESLint Configuration
- ✅ Glob patterns for file matching
- ✅ Overrides per file pattern
- ✅ No hardcoded paths
- ✅ Language-agnostic core

### Pytest Configuration
- ✅ Configurable naming conventions (`python_files`, `python_classes`)
- ✅ Configurable test discovery paths
- ✅ Per-project customization
- ✅ Smart defaults

### Our Handlers (Current)
- ❌ Hardcoded paths
- ❌ Python-only for TDD
- ❌ No configuration options
- ❌ Not reusable

### Our Handlers (Target)
- ✅ Configuration-driven paths
- ✅ Multi-language support
- ✅ Smart defaults with overrides
- ✅ Fully reusable

## Recommendations

### Immediate Actions
1. **Fix TddEnforcementHandler** (highest priority) - blocks multi-language use
2. **Add configuration schema** for project paths
3. **Extend LanguageConfig** for test file patterns

### Short-term Actions
1. **Refactor plan handlers** to use configuration
2. **Make skip directories configurable** in QA blockers
3. **Update documentation** with examples

### Long-term Actions
1. **Test with multiple project types** (Go, PHP, TypeScript)
2. **Create handler design checklist** to prevent future over-fitting
3. **Add CI test suite** with different project structures

## Proposed Solution Summary

**Approach**: Configuration-driven with LanguageConfig extension

**Key Components**:
1. `project_paths` section in YAML config
2. Extended `LanguageConfig` with test patterns
3. `ProjectPaths` utility for path resolution
4. Smart defaults with graceful degradation

**Benefits**:
- ✅ Backward compatible (this project unchanged)
- ✅ Supports all major languages
- ✅ Flexible for any project structure
- ✅ Maintains existing API

**Migration Path**:
- Phase 1: Add infrastructure (config, LanguageConfig)
- Phase 2: Refactor critical handlers (TDD, plans)
- Phase 3: Refactor moderate handlers (QA blockers)
- Phase 4: Update documentation and examples

## Test Cases Required

### Multi-Language TDD Enforcement
```python
def test_tdd_enforcement_python():
    # src/auth.py requires tests/test_auth.py
    pass

def test_tdd_enforcement_go():
    # pkg/auth/auth.go requires pkg/auth/auth_test.go
    pass

def test_tdd_enforcement_typescript():
    # src/Button.tsx requires Button.test.tsx or Button.spec.tsx
    pass

def test_tdd_enforcement_php():
    # src/Auth/Service.php requires tests/Auth/ServiceTest.php
    pass
```

### Custom Path Configuration
```python
def test_custom_plan_directory():
    # planning/active/ instead of CLAUDE/Plan/
    pass

def test_custom_test_directory():
    # spec/ instead of tests/
    pass

def test_custom_source_directory():
    # lib/ instead of src/
    pass
```

### Graceful Degradation
```python
def test_missing_test_directory():
    # Handler doesn't enforce if tests/ doesn't exist
    pass

def test_unconfigured_project():
    # Smart defaults work for standard structures
    pass
```

## Conclusion

The investigation reveals a systemic issue: **handlers are over-fit to this project's structure**. This violates library design principles and limits adoption.

**Good news**:
- Problem is well-understood
- Solution is clear (configuration + LanguageConfig)
- Backward compatibility is achievable
- Phased implementation is feasible

**Action required**: Approve plan and begin Phase 1 implementation.

## Appendix: Handler Inventory

| Handler | File | Severity | Primary Issue |
|---------|------|----------|---------------|
| TddEnforcementHandler | `tdd_enforcement.py` | CRITICAL | Python-only, hardcoded paths |
| MarkdownOrganizationHandler | `markdown_organization.py` | CRITICAL | Hardcoded CLAUDE/ structure |
| ValidatePlanNumberHandler | `validate_plan_number.py` | CRITICAL | Hardcoded CLAUDE/Plan/ |
| PlanNumberHelperHandler | `plan_number_helper.py` | CRITICAL | Rigid path assumptions |
| PlanWorkflowHandler | `plan_workflow.py` | CRITICAL | Hardcoded plan paths |
| PlanCompletionAdvisorHandler | `plan_completion_advisor.py` | CRITICAL | Hardcoded git advice |
| PythonQaSuppressionBlocker | `python_qa_suppression_blocker.py` | MODERATE | Hardcoded skip dirs |
| GoQaSuppressionBlocker | `go_qa_suppression_blocker.py` | MODERATE | Hardcoded skip dirs |
| PhpQaSuppressionBlocker | `php_qa_suppression_blocker.py` | MODERATE | Hardcoded skip dirs |
| EslintDisableHandler | `eslint_disable.py` | MODERATE | Hardcoded extensions/skip dirs |
| DaemonRestartVerifierHandler | `daemon_restart_verifier.py` | LOW | Intentional (dogfooding) |

**Total**: 11 handlers affected (6 critical, 4 moderate, 1 low)
