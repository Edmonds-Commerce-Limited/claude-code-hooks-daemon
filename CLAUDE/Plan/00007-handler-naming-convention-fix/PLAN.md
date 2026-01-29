# Plan 007: Fix Handler Naming Convention Conflict

**Status**: Ready for Implementation
**Priority**: HIGH - Blocking test failures and linter conflicts
**Created**: 2026-01-28
**Agent**: Opus Analysis + Sonnet Implementation

---

## Problem Statement

There is a **critical naming convention conflict** causing:
- Test failures (1 failing test)
- Linter/formatter fights (reverting manual fixes)
- Runtime config lookup failures
- Developer confusion

### The Conflict

Multiple implementations of `_to_snake_case()` produce **different results**:

| Implementation | Location | Strips Suffix? | Example Output |
|----------------|----------|----------------|----------------|
| Runtime (CORRECT) | `registry.py:281-299` | ✅ YES | `suggest_status_line` |
| Runtime (CORRECT) | `validator.py:124-141` | ✅ YES | `suggest_status_line` |
| Template (WRONG) | `init_config.py` | ❌ NO | `suggest_status_line_handler` |
| Test Helper (WRONG) | `test_init_config.py:21-24` | ❌ NO | `suggest_status_line_handler` |

**Impact**: When the daemon reads config, it looks for `suggest_status_line` but the template generates `suggest_status_line_handler`, causing handler registration failures.

---

## Root Cause Analysis

### Evidence Supporting "NO SUFFIX" Convention

1. **Runtime Code Explicitly Strips Suffix**
   ```python
   # registry.py:281-299 and validator.py:124-141
   def _to_snake_case(name: str) -> str:
       s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
       snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

       # Strip _handler suffix to match config keys
       if snake.endswith("_handler"):
           snake = snake[:-8]  # Remove "_handler"

       return snake
   ```

2. **Unit Tests Verify Stripping**
   - `test_registry.py:362-400` - Tests verify suffix stripping
   - `test_handler_name_validation.py:9-11` - Comment states: "Handler config keys do NOT include _handler suffix. Class DestructiveGitHandler -> config key 'destructive_git'"

3. **Production Config Uses No Suffix**
   - `.claude/hooks-daemon.yaml` mostly correct: `destructive_git`, `sed_blocker`, `absolute_path`
   - Only recent additions have wrong suffix (status_line handlers)

### Why Template Is Wrong

The `init_config.py` template was created with ALL handler keys using `_handler` suffix, contradicting the runtime convention. This creates a conflict loop:

1. Template generates config with `_handler` suffix
2. Linter/formatter sees template, thinks that's the standard
3. Linter "fixes" manual corrections back to wrong format
4. Runtime code can't find handlers (looking for `suggest_status_line` but config has `suggest_status_line_handler`)

---

## Correct Convention (Authoritative)

**Config keys should NOT have `_handler` suffix**

| Class Name | Config Key |
|------------|------------|
| `DestructiveGitHandler` | `destructive_git` |
| `SedBlockerHandler` | `sed_blocker` |
| `SuggestStatusLineHandler` | `suggest_status_line` |
| `BashErrorDetectorHandler` | `bash_error_detector` |
| `PlanNumberHelperHandler` | `plan_number_helper` |

**Rationale**:
- Brevity: More readable config files
- Consistency: Matches runtime behavior
- Validation: Enables typo detection
- Convention: Python packages don't include module type in imports

---

## Implementation Plan

### Phase 1: Fix Config Template (init_config.py)

**File**: `/workspace/src/claude_code_hooks_daemon/daemon/init_config.py`

**Method**: `generate_full()` lines 82-159

**Changes Required** (21 handler keys):

