# General Code Change Lifecycle

**Status**: MANDATORY for all code modifications
**Audience**: AI agents and human developers

## Overview

Standard process for any code modification that isn't a new feature or bug fix.

**Use this for**:
- Refactoring
- Documentation updates
- Configuration changes
- Test improvements
- Performance optimizations
- Code cleanup

**Don't use this for**:
- New features/handlers → Use @CLAUDE/CodeLifecycle/Features.md
- Bug fixes → Use @CLAUDE/CodeLifecycle/Bugs.md

## Quick Checklist

```bash
# 1. Make your changes
# ... edit files ...

# 2. Auto-fix formatting and linting
./scripts/qa/run_autofix.sh

# 3. Run full QA suite
./scripts/qa/run_all.sh

# 4. Verify daemon loads (MANDATORY)
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: Status: RUNNING

# 5. Commit if all pass
git add <specific files>
git commit -m "Description"
```

## Detailed Workflow

### Step 1: Make Changes

**Best Practices**:
- Keep changes focused and atomic
- One logical change per commit
- Don't mix refactoring with feature work
- Update tests when changing behavior

### Step 2: Update Tests

If you changed code behavior:
- Update existing tests
- Add new tests if needed
- Maintain 95%+ coverage

```bash
# Run tests for affected modules
pytest tests/unit/path/to/test_module.py -v

# Check coverage
pytest tests/unit/path/to/test_module.py --cov=src/path/to/module.py --cov-report=term-missing
```

### Step 3: Auto-fix Code Quality

```bash
# Run Black and Ruff auto-fix
./scripts/qa/run_autofix.sh

# This runs:
# - black src/ tests/ (formats code)
# - ruff check --fix src/ tests/ (auto-fixes lint issues)
```

### Step 4: Run Full QA Suite

```bash
./scripts/qa/run_all.sh
```

**Expected output**:
```
========================================
QA Summary
========================================
  Magic Values        : ✅ PASSED
  Format Check        : ✅ PASSED
  Linter              : ✅ PASSED
  Type Check          : ✅ PASSED
  Tests               : ✅ PASSED
  Security Check      : ✅ PASSED

Overall Status: ✅ ALL CHECKS PASSED
```

**If any check fails**: Fix issues and re-run.

### Step 5: Verify Daemon Loads (MANDATORY)

**CRITICAL**: Every code change must verify daemon still works.

```bash
# Restart daemon with your changes
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart

# Verify daemon is RUNNING
$PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Expected:
# Daemon: RUNNING
# PID: [number]
# Socket: [path] (exists)

# Check for errors
$PYTHON -m claude_code_hooks_daemon.daemon.cli logs | grep -i error

# Expected: No import errors, no loading failures
```

**Why this matters**: Even refactoring can introduce import errors, circular dependencies, or registration failures that unit tests won't catch.

**If daemon fails**: Fix the issue before committing.

### Step 6: Commit Changes

```bash
# Stage specific files (never use git add .)
git add src/path/to/file.py tests/path/to/test.py

# Write clear commit message
git commit -m "Refactor: Simplify XYZ logic

- Extract common pattern into utility function
- Update tests to match new structure
- No behavior changes

All QA checks pass, daemon loads successfully."
```

## Definition of Done Checklist

A general code change is DONE when ALL of the following are verified:

### 1. Code Quality
- [ ] Black formatted (run `./scripts/qa/run_autofix.sh`)
- [ ] Ruff linted (no violations)
- [ ] MyPy typed (strict mode, all functions typed)
- [ ] No security issues (Bandit scan passes)

### 2. Tests
- [ ] Relevant tests added/updated
- [ ] 95%+ coverage maintained
- [ ] All tests pass: `pytest tests/ -v`

### 3. Daemon Load (MANDATORY)
- [ ] Daemon restarts without errors
- [ ] No import failures in logs
- [ ] Run: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
- [ ] Verify: `$PYTHON -m claude_code_hooks_daemon.daemon.cli status` (RUNNING)

### 4. Full QA
- [ ] Run: `./scripts/qa/run_all.sh`
- [ ] Expected: "ALL CHECKS PASSED"

## Common Change Types

### Refactoring

**Before**:
```python
# Duplicated code
def handler_a():
    if condition:
        result = process()
        return result
    return None

def handler_b():
    if condition:
        result = process()
        return result
    return None
```

