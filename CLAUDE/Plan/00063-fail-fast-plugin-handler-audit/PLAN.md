# Plan 00063: FAIL FAST - Plugin Handler Bug & Error Hiding Audit

**Status**: In Progress
**Created**: 2026-02-17
**Owner**: Claude Sonnet 4.5
**Priority**: CRITICAL
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (surgical fix + comprehensive audit)

## Overview

**CRITICAL BUG**: Plugin handlers with the `Handler` class name suffix (the documented convention) are silently skipped during daemon startup. The daemon logs a warning, reports RUNNING, and continues with ZERO indication to the user that their configured protection is inactive.

**ROOT CAUSE**: Asymmetry between `PluginLoader.load_handler()` (correctly handles `Handler` suffix) and `DaemonController._load_plugins()` (only checks base class name, misses suffix).

**BIGGER PROBLEM**: This is a symptom of error hiding throughout the codebase. We need a comprehensive audit to find and eliminate ALL patterns that violate FAIL FAST principles.

## Goals

1. **Fix plugin handler suffix bug** - Make matching logic consistent
2. **Convert warning to CRASH** - If configured handler can't be registered, daemon MUST NOT START
3. **Comprehensive audit** - Find ALL error hiding patterns in codebase
4. **Enforce FAIL FAST** - Eliminate silent failures, graceful degradation, warning-and-continue
5. **Prevent regression** - Add validation to catch this pattern in code review

## Non-Goals

- Not fixing legitimate error recovery (user input validation, network retries)
- Not removing user-friendly error messages (but errors must be fatal, not warnings)
- Not changing legitimate optional features (features can be optional, but failures are not)

## Context & Background

From bug report `untracked/upstream-bug-report-plugin-handler-suffix.md`:

**The Bug**:
```python
# PluginLoader.load_handler() - CORRECT
class_name_with_suffix = f"{class_name}Handler"
if hasattr(module, class_name_with_suffix):
    handler_class_raw = getattr(module, class_name_with_suffix)  # ✅ Works

# DaemonController._load_plugins() - WRONG
expected_class = PluginLoader.snake_to_pascal(plugin_module)  # "SystemPaths"
if handler.__class__.__name__ == expected_class:              # "SystemPathsHandler" != "SystemPaths"
    event_type_str = plugin.event_type                        # ❌ Never reached
```

**Current Behavior**: Warning logged, handler silently discarded, daemon continues
**Expected Behavior**: DAEMON CRASHES IMMEDIATELY with clear error

**Historical Context**:
- Plan 00008 fixed error hiding audit (2026-02-05) - but this pattern was missed
- Security standards require FAIL FAST (CLAUDE.md)
- Engineering Principles require NO MAGIC and explicit error handling

## Tasks

### Phase 1: Fix Immediate Bug (CRITICAL)

- [x] ✅ **Fix Handler suffix matching** in `daemon/controller.py` line 258
  - [x] ✅ Change from `== expected_class` to `in (expected_class, f"{expected_class}Handler")`
  - [x] ✅ Add comment explaining the logic
- [x] ✅ **Convert warning to CRASH**
  - [x] ✅ Replace warning log with `raise RuntimeError()` with clear message
  - [x] ✅ Include handler name, class name, config path in error
  - [x] ✅ Daemon MUST NOT START if any configured handler can't be registered
- [x] ✅ **Write failing test** for bug
  - [x] ✅ Test plugin handler with `Handler` suffix loads and registers
  - [x] ✅ Test daemon crashes if handler can't be matched to config
- [x] ✅ **Verify fix**
  - [x] ✅ Test passes with fix
  - [x] ✅ Run full QA: `./scripts/qa/run_all.sh`
  - [x] ✅ Restart daemon: verify RUNNING

### Phase 2: Comprehensive Error Hiding Audit

**Audit Scope**: Scan entire codebase for error hiding patterns

#### 2.1: Pattern Detection (Automated)

- [ ] ⬜ **Write audit script**: `scripts/qa/audit_error_hiding.py`
  - [ ] ⬜ AST-based pattern detection
  - [ ] ⬜ Report findings with file/line/pattern
  - [ ] ⬜ Exit code 1 if violations found

**Patterns to Detect**:

