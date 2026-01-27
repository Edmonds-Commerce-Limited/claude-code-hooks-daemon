# Plan 002: Fix Silent Handler Failures

**Status**: 🟡 In Progress
**Created**: 2026-01-27
**Owner**: TBD
**Priority**: Critical
**Estimated Effort**: 8-12 hours

## Overview

Fix critical silent failures where handlers match events but fail to process them due to wrong field names, then add robust input validation at the front controller layer to prevent this class of bug from recurring. This addresses the findings from Plan 001 (Test Fixture Validation).

**Problem**: Multiple handlers are silently broken in production:
- BashErrorDetectorHandler uses `tool_output` (real events have `tool_response`)
- AutoApproveReadsHandler uses `permission_type` (real events have `permission_suggestions`)
- NotificationLoggerHandler tests use `severity` (real events have `notification_type`)

**Impact**: Handlers match events, return success, but never actually process data. No errors logged. Claude Code receives success responses. Users have no indication anything is wrong.

**Architecture**: Input validation will be added at the **outermost front controller layer** (server.py `_handle_client()`) to validate hook_input ONCE per event BEFORE dispatching to handlers. This ensures all handlers receive validated data.

## Goals

- ✅ Fix all broken handlers to use correct field names
- ✅ Update all test fixtures to match real Claude Code event structures
- ✅ Add input schema validation (toggleable via config/env var)
- ✅ Add sanity checks for required fields
- ✅ Ensure handlers fail loudly when data is missing
- ✅ Maintain 95%+ test coverage
- ✅ Document input validation patterns for future handlers

## Non-Goals