```yaml
# Line 98: PreToolUse handlers
destructive_git_handler: -> destructive_git:
sed_blocker_handler: -> sed_blocker:
absolute_path_handler: -> absolute_path:
worktree_file_copy_handler: -> worktree_file_copy:
git_stash_handler: -> git_stash:

# Line 105: Code Quality handlers
eslint_disable_handler: -> eslint_disable:
python_qa_suppression_blocker: (already correct - no Handler suffix in class)
php_qa_suppression_blocker: (already correct)
go_qa_suppression_blocker: (already correct)
tdd_enforcement_handler: -> tdd_enforcement:

# Line 112: Workflow handlers
gh_issue_comments_handler: -> gh_issue_comments:
web_search_year_handler: -> web_search_year:

# Line 116: Tool usage
british_english_handler: -> british_english:

# Line 120: PostToolUse
bash_error_detector_handler: -> bash_error_detector:

# Line 127: Notification
notification_logger_handler: -> notification_logger:

# Line 134: SessionStart
suggest_status_line_handler: -> suggest_status_line:

# Line 138: SessionEnd
cleanup_handler: -> cleanup:

# Line 145: SubagentStop
subagent_completion_logger_handler: -> subagent_completion_logger:

# Line 149: PreCompact
transcript_archiver_handler: -> transcript_archiver:

# Line 153-155: StatusLine
model_context_handler: -> model_context:
git_branch_handler: -> git_branch:
daemon_stats_handler: -> daemon_stats:
```

**Implementation Notes**:
- These are in YAML template strings
- Use search/replace to ensure consistency
- Verify no other handler keys exist in the template

---

### Phase 2: Fix Test Helper Function (test_init_config.py)

**File**: `/workspace/tests/daemon/test_init_config.py`

#### Change 1: Update `_to_snake_case` (lines 21-24)

**Current (WRONG)**:
```python
def _to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
```

**Fixed (CORRECT)**:
```python
def _to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case with _handler suffix stripped."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    # Strip _handler suffix to match config keys
    if snake.endswith("_handler"):
        snake = snake[:-8]  # Remove "_handler"

    return snake
```

#### Change 2: Update `EXCLUDED_HANDLERS` Set (lines 333-362)

**Current (WRONG)** - All entries have `_handler` suffix:
```python
EXCLUDED_HANDLERS: ClassVar[set[str]] = {
    "validate_plan_number_handler",
    "plan_time_estimates_handler",
    ...
    "suggest_status_line_handler",
}
```

**Fixed (CORRECT)** - Remove `_handler` from all entries:
```python
EXCLUDED_HANDLERS: ClassVar[set[str]] = {
    # Plan workflow handlers - require CLAUDE/Plan/ directory structure
    "validate_plan_number",
    "plan_time_estimates",
    "plan_workflow",
    "plan_number_helper",
    "markdown_organization",
    # NPM handler - project-specific
    "npm_command",
    # Permission handlers - YOLO mode doesn't use these
    "auto_approve_reads",
    # Git context injector - optional
    "git_context_injector",
    # Workflow restoration - optional
    "workflow_state_restoration",
    "workflow_state_pre_compact",
    # YOLO container detection - auto-detects
    "yolo_container_detection",
    # Reminder handlers - optional
    "remind_prompt_library",
    "remind_validator",
    # Stop handlers - optional
    "auto_continue_stop",
    "task_completion_checker",
    # ESLint validation - optional
    "validate_eslint_on_write",
    "validate_sitemap",
    # Status line handlers - project-specific
    "suggest_status_line",
}
```

---

### Phase 3: Fix Production Config (.claude/hooks-daemon.yaml)

**File**: `/workspace/.claude/hooks-daemon.yaml`

**Changes Required** (4 handler keys):

```yaml
# Line 113: SessionStart
suggest_status_line_handler: -> suggest_status_line:

# Lines 153-161: StatusLine section
model_context_handler: -> model_context:
git_branch_handler: -> git_branch:
daemon_stats_handler: -> daemon_stats:
```

**Note**: Most handlers in this file are already correct (`destructive_git`, `sed_blocker`, etc.). Only recently added handlers have the wrong suffix.

---

### Phase 4: Add Validation to Prevent Future Conflicts

**File**: `/workspace/tests/daemon/test_init_config.py`

**Add New Test Method** to `TestConfigHandlerCoverage` class:

