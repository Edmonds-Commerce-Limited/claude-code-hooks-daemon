# Critical Analysis: Silent Handler Failures

## Executive Summary

**SEVERITY: CRITICAL**

Multiple handlers are **silently failing** in production. They match events but fail to process them because they're looking for wrong field names. No errors are logged, Claude Code receives success responses, and users have no indication anything is wrong.

## The Silent Failure Pattern

### What Happens

1. ✅ Event arrives (e.g., PostToolUse)
2. ✅ Handler matches (e.g., `bash-error-detector`)
3. ❌ Handler looks for wrong field (`tool_output` instead of `tool_response`)
4. ❌ Gets empty dict `{}`
5. ✅ Returns `ALLOW` (no error)
6. ✅ Claude Code receives success response
7. ❌ **Handler never actually processed the event**

### Evidence from Logs

```
2026-01-27 15:51:59,286 [DEBUG] claude_code_hooks_daemon.core.chain: Handler bash-error-detector matched event
```

Handler matched, but check the code:

```python
# bash_error_detector.py line 45
tool_output = hook_input.get("tool_output", {})  # WRONG FIELD NAME!
if not tool_output:
    return HookResult(decision=Decision.ALLOW)  # Silently fails
```

Real events have `tool_response`, not `tool_output`. The handler gets an empty dict and immediately returns ALLOW.

**Result**: Handler matches, processes nothing, returns success. NO ERRORS LOGGED.

## Why No Errors Are Logged

### 1. No Input Schema Validation

**Current State**:
- ✅ Response schemas exist (`response_schemas.py`)
- ✅ Responses to Claude Code are validated
- ❌ **NO INPUT VALIDATION** - incoming hook_input is not validated

**Impact**: Wrong field names in handlers aren't caught until real events arrive in production.

### 2. Fail-Open Architecture

**Code**: `chain.py` lines 173-174

```python
# Build final result
if final_result is None:
    final_result = HookResult.allow()
```

**Design**: If no handlers match OR all handlers fail, default to ALLOW.

**Impact**: Broken handlers silently return ALLOW instead of failing loudly.

### 3. `.get()` with Defaults

**Pattern**: Handlers use `.get("field", {})` everywhere

```python
tool_output = hook_input.get("tool_output", {})  # Returns {} if missing
```

**Impact**: Missing fields return empty dicts/strings instead of raising exceptions.

## Affected Handlers

### 1. BashErrorDetectorHandler (PostToolUse)

**Status**: SILENTLY BROKEN

**Issue**:
- Uses: `tool_output` (WRONG)
- Real events have: `tool_response` (CORRECT)
- Also expects: `exit_code` field that doesn't exist

**Impact**:
- Error detection completely non-functional
- Never detects Bash errors or warnings
- Always returns ALLOW

**Evidence**: Matches in logs but never processes actual data.

### 2. AutoApproveReadsHandler (PermissionRequest)

**Status**: NEVER MATCHES

**Issue**:
- Uses: `permission_type` and `resource` fields (WRONG)
- Real events have: `permission_suggestions` field (CORRECT)

**Impact**:
- Handler.matches() always returns False
- Never executes at all
- Completely non-functional

**Evidence**: Never appears in "matched event" logs.

### 3. NotificationLoggerHandler (Notification)

**Status**: WORKS BUT TESTS WRONG

**Issue**:
- Handler works (generic, passes through all fields)
- Tests use: `severity` field (WRONG)
- Real events have: `notification_type` field (CORRECT)

**Impact**:
- Handler functional in production
- Tests validate wrong data structure
- False sense of test coverage

## Why Claude Code Gets No Errors

### Response Flow

1. Handler matches → executes → returns `HookResult.allow()`
2. Result converted to JSON: `{"hookSpecificOutput": {"hookEventName": "PostToolUse"}}`
3. Response validates against schema (empty response is valid)
4. Claude Code receives success

### Valid Empty Responses

From `response_schemas.py`:

