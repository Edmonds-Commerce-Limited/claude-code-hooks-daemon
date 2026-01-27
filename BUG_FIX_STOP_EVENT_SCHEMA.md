# Bug Fix: Stop Event Schema Validation Failure

## Issue Summary

**Bug**: Stop event handlers were returning JSON with `hookSpecificOutput` field, causing Claude Code schema validation to fail with "Invalid input" error.

**Severity**: Critical - Prevents error messages from reaching the agent, breaking daemon health monitoring.

**Discovered**: 2026-01-27 during integration testing in another agent session

## Root Cause

The `emit_hook_error()` function in `init.sh` was generating the same JSON format for ALL events:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "Stop",
    "additionalContext": "..."
  }
}
```

However, Claude Code's schema for Stop/SubagentStop events does NOT support `hookSpecificOutput`:

```python
STOP_SCHEMA = {
    "properties": {
        "decision": {"type": "string", "const": "block"},
        "reason": {"type": "string"},
    },
    "additionalProperties": False  # Blocks hookSpecificOutput!
}
```

This caused schema validation failures, preventing error messages from reaching the agent.

## Impact

1. **Silent Failures**: When daemon startup failed, the Stop hook error was rejected by Claude Code
2. **No Agent Notification**: Agent never saw that hooks protection was down
3. **Safety Risk**: Work could continue without safety guardrails
4. **DRY Violation**: Error message generation duplicated in 3 places (bash jq, bash fallback, Python)

## Fix

Created centralized error response generation using existing `HookResult` infrastructure:

### 1. New Module: `src/claude_code_hooks_daemon/core/error_response.py`

CLI utility that generates event-appropriate error JSON:

```python
def generate_daemon_error_response(
    event_name: str, error_type: str, error_details: str
) -> dict:
    # For Stop/SubagentStop: use deny decision (shows as blocked)
    if event_name in ("Stop", "SubagentStop"):
        result = HookResult.deny(reason="...", context=[...])
    else:
        # For other events: use allow with context
        result = HookResult.allow(context=[...])

    # Leverages existing to_json() for proper formatting
    return result.to_json(event_name)
```

### 2. Updated `init.sh`

**Before** (73 lines of duplicated code):
- Bash `emit_hook_error()` with jq - 48 lines
- Bash fallback without jq - 3 lines
- Python `emit_error_json()` - 22 lines

**After** (6 lines total):
```bash
emit_hook_error() {
    # Uses Python utility for event-specific formatting
    $PYTHON_CMD -m claude_code_hooks_daemon.core.error_response \
        "$event_name" "$error_type" "$error_details"
}
```

### 3. Comprehensive Test Coverage

Added `tests/unit/core/test_error_response.py` with 27 tests:
- Event-specific format validation for all 10 event types
- Schema compliance verification using `validate_response()`
- CLI interface testing
- Special character handling
- hookSpecificOutput presence/absence verification

## Verification

All tests pass with proper schema compliance:

```bash
$ .venv/bin/pytest tests/unit/core/test_error_response.py -v
# 27 passed in 2.24s

$ .venv/bin/python -m claude_code_hooks_daemon.core.error_response Stop daemon_startup_failed "Failed"
{"decision": "block", "reason": "Hooks daemon not running - protection not active"}

$ .venv/bin/python -m claude_code_hooks_daemon.core.error_response PreToolUse socket_timeout "Timeout"
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "..."}}
```

## Benefits

1. **DRY**: Single source of truth for error message generation
2. **Type Safety**: Leverages existing `HookResult` with full validation
3. **Event-Aware**: Automatically generates correct format per event type
4. **Maintainable**: Changes to error messages only need one update
5. **Testable**: Comprehensive test coverage ensures correctness

## Files Changed

- `src/claude_code_hooks_daemon/core/error_response.py` - New CLI utility (85 lines)
- `src/claude_code_hooks_daemon/core/__init__.py` - Export new utility
- `.claude/init.sh` - Replace 73 lines with 6 lines calling utility
- `tests/unit/core/test_error_response.py` - New test file (27 tests)

## Migration Notes

**For Users**: Automatic on next `install.py` run - no action needed.

**For Developers**: The `generate_daemon_error_response()` function is now available for any code that needs to generate daemon error responses.

## Lessons Learned

1. **Schema Validation**: Always validate hook responses against Claude Code's schemas during testing
2. **Event Differences**: Stop/SubagentStop events have unique schema - no hookSpecificOutput allowed
3. **Integration Testing**: Hook flow testing (using `./scripts/debug_hooks.sh`) should be part of QA
4. **DRY Principle**: Centralize complex formatting logic - don't duplicate in shell scripts

## Related

- PRD Section 3.3.2: Hook Error Response Format
- `src/claude_code_hooks_daemon/core/response_schemas.py`: Schema definitions
- `src/claude_code_hooks_daemon/core/hook_result.py`: HookResult.to_json() event formatting