1. **Silent try/except/pass**
   ```python
   try:
       operation()
   except Exception:
       pass  # ❌ VIOLATION
   ```

2. **Silent try/except/continue**
   ```python
   for item in items:
       try:
           process(item)
       except Exception:
           continue  # ❌ VIOLATION
   ```

3. **Warning instead of error** (in critical paths)
   ```python
   if critical_condition_failed:
       logger.warning("Problem")  # ❌ Should crash
       return  # ❌ Silently continues
   ```

4. **Returning None on error** (instead of raising)
   ```python
   def load_critical_resource():
       try:
           return resource
       except Exception:
           return None  # ❌ VIOLATION - should raise
   ```

5. **Empty except blocks**
   ```python
   try:
       operation()
   except Exception as e:
       logger.error(str(e))  # ❌ Log and continue = violation
   ```

6. **Optional chaining hiding failures**
   ```python
   result = obj.method() or default_value  # ❌ Masks method failure
   ```

7. **Graceful degradation in critical paths**
   ```python
   if not load_handler():
       logger.warning("Handler failed to load")
       # Continue anyway ❌ VIOLATION
   ```

#### 2.2: Manual Code Review (Critical Paths)

Review these critical paths manually for error hiding:

- [ ] ⬜ **Handler loading** (`PluginLoader`, `HandlerRegistry`)
- [ ] ⬜ **Config loading** (`ConfigLoader`, `DaemonController`)
- [ ] ⬜ **Daemon startup** (`server.py`, `cli.py`)
- [ ] ⬜ **Handler dispatch** (`FrontController`, `EventRouter`)
- [ ] ⬜ **Socket communication** (`server.py`, hook bash scripts)

#### 2.3: Document Findings

- [ ] ⬜ Create `untracked/error-hiding-audit-YYYYMMDD.md`
- [ ] ⬜ List all violations with:
  - File path and line number
  - Pattern type
  - Current behavior
  - Required fix
  - Risk level (Critical/High/Medium/Low)

### Phase 3: Fix All Violations (TDD)

For each violation found:

- [ ] ⬜ **Write failing test** that exposes the violation
- [ ] ⬜ **Implement fix** following FAIL FAST principles
- [ ] ⬜ **Verify test passes**
- [ ] ⬜ **Run full QA** after each fix
- [ ] ⬜ **Restart daemon** to verify no regressions

**Fix Strategies**:

1. **Silent pass → Crash**
   ```python
   # BEFORE
   try:
       operation()
   except Exception:
       pass

   # AFTER
   try:
       operation()
   except SpecificException as e:
       raise RuntimeError(f"Critical operation failed: {e}") from e
   ```

2. **Warning → Crash**
   ```python
   # BEFORE
   if critical_check_failed:
       logger.warning("Check failed")
       return

   # AFTER
   if critical_check_failed:
       raise RuntimeError("Critical check failed: <details>")
   ```

3. **Return None → Raise**
   ```python
   # BEFORE
   def load_resource():
       try:
           return resource
       except Exception:
           return None

   # AFTER
   def load_resource():
       try:
           return resource
       except Exception as e:
           raise RuntimeError(f"Failed to load resource: {e}") from e
   ```

### Phase 4: Enforcement Mechanisms

- [ ] ⬜ **Integrate audit script into QA pipeline**
  - [ ] ⬜ Add to `scripts/qa/run_all.sh` (run first, fail fast)
  - [ ] ⬜ Add to `.github/workflows/` CI checks
- [ ] ⬜ **Document FAIL FAST patterns** in CLAUDE.md
  - [ ] ⬜ Add "Error Handling Standards" section
  - [ ] ⬜ Show correct vs incorrect patterns
  - [ ] ⬜ Reference audit script
- [ ] ⬜ **Update code review checklist**
  - [ ] ⬜ Add "No error hiding" checkpoint
  - [ ] ⬜ Reference patterns to avoid

### Phase 5: Verification & Documentation

- [ ] ⬜ **Run full QA suite**: `./scripts/qa/run_all.sh`
- [ ] ⬜ **Restart daemon**: Verify RUNNING with no regressions
- [ ] ⬜ **Test plugin handler with Handler suffix**
  - [ ] ⬜ Create test plugin with `Handler` suffix
  - [ ] ⬜ Configure in yaml
  - [ ] ⬜ Verify loads and registers correctly