- ❌ Change fail-open architecture (that's by design for hook resilience)
- ❌ Add validation that impacts performance significantly (< 5ms overhead target)
- ❌ Rewrite all handlers (only fix broken ones)
- ❌ Validate response schemas (already exists)

## Context & Background

From Plan 001, we discovered:

1. **PostToolUse handlers**: Use `tool_output` (wrong), should use `tool_response` (correct)
2. **PermissionRequest handlers**: Use `permission_type`/`resource` (wrong), should use `permission_suggestions` (correct)
3. **Notification tests**: Use `severity` (wrong), should use `notification_type` (correct)

**Root Causes**:
- Handlers written based on assumptions, not real event captures
- No input schema validation (only response schemas exist)
- `.get()` with defaults masks missing required fields
- Fail-open architecture allows silent failures

**Why No Errors**: Handlers use `.get("wrong_field", {})` which returns empty dict, then immediately return ALLOW with no error logging.

See `/workspace/CLAUDE/Plan/002-fix-silent-handler-failures/CRITICAL_ANALYSIS_SILENT_FAILURES.md` for complete analysis.

## Tasks

### Phase 1: Design Input Validation System
- [ ] ⬜ **Task 1.1**: Research validation approaches
  - [ ] ⬜ Evaluate jsonschema performance (benchmark with 10k events)
  - [ ] ⬜ Compare: full schemas vs sanity checks vs hybrid
  - [ ] ⬜ **ARCHITECTURE**: Validate at outermost layer (server.py) ONCE per event
  - [ ] ⬜ Design error handling strategy
- [ ] ⬜ **Task 1.2**: Design input schemas structure
  - [ ] ⬜ Create `input_schemas.py` alongside `response_schemas.py`
  - [ ] ⬜ Define schemas for ALL event types (PreToolUse, PostToolUse, PermissionRequest, etc.)
  - [ ] ⬜ Document required vs optional fields per event type
  - [ ] ⬜ Include tool-specific structures (Bash, Read, Write, etc.)
  - [ ] ⬜ Define validation error format returned to Claude Code
- [ ] ⬜ **Task 1.3**: Design configuration approach
  - [ ] ⬜ Add `validate_input` boolean to DaemonConfig (default: False initially)
  - [ ] ⬜ Add `HOOKS_DAEMON_VALIDATE_INPUT` env var override
  - [ ] ⬜ Document in config schema and init_config.py
  - [ ] ⬜ Add validation toggle to CLI commands

### Phase 2: Implement Input Validation (TDD)
- [ ] ⬜ **Task 2.1**: Create input schemas
  - [ ] ⬜ Write tests for schema structure
  - [ ] ⬜ Implement PreToolUse input schema
  - [ ] ⬜ Implement PostToolUse input schema (tool_response structure)
  - [ ] ⬜ Implement PermissionRequest input schema (permission_suggestions)
  - [ ] ⬜ Implement Notification input schema (notification_type)
  - [ ] ⬜ Implement remaining event schemas
- [ ] ⬜ **Task 2.2**: Implement validation function
  - [ ] ⬜ Write tests for validate_input()
  - [ ] ⬜ Implement validate_input(event_type, hook_input)
  - [ ] ⬜ Return validation errors list
  - [ ] ⬜ Add performance logging
- [ ] ⬜ **Task 2.3**: Integrate into server.py front controller layer
  - [ ] ⬜ Write tests for server validation integration
  - [ ] ⬜ Add validation call in _handle_client() after parsing JSON, BEFORE dispatch
  - [ ] ⬜ Validate ONCE per event at outermost layer (not in handlers/chain)
  - [ ] ⬜ Return error response to Claude Code if validation fails
  - [ ] ⬜ Log validation failures at WARNING level with full details
  - [ ] ⬜ Add metrics tracking (validation_failures counter)
  - [ ] ⬜ Short-circuit: Don't dispatch to handlers if validation fails

### Phase 3: Fix BashErrorDetectorHandler (PostToolUse)
- [ ] ⬜ **Task 3.1**: Update handler implementation
  - [ ] ⬜ Write failing tests using tool_response field
  - [ ] ⬜ Change tool_output → tool_response in handler
  - [ ] ⬜ Remove exit_code dependency (doesn't exist in real events)
  - [ ] ⬜ Use stderr/stdout content for error detection
  - [ ] ⬜ Implement tests pass
- [ ] ⬜ **Task 3.2**: Update all PostToolUse test fixtures
  - [ ] ⬜ Update test_bash_error_detector.py fixtures (tool_output → tool_response)
  - [ ] ⬜ Remove exit_code from fixtures
  - [ ] ⬜ Add stdout, stderr, interrupted, isImage fields
  - [ ] ⬜ Update test_validate_eslint_on_write.py fixtures
  - [ ] ⬜ Update test_validate_sitemap.py fixtures
  - [ ] ⬜ Update integration test fixtures
- [ ] ⬜ **Task 3.3**: Verify handler works in production
  - [ ] ⬜ Test with debug_hooks.sh capturing real events
  - [ ] ⬜ Verify handler matches and processes data
  - [ ] ⬜ Verify error detection actually works

### Phase 4: Fix AutoApproveReadsHandler (PermissionRequest)
- [ ] ⬜ **Task 4.1**: Redesign handler for correct structure
  - [ ] ⬜ Analyze real permission_suggestions structure from logs
  - [ ] ⬜ Decide: Keep auto-approve concept or repurpose handler?
  - [ ] ⬜ Write tests for new matching logic (permission_suggestions based)
  - [ ] ⬜ Reimplement matches() to check permission_suggestions
  - [ ] ⬜ Reimplement handle() to return appropriate result
- [ ] ⬜ **Task 4.2**: Update all PermissionRequest test fixtures
  - [ ] ⬜ Update test_auto_approve_reads.py (147 tests)
  - [ ] ⬜ Change permission_type/resource → permission_suggestions structure
  - [ ] ⬜ Add tool_name, tool_input fields
  - [ ] ⬜ Update integration test fixtures
  - [ ] ⬜ Verify all 147 tests still pass
- [ ] ⬜ **Task 4.3**: Verify handler works in production
  - [ ] ⬜ Trigger permission request in Claude Code
  - [ ] ⬜ Verify handler matches in logs
  - [ ] ⬜ Verify handler processes permission_suggestions

### Phase 5: Fix NotificationLoggerHandler Tests
- [ ] ⬜ **Task 5.1**: Update test fixtures
  - [ ] ⬜ Update test_notification_logger.py (severity → notification_type)
  - [ ] ⬜ Use documented types: permission_prompt, idle_prompt, auth_success
  - [ ] ⬜ Remove invalid fields: code, details
  - [ ] ⬜ Add standard fields: session_id, transcript_path, cwd
  - [ ] ⬜ Update integration test fixtures
- [ ] ⬜ **Task 5.2**: Verify handler still works
  - [ ] ⬜ Handler is generic (passes through all fields)
  - [ ] ⬜ Verify logs contain correct field names
  - [ ] ⬜ All tests passing

### Phase 6: Add Defensive Checks to Handlers (Optional)
- [ ] ⬜ **Task 6.1**: Define defensive coding pattern for handlers
  - [ ] ⬜ Document: Handlers can trust validated input from front controller
  - [ ] ⬜ Document: When to add defensive checks vs trusting validation
  - [ ] ⬜ Create handler_utils.py with helper functions if needed
  - [ ] ⬜ Update HANDLER_DEVELOPMENT.md with best practices
- [ ] ⬜ **Task 6.2**: Review critical handlers for defensive improvements
  - [ ] ⬜ BashErrorDetector: Verify assumes tool_response exists
  - [ ] ⬜ DestructiveGit: Verify assumes tool_input.command exists
  - [ ] ⬜ Document which fields are guaranteed by validation vs optional

**Note**: With front controller validation, handlers can mostly trust input structure. Defensive checks are for edge cases not caught by schema (e.g., empty strings where non-empty expected).

### Phase 7: Performance & Integration Testing
- [ ] ⬜ **Task 7.1**: Benchmark validation performance
  - [ ] ⬜ Create benchmark script with 10k events
  - [ ] ⬜ Measure baseline (no validation)
  - [ ] ⬜ Measure with validation enabled
  - [ ] ⬜ Target: < 5ms overhead per event
  - [ ] ⬜ Document results
- [ ] ⬜ **Task 7.2**: Integration testing with live Claude Code
  - [ ] ⬜ Enable validation: HOOKS_DAEMON_VALIDATE_INPUT=true
  - [ ] ⬜ Run through common workflows (git, file ops, agent tasks)
  - [ ] ⬜ Verify no validation failures for valid events
  - [ ] ⬜ Verify validation catches malformed events
  - [ ] ⬜ Check daemon logs for any issues
- [ ] ⬜ **Task 7.3**: Full QA suite
  - [ ] ⬜ Run ./scripts/qa/run_all.sh
  - [ ] ⬜ Verify 95%+ coverage maintained
  - [ ] ⬜ All 2484+ tests passing
  - [ ] ⬜ No type errors
  - [ ] ⬜ No security issues

### Phase 8: Documentation & Completion
- [ ] ⬜ **Task 8.1**: Update documentation
  - [ ] ⬜ Update CLAUDE/HANDLER_DEVELOPMENT.md with sanity check patterns
  - [ ] ⬜ Document input validation in DAEMON.md
  - [ ] ⬜ Add input_schemas.py documentation
  - [ ] ⬜ Update README.md configuration section
- [ ] ⬜ **Task 8.2**: Update default configuration
  - [ ] ⬜ Decide: Enable validation by default or opt-in?
  - [ ] ⬜ Update .claude/hooks-daemon.yaml template
  - [ ] ⬜ Update init_config.py default value
  - [ ] ⬜ Document in UPGRADES/ if breaking change
- [ ] ⬜ **Task 8.3**: Commit and push
  - [ ] ⬜ Review all changes
  - [ ] ⬜ Create comprehensive commit message
  - [ ] ⬜ Push to origin/main
  - [ ] ⬜ Mark plan as complete

## Dependencies

- **Depends on**: Plan 001 (Complete) - Provides analysis and verification reports
- **Blocks**: None yet
- **Related**: None yet

## Technical Decisions

### Decision 1: Validation Approach
**Context**: Need to prevent silent failures without impacting performance
**Options Considered**:
1. Full jsonschema validation (comprehensive but potentially slow)
2. Sanity checks only (fast but less comprehensive)
3. Hybrid: Essential field validation always + optional full validation

**Decision**: **Hybrid approach with layered validation**
**Implementation**:
- **Layer 1 (Always ON)**: Validate essential fields required for routing (tool_name, tool_response vs tool_output, etc.)
- **Layer 2 (Optional)**: Full jsonschema validation for all documented fields
**Performance Data**:
- Schema compilation: 0.1-0.5ms (one-time, cached)
- Simple validation: 0.01-0.05ms per event
- Complex validation: 0.1-0.5ms per event
- **Worst case: ~1ms** (well under 5ms target)
**Rationale**:
- Essential validation catches the specific bugs identified (wrong field names)
- Full schemas provide comprehensive checking without brittleness
- Performance is acceptable with cached validators
- Hybrid provides protection without over-constraining
**Date**: 2026-01-27

### Decision 2: Configuration Default
**Context**: Should validation be enabled by default?
**Options Considered**:
1. Opt-in (validate_input: false by default) - safer rollout
2. Opt-out (validate_input: true by default) - better protection

**Decision**: **Validation ON by default, Strict mode OFF by default**
**Configuration Structure**:
```yaml
daemon:
  input_validation:
    enabled: true              # Master switch (default: true)
    strict_mode: false         # Fail-closed on errors (default: false)
    log_validation_errors: true
```
**Environment Variables**:
- `HOOKS_DAEMON_INPUT_VALIDATION=true|false` - Master switch
- `HOOKS_DAEMON_VALIDATION_STRICT=true|false` - Strict mode
**Rollout Strategy**:
1. Phase 1: `enabled: true`, `strict_mode: false` - Validate but don't block
2. Phase 2: Monitor logs, fix any false positives
3. Phase 3: Keep `strict_mode: false` for production resilience
**Rationale**:
- ON by default catches bugs during development
- Strict OFF ensures production resilience (fail-open)
- Easy to enable strict mode for debugging
- Aligns with existing fail-open architecture
**Date**: 2026-01-27

### Decision 3: Validation Layer Location
**Context**: Where should input validation happen?
**Options Considered**:
1. In individual handlers (validate per-handler) - Flexible but inefficient, validated N times
2. In handler chain (validate per-chain) - Better but still after routing
3. In front controller server.py (validate once per event) - Outermost layer, most efficient

**Decision**: Front controller layer (server.py `_handle_client()`) - ARCHITECTURAL DECISION
**Rationale**:
- Validate ONCE per event, not N times per handler
- Catch invalid data before any handler processing
- Single source of truth for valid event structure
- Fail fast at system boundary
- All handlers can trust input is valid
**Date**: 2026-01-27

### Decision 4: Error Handling
**Context**: What happens when validation fails?
**Options Considered**:
1. Return error to Claude Code (fail-closed for validation)
2. Log error and allow (fail-open for validation)
3. Configurable behavior

**Decision**: **Log and continue (fail-open) by default, with optional strict mode**
**Default Behavior (fail-open)**:
- Log validation errors at WARNING level with full details
- Continue processing (dispatch to handlers)
- Include validation warning in response context
- Track `validation_failures` metric
**Strict Mode (fail-closed, opt-in)**:
- Log validation errors at ERROR level
- Return error response to Claude Code
- Do NOT dispatch to handlers
- Error format: `{"error": "input_validation_failed", "details": [...]}`
**Rationale**:
- Fail-open aligns with existing architecture philosophy
- Validation failures are likely edge cases or version mismatches
- Better to have partial functionality than total failure
- Strict mode available for testing/debugging
- Logs provide visibility without blocking work
**Date**: 2026-01-27

## Success Criteria

- [ ] All broken handlers fixed (BashErrorDetector, AutoApproveReads, Notification tests)
- [ ] All test fixtures match real Claude Code event structures
- [ ] Input validation system implemented and configurable
- [ ] Sanity check pattern documented and implemented
- [ ] Performance overhead < 5ms per event (with validation enabled)
- [ ] All tests passing (2484+ tests)
- [ ] Coverage maintained at 95%+
- [ ] No type errors (MyPy strict mode)
- [ ] Handlers verified working in live Claude Code sessions
- [ ] Documentation updated

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Validation too slow | High | Medium | Benchmark early, make validation optional, optimize schemas |
| Breaking existing handlers | High | Low | Comprehensive testing, gradual rollout, opt-in initially |
| Validation too strict | Medium | Medium | Test with real events, allow optional fields, document schema |
| Complex handler redesign | Medium | High | Focus on fixing field names first, redesign only if needed |
| Coverage drops below 95% | Medium | Low | Write tests first (TDD), monitor coverage continuously |

## Timeline

- **Phase 1 (Design)**: 2 hours
- **Phase 2 (Validation System)**: 4 hours
- **Phase 3 (BashErrorDetector)**: 2 hours
- **Phase 4 (AutoApproveReads)**: 2 hours
- **Phase 5 (Notification)**: 1 hour
- **Phase 6 (Sanity Checks)**: 2 hours
- **Phase 7 (Testing)**: 2 hours
- **Phase 8 (Documentation)**: 1 hour
- **Target Completion**: 2026-01-28 (allowing buffer for issues)

## Notes & Updates

### 2026-01-27
- Plan created based on Plan 001 findings
- Moved CRITICAL_ANALYSIS_SILENT_FAILURES.md into plan folder
- Awaiting Opus agent research on validation approach
- Need to decide on validation strategy before implementation begins

## Artifacts

Located in `/workspace/CLAUDE/Plan/002-fix-silent-handler-failures/`:

1. **CRITICAL_ANALYSIS_SILENT_FAILURES.md** - Comprehensive analysis of the problem
2. **PLAN.md** (this file) - Implementation plan

## Reference Documentation

- Plan 001: Test Fixture Validation Against Real Claude Code Events
- CLAUDE/HANDLER_DEVELOPMENT.md - Handler patterns
- CLAUDE/DEBUGGING_HOOKS.md - How to capture real events
- src/claude_code_hooks_daemon/core/response_schemas.py - Example validation approach

## Technical Design

### Input Schema Structure

#### Common Base Fields
All events contain these base fields:
```python
{
    "session_id": "uuid-string",           # Always present
    "transcript_path": "path/to/file.jsonl", # Usually present  
    "cwd": "/workspace",                   # Usually present
    "permission_mode": "acceptEdits",      # Usually present
    "hook_event_name": "EventType"         # Always present
}
```

#### Event-Specific Schemas

**PreToolUse Schema:**
```python
PRE_TOOL_USE_INPUT_SCHEMA = {
    "type": "object",
    "required": ["tool_name", "hook_event_name"],
    "properties": {
        "session_id": {"type": "string"},
        "transcript_path": {"type": "string"},
        "cwd": {"type": "string"},
        "hook_event_name": {"const": "PreToolUse"},
        "tool_name": {"type": "string"},
        "tool_input": {"type": "object"},
        "tool_use_id": {"type": "string"},
    },
    "additionalProperties": True,  # Allow unknown fields for forward compatibility
}
```

**PostToolUse Schema (CRITICAL - validates tool_response, not tool_output):**
```python
POST_TOOL_USE_INPUT_SCHEMA = {
    "type": "object",
    "required": ["tool_name", "tool_response", "hook_event_name"],
    "properties": {
        "session_id": {"type": "string"},
        "transcript_path": {"type": "string"},
        "cwd": {"type": "string"},
        "hook_event_name": {"const": "PostToolUse"},
        "tool_name": {"type": "string"},
        "tool_input": {"type": "object"},
        "tool_response": {"type": "object"},  # NOT tool_output!
        "tool_use_id": {"type": "string"},
    },
    "additionalProperties": True,
}
```

**PermissionRequest Schema (CRITICAL - validates permission_suggestions):**
```python
PERMISSION_REQUEST_INPUT_SCHEMA = {
    "type": "object",
    "required": ["tool_name", "permission_suggestions", "hook_event_name"],
    "properties": {
        "session_id": {"type": "string"},
        "transcript_path": {"type": "string"},
        "cwd": {"type": "string"},
        "hook_event_name": {"const": "PermissionRequest"},
        "tool_name": {"type": "string"},
        "tool_input": {"type": "object"},
        "permission_suggestions": {"type": "array"},  # NOT permission_type/resource!
    },
    "additionalProperties": True,
}
```

### Validation Function Design

```python
def _validate_hook_input(
    self, 
    event_type: str, 
    hook_input: dict[str, Any]
) -> list[str]:
    """Validate hook_input against event-specific schema.
    
    Args:
        event_type: Event name (PreToolUse, PostToolUse, etc.)
        hook_input: Hook input dictionary
        
    Returns:
        List of validation error messages (empty if valid)
    """
    # Get cached validator for event type
    validator = self._get_input_validator(event_type)
    if validator is None:
        return []  # Unknown event type, skip validation
    
    errors = []
    for error in validator.iter_errors(hook_input):
        path = ".".join(str(p) for p in error.path) if error.path else "root"
        errors.append(f"{path}: {error.message}")
    
    return errors
```

### Integration Point in server.py

**Location**: `_process_request()` method, after JSON parsing, BEFORE dispatch to controller

```python
async def _process_request(self, request_data: str) -> dict[str, Any]:
    try:
        request = json.loads(request_data)
    except json.JSONDecodeError as e:
        logger.error("Malformed JSON request: %s", e)
        return {"error": f"Malformed JSON: {e}"}

    # Extract request fields
    request_id = request.get("request_id")
    event = request.get("event")
    hook_input = request.get("hook_input")

    # ... existing validation of event and hook_input presence ...

    # Handle system events (no input validation needed)
    if event == "_system":
        return self._handle_system_request(hook_input, request_id)

    # === INPUT VALIDATION (NEW) ===
    if self._should_validate_input():
        validation_errors = self._validate_hook_input(event, hook_input)
        if validation_errors:
            logger.warning(
                "Input validation failed for %s: %s", 
                event, 
                validation_errors
            )
            if self._is_strict_validation():
                return self._validation_error_response(
                    event, validation_errors, request_id
                )
            # Fail-open: continue with warning in context

    # Process with appropriate controller (existing logic)
    ...
```

### Validator Caching Strategy

```python
# In HooksDaemon.__init__()
self._input_validators: dict[str, Draft7Validator] = {}

def _get_input_validator(self, event_type: str) -> Draft7Validator | None:
    """Get or create cached validator for event type."""
    if event_type not in self._input_validators:
        schema = get_input_schema(event_type)  # From input_schemas.py
        if schema:
            self._input_validators[event_type] = Draft7Validator(schema)
    return self._input_validators.get(event_type)
```

### Error Response Format (Strict Mode)

```python
{
    "error": "input_validation_failed",
    "details": [
        "tool_response: Missing required field",
        "tool_output: Additional property not allowed (should be tool_response)"
    ],
    "event_type": "PostToolUse",
    "request_id": "..."  # If present in original request
}
```

### Performance Expectations

| Metric | Target | Expected |
|--------|--------|----------|
| Schema compilation (cached) | N/A | 0.1-0.5ms one-time |
| Validation per event | < 5ms | 0.1-0.5ms |
| Memory overhead | < 1MB | ~500KB for all schemas |
| Throughput impact | < 5% | < 1% expected |

**Mitigation Strategies:**
- Pre-compile and cache all validators at daemon startup
- Use Draft7Validator (optimized implementation)
- Skip validation for system events (_system)
- Optional: Disable validation in production if performance issues arise

### Testing Strategy

**Test Fixtures from Real Events:**
- Store canonical real event fixtures in `tests/fixtures/real_events/`
- Source: Captures from debug_hooks.sh sessions
- Document field structures in POSTTOOLUSE_FIXTURE_VERIFICATION.md

**Unit Test Coverage:**
```python
class TestInputValidation:
    def test_valid_pre_tool_use_bash(self):
        """Valid PreToolUse Bash event passes validation."""
        
    def test_missing_tool_name(self):
        """Missing tool_name field fails validation."""
        
    def test_wrong_field_tool_output_instead_of_response(self):
        """Using tool_output instead of tool_response fails validation."""
        # This is the specific bug we're catching!
        
    def test_validation_performance_under_5ms(self):
        """Validation completes under 5ms target."""
```

**Integration Tests:**
- Test full request flow with validation enabled
- Verify validation doesn't break existing handlers
- Verify validation errors are logged correctly
- Verify fail-open behavior works
- Verify strict mode returns error responses

### Files to Create/Modify

**New Files:**
1. `src/claude_code_hooks_daemon/core/input_schemas.py` - Input schema definitions
2. `tests/fixtures/real_events/` - Canonical real event fixtures

**Modified Files:**
1. `src/claude_code_hooks_daemon/daemon/server.py` - Add validation integration
2. `src/claude_code_hooks_daemon/config/models.py` - Add InputValidationConfig
3. `src/claude_code_hooks_daemon/daemon/config.py` - Add validation settings
4. `src/claude_code_hooks_daemon/handlers/post_tool_use/bash_error_detector.py` - Fix field names
5. `src/claude_code_hooks_daemon/handlers/permission_request/auto_approve_reads.py` - Fix field names
6. `tests/unit/handlers/post_tool_use/test_bash_error_detector.py` - Fix test fixtures
7. `tests/unit/handlers/permission_request/test_auto_approve_reads.py` - Fix test fixtures
8. `tests/unit/handlers/notification/test_notification_logger.py` - Fix test fixtures
