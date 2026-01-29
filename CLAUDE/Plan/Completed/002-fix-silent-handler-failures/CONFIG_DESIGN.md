# Input Validation Configuration Design

**Date**: 2026-01-27
**Phase**: 1.3 - Design configuration approach

## Configuration Structure

### YAML Configuration

```yaml
version: 2.0
daemon:
  idle_timeout_seconds: 600
  log_level: INFO

  # New: Input validation configuration
  input_validation:
    enabled: true              # Master switch (default: true)
    strict_mode: false         # Fail-closed on errors (default: false)
    log_validation_errors: true  # Log validation failures (default: true)
```

### Environment Variables

Following the existing pattern (`HOOKS_DAEMON_LOG_LEVEL`):

- `HOOKS_DAEMON_INPUT_VALIDATION=true|false` - Override master switch
- `HOOKS_DAEMON_VALIDATION_STRICT=true|false` - Override strict mode

**Priority**: Environment variables > YAML config > Default values

## Pydantic Model

```python
class InputValidationConfig(BaseModel):
    """Configuration for input validation.

    Attributes:
        enabled: Enable input schema validation
        strict_mode: Fail-closed (return error) vs fail-open (log warning)
        log_validation_errors: Log validation failures
    """

    enabled: bool = Field(
        default=True,
        description="Enable input validation (catches wrong field names)"
    )
    strict_mode: bool = Field(
        default=False,
        description="Fail-closed on validation errors (default: fail-open)"
    )
    log_validation_errors: bool = Field(
        default=True,
        description="Log validation errors to daemon logs"
    )

class DaemonConfig(BaseModel):
    # ... existing fields ...

    input_validation: InputValidationConfig = Field(
        default_factory=InputValidationConfig
    )
```

## Server Integration

### Environment Variable Override

```python
# In HooksDaemon.__init__() or _process_request()

def _should_validate_input(self) -> bool:
    """Check if input validation is enabled."""
    # Check environment variable first
    env_enabled = os.environ.get("HOOKS_DAEMON_INPUT_VALIDATION", "").strip().lower()
    if env_enabled in ("true", "1", "yes"):
        return True
    if env_enabled in ("false", "0", "no"):
        return False

    # Fall back to config
    return self.config.daemon.input_validation.enabled

def _is_strict_validation(self) -> bool:
    """Check if strict validation mode is enabled."""
    # Check environment variable first
    env_strict = os.environ.get("HOOKS_DAEMON_VALIDATION_STRICT", "").strip().lower()
    if env_strict in ("true", "1", "yes"):
        return True
    if env_strict in ("false", "0", "no"):
        return False

    # Fall back to config
    return self.config.daemon.input_validation.strict_mode
```

## Behavior Modes

### Mode 1: Disabled (enabled: false)

- No validation performed
- Maximum performance (saves ~0.028ms per event)
- Use case: Performance-critical deployments

```yaml
daemon:
  input_validation:
    enabled: false
```

### Mode 2: Enabled + Fail-Open (default)

- Validation performed
- Errors logged at WARNING level
- Processing continues (fail-open)
- Use case: Production use with visibility

```yaml
daemon:
  input_validation:
    enabled: true        # default
    strict_mode: false   # default
    log_validation_errors: true  # default
```

**Log Output**:
```
[WARNING] Input validation failed for PostToolUse: tool_response: Missing required field
[WARNING] Input validation failed for PostToolUse: tool_output: Additional property not allowed
```

### Mode 3: Enabled + Strict Mode (fail-closed)

- Validation performed
- Errors logged at ERROR level
- Returns error to Claude Code (no dispatch)
- Use case: Testing, debugging, strict compliance

```yaml
daemon:
  input_validation:
    enabled: true
    strict_mode: true
```

**Error Response to Claude Code**:
```json
{
  "error": "input_validation_failed",
  "details": [
    "tool_response: Missing required field",
    "tool_output: Additional property not allowed"
  ],
  "event_type": "PostToolUse",
  "request_id": "req-123"
}
```

## Rollout Strategy

### Phase 1: Default ON, Strict OFF (Immediate)

```yaml
# Default configuration
daemon:
  input_validation:
    enabled: true      # Catch bugs
    strict_mode: false # Fail-open for resilience
```

**Rationale**:
- Validates all events, logs issues
- Doesn't break functionality
- Provides visibility into validation failures
- Aligns with fail-open philosophy

### Phase 2: Monitor Logs (1-2 weeks)

- Review validation warnings in production
- Identify false positives
- Fix any legitimate issues
- Adjust schemas if needed

### Phase 3: Production (Ongoing)

- Keep enabled: true, strict_mode: false
- Strict mode available for debugging

## CLI Integration

Add validation toggle to CLI commands:

```bash
# Status includes validation config
$ daemon-cli status
Daemon Status: running
Validation: enabled (fail-open)

# Optional: CLI flag to enable strict mode
$ daemon-cli start --strict-validation
```