```python
def test_template_handler_keys_match_runtime_convention(self):
    """CRITICAL: Verify template uses same naming convention as runtime registry.

    This test prevents the handler naming conflict where:
    - Runtime code strips _handler suffix: DestructiveGitHandler -> 'destructive_git'
    - Template was using suffix: 'destructive_git_handler'
    - Result: Config lookup failures at runtime

    The CORRECT convention is: config keys do NOT have _handler suffix.
    """
    from claude_code_hooks_daemon.handlers.registry import _to_snake_case as registry_snake_case

    # Parse the generated template
    config_yaml = generate_config(mode="full")
    config = yaml.safe_load(config_yaml)

    violations = []

    for event_type, handlers in config["handlers"].items():
        if not isinstance(handlers, dict):
            continue

        for handler_key in handlers.keys():
            # The key should NOT end with _handler (per runtime convention)
            if handler_key.endswith("_handler"):
                violations.append(f"{event_type}.{handler_key}")

    assert not violations, (
        f"Handler keys in template end with '_handler' (WRONG):\n"
        f"  {violations}\n\n"
        f"Config keys should match runtime convention (no _handler suffix).\n"
        f"Runtime strips suffix: DestructiveGitHandler -> 'destructive_git'\n"
        f"Template must match: 'destructive_git' NOT 'destructive_git_handler'\n\n"
        f"Fix in: src/claude_code_hooks_daemon/daemon/init_config.py"
    )
```

**Purpose**: This test will fail immediately if anyone adds a handler key with `_handler` suffix to the template, preventing future conflicts.

---

### Phase 5: Documentation Update

**File**: `/workspace/CLAUDE/HANDLER_DEVELOPMENT.md`

**Add New Section** after "Handler Priority Ranges":