- [ ] ⬜ **Test crash on misconfigured handler**
  - [ ] ⬜ Create invalid plugin config
  - [ ] ⬜ Verify daemon CRASHES (not warns)
  - [ ] ⬜ Verify error message is clear
- [ ] ⬜ **Update bug report** with fix details
- [ ] ⬜ **Update CHANGELOG.md** with bug fix entry

## Dependencies

- None (critical bug, highest priority)

## Technical Decisions

### Decision 1: Warning → Crash for Plugin Loading Failures

**Context**: Currently daemon logs warning and continues when plugin handler can't be matched to config

**Options Considered**:
1. Keep warning, improve matching logic
2. Make it an error but allow daemon to start in degraded mode
3. CRASH IMMEDIATELY if any configured handler can't be registered

**Decision**: Option 3 - CRASH IMMEDIATELY

**Rationale**:
- Users have NO IDEA their protection is down with warning approach
- "Degraded mode" is meaningless if critical handlers are missing
- FAIL FAST is a core engineering principle (CLAUDE.md)
- If you configured a handler, you expect it to run - failure to load = fatal error
- Better to crash and force investigation than silently run without protection

**Date**: 2026-02-17

### Decision 2: Handler Suffix Matching Strategy

**Context**: Need to match loaded handler class name back to config entry

**Options Considered**:
1. Check both `ClassName` and `ClassNameHandler` in comparison
2. Strip `Handler` suffix from class name before comparison
3. Use path-based matching instead of class name (rebuild loader interface)

**Decision**: Option 1 - Check both variants

**Rationale**:
- Minimal change, mirrors existing logic in `PluginLoader.load_handler()`
- No interface changes required
- Clear and explicit (`in (expected, f"{expected}Handler")`)
- Can be enhanced later with path-based matching if needed

**Date**: 2026-02-17

### Decision 3: Audit Scope - All Error Hiding Patterns

**Context**: Need to audit entire codebase for error hiding violations

**Options Considered**:
1. Fix only the reported bug (plugin handler suffix)
2. Audit critical paths only (handler loading, config, daemon startup)
3. Comprehensive audit of entire codebase

**Decision**: Option 3 - Comprehensive audit

**Rationale**:
- User explicitly requested "general audit for other shitness error hiding patterns"
- Plan 00008 (2026-02-05) missed this pattern - indicates incomplete coverage
- One violation suggests others exist
- Better to find and fix ALL patterns now than repeat this process later
- Error hiding is a "pet hate" - zero tolerance is appropriate

**Date**: 2026-02-17

## Success Criteria

- [ ] Plugin handlers with `Handler` suffix load and register correctly
- [ ] Daemon CRASHES (not warns) if configured handler can't be registered
- [ ] Error message is clear and actionable
- [ ] Audit script detects ALL error hiding patterns
- [ ] ZERO error hiding violations remain in codebase
- [ ] All tests passing with 95%+ coverage
- [ ] Daemon loads successfully
- [ ] All QA checks pass
- [ ] Audit script integrated into CI/CD pipeline

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Audit finds 100+ violations | High | Medium | Prioritize by risk (Critical first), batch fixes with comprehensive testing |
| Breaking change in error handling | High | Low | Add tests first, verify no behavior changes except crash-on-error |
| Daemon becomes too strict | Medium | Low | Only crash on *configured* resource failures, not optional features |
| Performance impact from audit script | Low | Low | Run audit only in CI, not in daemon hot path |

## Notes & Updates

### 2026-02-17 - Plan Created

**User Feedback**: "silently disarded is bullshit - why are we doing this? we shuld be failing fast!"

**Key Requirements**:
1. Fix the immediate plugin handler bug
2. Convert warning to CRASH
3. Comprehensive audit for ALL error hiding patterns
4. Zero tolerance for silent failures

**Approach**:
- Surgical fix for immediate bug
- Automated pattern detection + manual review
- Fix ALL violations following TDD
- Integrate enforcement into CI/CD

**Priority**: CRITICAL - This violates core engineering principles and leaves users unprotected