## Testing

### Unit Tests

```python
def test_input_validation_enabled_by_default():
    """Input validation is enabled by default."""
    config = Config()
    assert config.daemon.input_validation.enabled is True

def test_strict_mode_disabled_by_default():
    """Strict mode is disabled by default (fail-open)."""
    config = Config()
    assert config.daemon.input_validation.strict_mode is False

def test_env_var_overrides_config():
    """HOOKS_DAEMON_INPUT_VALIDATION env var overrides config."""
    os.environ["HOOKS_DAEMON_INPUT_VALIDATION"] = "false"
    # ... test that validation is disabled
```

### Integration Tests

```python
def test_validation_error_logged_in_fail_open_mode():
    """Validation errors are logged but processing continues."""
    # Send malformed event
    # Check WARNING log exists
    # Check event was still processed

def test_validation_error_returned_in_strict_mode():
    """Validation errors return error response in strict mode."""
    # Enable strict mode
    # Send malformed event
    # Check error response received
    # Check event was NOT processed
```

## Documentation Updates

### README.md

Add to Configuration section:

```markdown
## Input Validation

The daemon validates hook input from Claude Code to catch malformed events:

\`\`\`yaml
daemon:
  input_validation:
    enabled: true        # Enable validation (default: true)
    strict_mode: false   # Fail-closed on errors (default: false)
\`\`\`

**Environment Variables:**
- `HOOKS_DAEMON_INPUT_VALIDATION=true|false` - Override master switch
- `HOOKS_DAEMON_VALIDATION_STRICT=true|false` - Override strict mode

**Modes:**
- **Disabled** (enabled: false) - No validation, maximum performance
- **Fail-open** (enabled: true, strict_mode: false) - Log errors, continue processing
- **Fail-closed** (enabled: true, strict_mode: true) - Return errors, block processing
```

### DAEMON.md

Add Input Validation section:

- Schema definitions (input_schemas.py)
- Validation flow in server.py
- Performance characteristics
- Error handling modes

### HANDLER_DEVELOPMENT.md

Update to mention input validation:

```markdown
## Input Validation

The daemon validates all hook_input at the server layer before dispatching to handlers.
Handlers can trust that required fields exist and have correct names (tool_response vs tool_output).

**What's Validated:**
- Required fields present (tool_name, tool_response, etc.)
- Correct field names (tool_response, NOT tool_output)
- No invalid field names (catches typos)

**What's NOT Validated:**
- Field values (handlers should validate business logic)
- Optional field presence
- Tool-specific response structures (varies by tool)
```

## Migration Notes

### Existing Installations

No migration needed - new config fields have sensible defaults:

```yaml
# Existing config (no changes needed)
version: 2.0
daemon:
  idle_timeout_seconds: 600
  log_level: INFO

# Effective config (defaults applied)
version: 2.0
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
  input_validation:  # Auto-added with defaults
    enabled: true
    strict_mode: false
    log_validation_errors: true
```

### Opting Out

If validation causes issues:

```yaml
daemon:
  input_validation:
    enabled: false  # Disable completely
```

Or use environment variable:

```bash
export HOOKS_DAEMON_INPUT_VALIDATION=false
```

## Performance Impact

- **Validation ON**: +0.028ms per event (negligible)
- **Validation OFF**: 0ms overhead
- **Memory**: +500KB for cached validators
- **Startup**: +0.22ms (one-time schema compilation)

See `VALIDATION_RESEARCH_RESULTS.md` for benchmarks.

## Security Considerations

### Fail-Open by Default

**Decision**: Default to fail-open (log warnings, continue processing)

**Rationale**:
- Prevents daemon from breaking on Claude Code version mismatches
- New fields from Claude Code won't cause failures
- Validation is for catching bugs, not security (hooks are trusted)
- Aligns with existing daemon philosophy

### Strict Mode Use Cases

Use strict mode (`strict_mode: true`) when:
- Debugging handler failures
- Testing new handlers
- Enforcing strict compliance
- Identifying Claude Code version mismatches

**NOT recommended** for production (fail-open is safer).

## Future Enhancements

### Per-Event Validation Toggle

```yaml
daemon:
  input_validation:
    enabled: true
    event_overrides:
      PostToolUse: true   # Validate PostToolUse
      Notification: false # Skip Notification validation
```

### Custom Schemas

```yaml
daemon:
  input_validation:
    custom_schemas_path: /path/to/custom/schemas.py
```

### Validation Metrics

Track validation failures:
- Count by event type
- Most common errors
- Failure rate over time

## References

- Input schemas: `src/claude_code_hooks_daemon/core/input_schemas.py`
- Config models: `src/claude_code_hooks_daemon/config/models.py`
- Server integration: `src/claude_code_hooks_daemon/daemon/server.py`
- Research results: `VALIDATION_RESEARCH_RESULTS.md`