```markdown
## Handler Naming Convention

### Class Names vs Config Keys

**CRITICAL**: Config keys do NOT include the `_handler` suffix.

Handler classes follow the pattern `<Name>Handler`:
- `DestructiveGitHandler`
- `SedBlockerHandler`
- `SuggestStatusLineHandler`
- `BashErrorDetectorHandler`

Config keys **strip the `Handler` suffix** and use snake_case:

| Class Name | Config Key (CORRECT) | Config Key (WRONG) |
|------------|----------------------|--------------------|
| `DestructiveGitHandler` | `destructive_git` | ~~`destructive_git_handler`~~ |
| `SedBlockerHandler` | `sed_blocker` | ~~`sed_blocker_handler`~~ |
| `SuggestStatusLineHandler` | `suggest_status_line` | ~~`suggest_status_line_handler`~~ |
| `BashErrorDetectorHandler` | `bash_error_detector` | ~~`bash_error_detector_handler`~~ |

### Why This Convention?

1. **Brevity**: Config files are more readable without redundant `_handler` suffix
2. **Consistency**: The `_to_snake_case()` function in both `registry.py` and `validator.py` strips this suffix
3. **Validation**: The config validator uses this convention to detect typos
4. **Python Convention**: Similar to how we import `from datetime import datetime` not `from datetime import datetime_class`

### Implementation Details

The conversion happens in two places:

**1. Registry (runtime handler loading)**
```python
# src/claude_code_hooks_daemon/handlers/registry.py:281-299
def _to_snake_case(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    # Strip _handler suffix to match config keys
    if snake.endswith("_handler"):
        snake = snake[:-8]

    return snake
```

**2. Validator (config validation)**
```python
# src/claude_code_hooks_daemon/config/validator.py:124-141
# Same implementation as registry
```

### Example Config

**CORRECT**:
```yaml
handlers:
  pre_tool_use:
    destructive_git:
      enabled: true
      priority: 10
    sed_blocker:
      enabled: true
      priority: 10
```

**WRONG**:
```yaml
handlers:
  pre_tool_use:
    destructive_git_handler:  # ❌ WRONG - will not load at runtime
      enabled: true
      priority: 10
```

### Testing

Run the naming convention validation test:
```bash
pytest tests/daemon/test_init_config.py::TestConfigHandlerCoverage::test_template_handler_keys_match_runtime_convention -v
```

This test ensures the template matches runtime behavior and will catch any future deviations.
```

---

## Files to Modify

| File | Lines | Changes | Risk |
|------|-------|---------|------|
| `init_config.py` | 82-159 | Remove `_handler` from 21 keys | LOW - Template only |
| `test_init_config.py` | 21-24 | Add suffix stripping logic | LOW - Test helper |
| `test_init_config.py` | 333-362 | Remove suffix from 20 exclusions | LOW - Test data |
| `test_init_config.py` | NEW | Add validation test | LOW - New test |
| `.claude/hooks-daemon.yaml` | 113, 153-161 | Fix 4 handler keys | MEDIUM - Production config |
| `HANDLER_DEVELOPMENT.md` | NEW | Document convention | LOW - Documentation |

**Total Files**: 3 source files + 1 config file + 1 doc file = 5 files
**Total Changes**: ~50 line changes

---

## Validation Strategy

### Pre-Implementation Checks

1. **Verify Current State**
   ```bash
   # Check runtime convention
   python3 -c "
   from claude_code_hooks_daemon.handlers.registry import _to_snake_case
   print(_to_snake_case('SuggestStatusLineHandler'))
   "
   # Should output: suggest_status_line
   ```

2. **Identify All Mismatches**
   ```bash
   # Find all _handler suffixes in template
   grep -n "_handler:" src/claude_code_hooks_daemon/daemon/init_config.py
   ```

3. **Check Production Config**
   ```bash
   # Find all _handler suffixes in production config
   grep -n "_handler:" .claude/hooks-daemon.yaml
   ```

### Post-Implementation Validation

1. **Run Full Test Suite**
   ```bash
   ./scripts/qa/run_tests.sh
   ```
   Expected: All tests pass (currently 1 failing)

2. **Run Naming Validation**
   ```bash
   pytest tests/daemon/test_init_config.py::TestConfigHandlerCoverage::test_template_handler_keys_match_runtime_convention -v
   ```
   Expected: PASS

3. **Verify Handler Discovery**
   ```bash
   # Test that handlers can be discovered with new config
   python3 -c "
   from claude_code_hooks_daemon.handlers.registry import HandlerRegistry
   from pathlib import Path

   registry = HandlerRegistry()
   registry.discover()

   # Should find suggest_status_line (not suggest_status_line_handler)
   handler_class = registry.get_handler_class('SuggestStatusLineHandler')
   print(f'Found: {handler_class.__name__ if handler_class else None}')
   "
   ```

4. **Test Config Generation**
   ```bash
   # Generate config and verify no _handler suffixes
   python3 -c "
   from claude_code_hooks_daemon.daemon.init_config import generate_config
   import yaml

   config = yaml.safe_load(generate_config('full'))

   for event, handlers in config['handlers'].items():
       if isinstance(handlers, dict):
           for key in handlers:
               if key.endswith('_handler'):
                   print(f'ERROR: {event}.{key} has _handler suffix')
   "
   # Should output: nothing (no errors)
   ```

---

## Risk Assessment

### Low Risk Changes
- Template modifications (generates new configs, doesn't affect existing)
- Test helper updates (test-only code)
- Documentation additions (no code impact)
- New validation test (prevents future issues)

### Medium Risk Changes
- Production config `.claude/hooks-daemon.yaml` updates
  - **Risk**: Handler registration failures if keys are wrong
  - **Mitigation**: Test with daemon restart after changes
  - **Rollback**: Keep backup of original config

### High Risk Areas (No Changes Needed)
- Runtime code in `registry.py` and `validator.py`
  - Already correct, no changes needed
  - These are the authoritative implementations

---

## Implementation Order

### Recommended Sequence

1. **Phase 1**: Fix template (`init_config.py`)
   - Prevents future conflicts
   - Template generates correct configs going forward

2. **Phase 2**: Fix test helper (`test_init_config.py`)
   - Aligns tests with runtime behavior
   - Removes test failures

3. **Phase 4**: Add validation test
   - Prevents regression
   - Documents the correct convention in tests

4. **Phase 5**: Update documentation
   - Educates future developers
   - Provides reference for correct usage

5. **Phase 3**: Fix production config (`.claude/hooks-daemon.yaml`)
   - Last step to avoid linter conflicts
   - Linter will now see correct template and leave config alone

### Why This Order?

- Fix source of truth (template) first
- Then fix tests to match source of truth
- Add protection (validation test)
- Document for maintainers
- Finally fix production config (linter won't revert it anymore)

---

## Success Criteria

### Must Achieve
- ✅ All tests pass (0 failures)
- ✅ Config template generates keys without `_handler` suffix
- ✅ Production config uses correct convention
- ✅ Validation test catches future violations
- ✅ Linter stops reverting manual fixes

### Should Achieve
- ✅ Documentation clearly explains convention
- ✅ Developers understand why suffix is stripped
- ✅ Future handler additions follow convention

### Could Achieve
- Add linter rule to enforce convention
- Automate config key validation in CI/CD
- Create migration script for old configs

---

## Rollback Plan

If issues arise during implementation:

1. **Template Issues**
   ```bash
   git checkout HEAD -- src/claude_code_hooks_daemon/daemon/init_config.py
   ```

2. **Test Failures**
   ```bash
   git checkout HEAD -- tests/daemon/test_init_config.py
   ```

3. **Production Config Issues**
   ```bash
   # Restore backup
   cp .claude/hooks-daemon.yaml.backup .claude/hooks-daemon.yaml

   # Restart daemon
   python3 -m claude_code_hooks_daemon.daemon.cli restart
   ```

4. **Complete Rollback**
   ```bash
   git reset --hard HEAD
   ```

---

## Timeline Estimate

| Phase | Effort | Duration |
|-------|--------|----------|
| Phase 1: Template fixes | 21 replacements | 10 minutes |
| Phase 2: Test helper | 2 functions | 5 minutes |
| Phase 3: Production config | 4 keys | 5 minutes |
| Phase 4: Validation test | 1 test | 10 minutes |
| Phase 5: Documentation | 1 section | 15 minutes |
| **Testing & Validation** | Full QA | 5 minutes |
| **Total** | | **50 minutes** |

---

## Related Issues

- **Current**: 1 test failure in `test_no_unknown_handlers_in_config`
- **Current**: Linter reverting manual fixes
- **Current**: Handler registration failures for status_line handlers
- **Previous**: Plan 002 fixed silent handler failures
- **Previous**: Plan 003 added planning mode integration

---

## Notes for Implementation

### Important Reminders

1. **Search/Replace Pattern**
   - Find: `(\w+)_handler:`
   - Replace: `$1:`
   - Verify each replacement manually

2. **Test Before Committing**
   ```bash
   ./scripts/qa/run_all.sh
   ```

3. **Verify Daemon Still Works**
   ```bash
   python3 -m claude_code_hooks_daemon.daemon.cli restart
   python3 -m claude_code_hooks_daemon.daemon.cli status
   ```

4. **Check Handler Counts**
   - Should still show 34 production handlers
   - No handlers should be missing

### Common Pitfalls

1. ❌ Missing a handler key in template
   - **Solution**: Use grep to verify all found

2. ❌ Updating config but not restarting daemon
   - **Solution**: Always restart daemon after config changes

3. ❌ Forgetting to update EXCLUDED_HANDLERS
   - **Solution**: Validation test will catch this

4. ❌ Linter reverting changes
   - **Solution**: Fix template FIRST, then config

---

## References

- **Authoritative Code**: `registry.py:281-299`, `validator.py:124-141`
- **Test Documentation**: `test_registry.py:362-400`, `test_handler_name_validation.py:9-11`
- **Production Config**: `.claude/hooks-daemon.yaml`
- **Template**: `init_config.py:82-159`

---

**Plan Status**: READY FOR IMPLEMENTATION
**Approved By**: Opus Analysis Agent (a0a9681)
**Assignee**: TBD
**Estimated Completion**: 2026-01-28
