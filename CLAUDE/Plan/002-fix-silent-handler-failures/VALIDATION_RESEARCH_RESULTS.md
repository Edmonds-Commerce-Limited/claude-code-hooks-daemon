# Validation Approach Research Results

**Date**: 2026-01-27
**Phase**: 1.1 - Research validation approaches

## Performance Benchmark Results

Tested with 10,000 validation iterations:

| Approach | Compile Time | Per Event Time | Events/sec |
|----------|-------------|----------------|------------|
| Full jsonschema validation | 0.022ms | 0.028ms | 35,673 |
| Simple field checks | 0ms | 0.0001ms | 13,513,733 |
| Hybrid (essential + full) | 0.028ms | 0.028ms | 35,732 |

## Key Findings

1. **Full jsonschema validation is FAST**
   - Only 0.028ms per event (28 microseconds)
   - Well under 5ms performance target
   - One-time compile cost: 0.022ms (cached in daemon)

2. **Simple checks are faster but insufficient**
   - 280x faster than full schema
   - But only catches missing fields, not wrong field names
   - Wouldn't catch the `tool_output` vs `tool_response` bug

3. **Hybrid approach offers no advantage**
   - Same performance as full schema validation
   - Full validation overhead is negligible
   - No reason to split into layers

## Decision: Use Full jsonschema Validation

### Rationale

1. **Performance is excellent** - 0.028ms per event is negligible overhead
2. **Comprehensive protection** - Catches all structural issues including:
   - Missing required fields
   - Wrong field names (tool_output vs tool_response)
   - Type mismatches
   - Invalid enum values
3. **Simple implementation** - Single validation path, no complexity
4. **Already in use** - Response schemas already use Draft7Validator
5. **Forward compatible** - Use `additionalProperties: true` for unknown fields

### Implementation Approach

```python
# Pre-compile validators at daemon startup (one-time cost)
self._input_validators: dict[str, Draft7Validator] = {}

def _get_input_validator(self, event_type: str) -> Draft7Validator | None:
    """Get or create cached validator for event type."""
    if event_type not in self._input_validators:
        schema = get_input_schema(event_type)
        if schema:
            self._input_validators[event_type] = Draft7Validator(schema)
    return self._input_validators.get(event_type)

def _validate_hook_input(self, event_type: str, hook_input: dict) -> list[str]:
    """Validate hook_input against schema. Returns list of errors."""
    validator = self._get_input_validator(event_type)
    if validator is None:
        return []  # Unknown event type, skip validation

    errors = []
    for error in validator.iter_errors(hook_input):
        path = ".".join(str(p) for p in error.path) if error.path else "root"
        errors.append(f"{path}: {error.message}")
    return errors
```

## Error Handling Strategy

### Default: Fail-Open (Log and Continue)

```python
if self._should_validate_input():
    validation_errors = self._validate_hook_input(event, hook_input)
    if validation_errors:
        logger.warning(
            "Input validation failed for %s: %s",
            event,
            validation_errors
        )
        # Continue processing - fail-open
```

**Rationale**:
- Aligns with existing fail-open architecture
- Version mismatches between daemon and Claude Code won't break functionality
- Validation failures are logged for debugging
- Partial functionality better than total failure

### Optional: Strict Mode (Fail-Closed)

```python
if self._is_strict_validation() and validation_errors:
    return {
        "error": "input_validation_failed",
        "details": validation_errors,
        "event_type": event,
    }
```

**Use Cases**:
- Testing and debugging
- Identifying real event structure changes
- Enforcing strict compliance

## Integration Point

**Location**: `server.py` line ~409, in `_process_request()` method

**Timing**: After JSON parsing, BEFORE dispatching to controllers

```python
# After line 409: if event == "_system": ...

# INPUT VALIDATION
if self._should_validate_input():
    validation_errors = self._validate_hook_input(event, hook_input)
    if validation_errors:
        logger.warning("Input validation failed for %s: %s", event, validation_errors)
        if self._is_strict_validation():
            return self._validation_error_response(event, validation_errors, request_id)
        # Fail-open: continue with warning

# Continue with existing controller dispatch...
```

## Configuration Design

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

## Performance Impact

- **Per-event overhead**: 0.028ms (28 microseconds)
- **Startup overhead**: 0.022ms per schema (10 schemas = 0.22ms total)
- **Memory overhead**: ~500KB for all schemas and validators
- **Throughput impact**: < 0.1% (negligible)

## Comparison with Response Validation

| Aspect | Response Validation | Input Validation |
|--------|-------------------|------------------|
| Location | Tests only | Daemon runtime |
| Purpose | Ensure handlers return correct format | Catch wrong field names |
| Performance | Test-time only | 0.028ms per event |
| Failure mode | Test fails | Log warning, optional fail-closed |
| Coverage | Handler outputs | Claude Code inputs |

## Next Steps

1. ✅ **Research complete** - Full jsonschema validation chosen
2. → **Design input schemas** - Create schemas for all event types
3. → **Implement validation** - Add to server.py with caching
4. → **Fix broken handlers** - Update to correct field names
5. → **Update test fixtures** - Match real event structures

## References

- Benchmark script: `/workspace/scripts/benchmark_validation.py`
- Existing response schemas: `/workspace/src/claude_code_hooks_daemon/core/response_schemas.py`
- Server integration point: `/workspace/src/claude_code_hooks_daemon/daemon/server.py:409`
