# Exploration Findings: Status Line Implementation

**Date**: 2026-01-28
**Context**: Research for daemon-based status line system

## Socket Communication Architecture

### Request/Response Flow

1. **Bash Hook Entry Point** (`.claude/hooks/{event}`)
   - Sources `init.sh` for helper functions
   - Lazy daemon startup via `ensure_daemon()`
   - Pipes JSON through `send_request_stdin` function
   - Uses `jq` to format request: `{event: "EventName", hook_input: ...}`

2. **Unix Socket Server** (`daemon/server.py`)
   - Asyncio-based TCP socket over Unix domain socket
   - Reads newline-delimited JSON requests
   - 30-second timeout per connection
   - Optional input/output validation via JSON schemas

3. **DaemonController** (`daemon/controller.py`)
   - Parses request into `HookEvent` Pydantic model
   - Routes to `EventRouter` which dispatches to handler chains
   - Accumulates stats: requests, timing, errors
   - Returns formatted response dict

4. **Handler Chain Execution**
   - Handlers run in priority order (lowest first)
   - **Terminal handlers**: Stop chain, return immediately
   - **Non-terminal handlers**: Continue chain, accumulate context
   - Final result = accumulated context from all handlers

### Key Files

| File | Purpose |
|------|---------|
| `.claude/init.sh` | Socket communication helpers, daemon lifecycle |
| `daemon/server.py` | Asyncio socket server, request processing |
| `daemon/controller.py` | Event routing, handler dispatch, stats tracking |
| `core/router.py` | Routes events to appropriate handler chains |
| `core/chain.py` | Chain of Responsibility execution logic |
| `core/handler.py` | Handler base class interface |
| `core/hook_result.py` | Result formatting (event-specific JSON) |
| `core/event.py` | Event type enum, HookEvent/HookInput models |

## Handler Patterns

### Terminal vs Non-Terminal

**Terminal Handlers** (`terminal=True`, default):
- Block the operation or stop the chain
- Used for enforcement: destructive git, sed blocker, TDD checks
- Example priorities: 10-20 (safety), 25-35 (code quality)

**Non-Terminal Handlers** (`terminal=False`):
- Advisory/informational
- Accumulate context for Claude
- Continue to next handler
- Example priorities: 56-60 (advisory), 85+ (logging)

### Context Accumulation

From `chain.py` (lines 76-102):
```python
accumulated_context: list[str] = []

for handler in self.handlers:  # Sorted by priority
    if handler.matches(hook_input):
        result = handler.handle(hook_input)

        if handler.terminal:
            # Stop and return, prepending accumulated context
            if accumulated_context:
                result.context = accumulated_context + result.context
            return result
        else:
            # Accumulate and continue
            accumulated_context.extend(result.context)
            final_result = result

# No terminal handler matched
if final_result:
    if accumulated_context:
        final_result.context = accumulated_context
    return final_result
```

### HookResult Factory Methods

```python
# Simple allow (silent)
HookResult.allow()

# Allow with context (advisory)
HookResult.allow(
    context=["Line 1", "Line 2"],
    guidance="User-facing text"
)

# Deny with reason (blocking)
HookResult.deny(
    reason="Why this is blocked",
    context=["Additional info"]
)

# Error handling (fail-open)
HookResult.error(
    error_type="handler_exception",
    error_details="Error message"
)
```

## Claude Code StatusLine Format

### Input JSON (from Claude Code docs)

```json
{
  "hook_event_name": "Status",
  "session_id": "abc123...",
  "transcript_path": "/path/to/transcript.json",
  "cwd": "/current/working/directory",
  "model": {
    "id": "claude-opus-4-1",
    "display_name": "Opus"
  },
  "workspace": {
    "current_dir": "/current/working/directory",
    "project_dir": "/original/project/directory"
  },
  "version": "1.0.80",
  "output_style": {
    "name": "default"
  },
  "cost": {
    "total_cost_usd": 0.01234,
    "total_duration_ms": 45000,
    "total_api_duration_ms": 2300,
    "total_lines_added": 156,
    "total_lines_removed": 23
  },
  "context_window": {
    "total_input_tokens": 15234,
    "total_output_tokens": 4521,
    "context_window_size": 200000,
    "used_percentage": 42.5,
    "remaining_percentage": 57.5,
    "current_usage": {
      "input_tokens": 8500,
      "output_tokens": 1200,
      "cache_creation_input_tokens": 5000,
      "cache_read_input_tokens": 2000
    }
  }
}
```