```python
POST_TOOL_USE_SCHEMA = {
    "type": "object",
    "properties": {
        "hookSpecificOutput": {
            "required": ["hookEventName"],  # ONLY hookEventName required
            # additionalContext and guidance are optional
        }
    }
}
```

**An empty ALLOW response is schema-valid**. Claude Code has no way to know the handler didn't actually process anything.

## Test Coverage Paradox

### The Problem

- ✅ **Tests pass** (147 tests for AutoApproveReads)
- ✅ **Coverage at 95%**
- ✅ **All QA checks pass**
- ❌ **Handlers don't work in production**

### Why Tests Don't Catch This

Tests use **mock data** that matches the handler's expectations:

```python
# Test fixture (WRONG but matches handler)
hook_input = {
    "tool_output": {"exit_code": 1, "stderr": "error"}  # Matches handler
}

# Real event (CORRECT but doesn't match handler)
hook_input = {
    "tool_response": {"stdout": "", "stderr": "error", "interrupted": False}
}
```

**Tests validate handler logic against WRONG data structures.**

## Root Cause Analysis

### How Did This Happen?

1. **Handlers written before debugging real events**
   - Developers assumed what fields would be present
   - No actual Claude Code events captured

2. **No input schema validation**
   - Only response schemas exist
   - Input structure never validated

3. **Tests written to match handler code**
   - TDD done against assumptions, not reality
   - Test data matches handler expectations, not Claude Code events

4. **Fail-open design masks errors**
   - Missing data returns empty values, not exceptions
   - Default to ALLOW hides problems

## Comparison: What SHOULD Happen

### Option A: Fail-Closed with Errors

```python
tool_response = hook_input["tool_response"]  # KeyError if missing
exit_code = tool_response["exit_code"]  # KeyError if missing
```

**Result**: Exception logged, handler fails, error visible.

### Option B: Input Schema Validation

```python
# Validate hook_input against schema
errors = validate_input("PostToolUse", hook_input)
if errors:
    logger.error("Invalid hook_input: %s", errors)
    return {"error": "Invalid input structure"}
```

**Result**: Schema violations caught early, logged, returned to Claude Code.

## Recommendations

### Immediate Actions

1. **Fix broken handlers** (dispatch python-developer agents)
   - BashErrorDetectorHandler: tool_output → tool_response, remove exit_code dependency
   - AutoApproveReadsHandler: permission_type → permission_suggestions
   - NotificationLoggerHandler tests: severity → notification_type

2. **Add input schema validation**
   - Create `input_schemas.py` alongside `response_schemas.py`
   - Validate hook_input in server.py before dispatch
   - Log validation errors, return errors to Claude Code

3. **Update debug_hooks.sh script**
   - Remove config file copying (use HOOKS_DAEMON_LOG_LEVEL env var)
   - Already implemented by python-developer agent

### Long-Term Prevention

1. **Debug-first development**
   - ALWAYS capture real events with `scripts/debug_hooks.sh` BEFORE writing handlers
   - Document in CLAUDE/DEBUGGING_HOOKS.md (already exists)

2. **Input validation in tests**
   - Add fixtures from real captured events
   - Validate test fixtures match real event structure

3. **Integration tests with real event data**
   - Test against captured real events, not mock data
   - Detect field name mismatches

4. **Monitoring and alerting**
   - Log when handlers match but return empty results
   - Alert when handlers never match expected events

## Severity Assessment

### Critical (Fix Immediately)

- **BashErrorDetectorHandler** - Completely broken error detection
- **AutoApproveReadsHandler** - Never matches, completely non-functional

### High (Fix Soon)

- **NotificationLoggerHandler tests** - Wrong field names in tests

### Medium (Architectural)

- **Add input schema validation** - Prevent future issues
- **Update development workflow** - Debug before develop

## Conclusion

Multiple handlers are silently failing in production. The fail-open architecture, lack of input validation, and test-driven development against assumptions (rather than real data) created a perfect storm where:

1. Handlers are broken
2. Tests pass
3. No errors are logged
4. Claude Code receives success responses
5. Users have no indication anything is wrong

**This is the most dangerous type of bug** - silent, undetected failures that give a false sense of security.