**After**:
```python
# Extracted common logic
def _process_if_condition(condition):
    """Common logic for condition processing."""
    if condition:
        return process()
    return None

def handler_a():
    return _process_if_condition(condition)

def handler_b():
    return _process_if_condition(condition)
```

**Checklist**:
- [ ] Extract common patterns
- [ ] Update all callers
- [ ] Maintain test coverage
- [ ] Verify behavior unchanged
- [ ] Run full QA

### Documentation Updates

**What to update**:
- Docstrings in code
- README.md
- CLAUDE/*.md files
- Configuration examples
- Inline comments (only where necessary)

**Checklist**:
- [ ] Check spelling and grammar
- [ ] Verify code examples are correct
- [ ] Update links if files moved
- [ ] Test commands/examples work
- [ ] Commit with clear message

### Configuration Changes

**Examples**:
- Adding/removing handlers from `.claude/hooks-daemon.yaml`
- Changing handler priorities
- Updating configuration schema
- Modifying defaults

**Checklist**:
- [ ] Update configuration file
- [ ] Update schema/validation if needed
- [ ] Update documentation
- [ ] Test with daemon restart
- [ ] Verify dogfooding tests pass

### Test Improvements

**Examples**:
- Adding missing test cases
- Improving test coverage
- Refactoring test utilities
- Adding integration tests

**Checklist**:
- [ ] New tests pass
- [ ] Coverage increased
- [ ] No test regressions
- [ ] Test isolation maintained
- [ ] Run full test suite

## Individual QA Commands

If you need to run checks individually:

```bash
# Format checking and auto-fix
./scripts/qa/run_format_check.sh

# Linting with auto-fix
./scripts/qa/run_lint.sh

# Type checking (strict mode)
./scripts/qa/run_type_check.sh

# Unit tests with coverage (95%+ required)
./scripts/qa/run_tests.sh

# Security scanning (Bandit)
./scripts/qa/run_security_check.sh

# Magic value detection (no magic strings/numbers)
./scripts/qa/run_magic_value_check.sh

# Run all checks
./scripts/qa/run_all.sh
```

## Git Best Practices

### Staging Files

```bash
# NEVER use git add . or git add -A
# Always add specific files
git add src/handlers/pre_tool_use/my_handler.py
git add tests/unit/handlers/pre_tool_use/test_my_handler.py
git add .claude/hooks-daemon.yaml
```

**Why**: Prevents accidentally committing:
- Secrets (.env files)
- IDE configs (.vscode/, .idea/)
- Large binaries
- Untracked temporary files

### Commit Messages

**Good commit messages**:
```
Refactor: Extract common validation logic

- Create shared validate_hook_input() utility
- Update 5 handlers to use common logic
- Remove duplicated validation code
- No behavior changes

All QA checks pass, daemon loads successfully.
```

**Bad commit messages**:
```
fix stuff
update
wip
changes
```

### Atomic Commits

**One commit per logical change**:
- ✅ Refactor validation logic
- ✅ Update documentation
- ✅ Fix typo in error message

**Not**:
- ❌ Refactor validation + add new feature + fix bug

## When to Use Other Lifecycles

| Change Description | Use This Document |
|-------------------|-------------------|
| Add new handler | @CLAUDE/CodeLifecycle/Features.md |
| Add new feature | @CLAUDE/CodeLifecycle/Features.md |
| Fix a bug | @CLAUDE/CodeLifecycle/Bugs.md |
| Refactor code | @CLAUDE/CodeLifecycle/General.md |
| Update docs | @CLAUDE/CodeLifecycle/General.md |
| Update config | @CLAUDE/CodeLifecycle/General.md |
| Improve tests | @CLAUDE/CodeLifecycle/General.md |
| Performance optimization | @CLAUDE/CodeLifecycle/General.md |

## Summary

**Remember**: Even "simple" changes need:

1. ✅ Tests updated (if behavior changes)
2. ✅ QA suite passes
3. ✅ **Daemon restarts successfully** ← **CRITICAL**
4. ✅ Clear commit message

**The daemon restart check catches issues that tests miss!**

---

**See Also**:
- @CLAUDE/CodeLifecycle/Features.md - Feature development
- @CLAUDE/CodeLifecycle/Bugs.md - Bug fixes
- @CLAUDE/CodeLifecycle/TestingPyramid.md - Understanding test layers
- @CLAUDE/PlanWorkflow.md - Planning standards