### Expected Output

**Format**: Plain text with ANSI escape codes
**Example**: `Sonnet | Ctx: 42.5% | main | ⚡ 1.2s | 45MB | INFO`

**Color Codes** (from current implementation):
- Green (0-40%): `\033[42m\033[30m` (green bg, black text)
- Yellow (41-60%): `\033[43m\033[30m` (yellow bg, black text)
- Orange (61-80%): `\033[48;5;208m\033[30m` (orange bg, black text)
- Red (81-100%): `\033[41m\033[97m` (red bg, white text)
- Reset: `\033[0m`

## Response Formatting

### Event-Specific Formats (from `hook_result.py`)

Different events expect different response structures:

| Event Type | Response Format |
|------------|----------------|
| PreToolUse | `hookSpecificOutput` with `permissionDecision` |
| PostToolUse | `decision` + `hookSpecificOutput` |
| SessionStart/End | `hookSpecificOutput` with `additionalContext` only |
| Stop/SubagentStop | `decision` + `reason` (no hookSpecificOutput) |
| **Status** | **Plain text** (not JSON hookSpecificOutput) |

### Special Case: Status Event

```python
def to_json(self, event_name: str) -> dict[str, Any]:
    if event_name == "Status":
        # Join context with spaces (not double newlines)
        text = " ".join(self.context) if self.context else "Claude"
        return {"text": text}
    # ... other event types ...
```

## Daemon Stats Available

From `DaemonStats` in `controller.py`:

```python
@dataclass
class DaemonStats:
    start_time: datetime
    requests_processed: int
    requests_by_event: dict[str, int]
    total_processing_time_ms: float
    errors: int
    last_request_time: datetime | None

    @property
    def uptime_seconds(self) -> float:
        return (datetime.now() - self.start_time).total_seconds()

    @property
    def avg_processing_time_ms(self) -> float:
        if self.requests_processed == 0:
            return 0.0
        return self.total_processing_time_ms / self.requests_processed
```

Access via: `get_controller().get_stats()`

## Implementation Notes

### Priority Allocation

Based on existing conventions:

| Range | Purpose | Example |
|-------|---------|---------|
| 0-19 | Critical safety | Destructive git (10) |
| 20-39 | Code quality | ESLint, TDD |
| 40-59 | Workflow | Planning (35) |
| 60-79 | Advisory | British English (60) |
| 80-99 | Logging/metrics | **Status line (10-30)** |

Status line handlers: 10, 20, 30 (within status_line event namespace)

### Error Handling Philosophy

- **Fail-open with context**: Errors shouldn't break the user flow
- **Log and continue**: Status line failures should degrade gracefully
- **Fallback values**: Always provide minimal status if data unavailable

### Performance Considerations

- **Socket warmup**: First request slower (daemon startup)
- **After warmup**: ~20x faster than subprocess spawn
- **Caching**: Consider caching git operations (0.5s timeout currently)
- **Memory**: psutil.Process().memory_info() is fast (<1ms)

## References

- [Claude Code StatusLine Docs](https://code.claude.com/docs/en/statusline)
- [Shipyard Claude Code Cheatsheet](https://shipyard.build/blog/claude-code-cheat-sheet/)
- [ccstatusline Project](https://github.com/sirmalloc/ccstatusline) - Community statusline tool
- [ccusage Project](https://ccusage.com/guide/statusline) - Usage analysis tool

## Next Steps

1. Add `STATUS_LINE = "Status"` to `EventType` enum
2. Create bash hook entry point
3. Implement 3 modular handlers (model_context, git_branch, daemon_stats)
4. Update `HookResult.to_json()` for Status event (return plain text)
5. Add SessionStart suggestion handler
6. Write comprehensive tests
7. Update documentation
