# Claude Code Hooks Daemon

**Status**: ✅ Fully Implemented (Phases 1-5 complete)

A high-performance daemon for Claude Code hooks using Unix socket IPC to eliminate process spawn overhead.

## Architecture

### Forwarder Pattern

```
┌─────────────┐      ┌──────────────┐      ┌────────────────┐
│ Claude Code │─────▶│ Hook Script  │─────▶│ Daemon Process │
│             │      │ (forwarder)  │      │ (long-running) │
└─────────────┘      └──────────────┘      └────────────────┘
                            │                       │
                            │ 1. Source init.sh     │
                            │ 2. ensure_daemon()    │
                            │ 3. send_request()     │
                            │                       │
                            └───────────────────────┘
                              Unix Socket IPC
                        /tmp/claude-hooks-{name}-{hash}.sock
```

### Key Features

**Performance**:
- **Sub-millisecond** response times after warmup (vs 21ms process spawn)
- Handlers loaded in memory (no repeated imports)
- Asyncio concurrent request handling

**Lifecycle**:
- **Lazy startup** - Daemon starts on first hook call
- **Auto-shutdown** - Exits after 10 minutes of inactivity (configurable)
- **Graceful shutdown** - Completes in-flight requests before exit

**Multi-Project**:
- Unique socket per project directory
- Socket path: `/tmp/claude-hooks-{project-name}-{hash}.sock`
- Hash based on absolute project path (MD5 first 8 chars)
- Multiple Claude instances in same project share one daemon

**Reliability**:
- PID file management with stale PID detection
- Fail-open philosophy (errors don't block operations)
- Signal handling (SIGTERM, SIGINT)

## Installation

```bash
cd your-project/.claude/hooks
git clone https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git
cd claude-code-hooks-daemon
pip install -e .
python3 install.py
```

The installer:
1. Backs up existing `.claude/hooks/` to `.claude/hooks.bak`
2. Copies `init.sh` to `.claude/init.sh`
3. Creates forwarder scripts in `.claude/hooks/`
4. Creates `.claude/settings.json` registering all hooks
5. Creates `.claude/hooks-daemon.yaml` with configuration

## Components

### Daemon Server

**File**: `src/claude_code_hooks_daemon/daemon/server.py`

**Class**: `HooksDaemon`

Asyncio Unix socket server that:
- Listens on project-specific socket path
- Reads JSON requests from socket
- Routes to `FrontController.dispatch()`
- Returns JSON responses with timing metrics
- Monitors idle timeout in background task
- Handles graceful shutdown on signals

**Protocol**:
```json
// Request
{
  "event": "PreToolUse",
  "hook_input": {"tool_name": "Bash", "tool_input": {...}},
  "request_id": "uuid"
}

// Response
{
  "request_id": "uuid",
  "result": {"decision": "allow", "reason": null},
  "timing_ms": 0.5
}

// Error
{
  "request_id": "uuid",
  "error": "Error message here"
}

// Validation Error (strict mode)
{
  "request_id": "uuid",
  "error": "input_validation_failed",
  "details": ["tool_response: required", "tool_output: unexpected field"],
  "event_type": "PostToolUse"
}
```

### Input Validation

**Added in**: v2.2.0

**Purpose**: Catch malformed events and wrong field names (e.g., `tool_output` vs `tool_response`) at the server layer before dispatching to handlers.

**Architecture**: Validation happens at the **front controller** (outermost layer) in `_process_request()`. Events are validated ONCE per request before any handler processing.

**Implementation**:
- JSON Schema validation using `jsonschema` library
- Schemas defined in `src/claude_code_hooks_daemon/core/input_schemas.py`
- Validators cached per event type (compilation happens once)
- Performance: ~0.03ms overhead per event

**Behavior Modes**:

1. **Fail-Open (Default)**: Validation enabled, errors logged but processing continues
   - Logs validation failures at WARNING level
   - Dispatches to handlers normally
   - Resilient to schema changes and edge cases

2. **Fail-Closed (Strict Mode)**: Validation enabled, errors block processing
   - Logs validation failures at ERROR level
   - Returns error response to Claude Code
   - Does NOT dispatch to handlers
   - Use for debugging and testing

3. **Disabled**: Validation completely off
   - No validation overhead
   - Use only if validation causes issues

**Configuration**:
```yaml
daemon:
  input_validation:
    enabled: true              # Master switch (default: true)
    strict_mode: false         # Fail-closed on errors (default: false)
    log_validation_errors: true
```

**Environment Variables** (override config):
- `HOOKS_DAEMON_INPUT_VALIDATION=true|false` - Enable/disable validation
- `HOOKS_DAEMON_VALIDATION_STRICT=true|false` - Enable/disable strict mode

**Example Validation Errors**:
```
PostToolUse validation failed:
  - tool_response: required field missing
  - tool_output: unexpected field (should be tool_response)

PermissionRequest validation failed:
  - permission_suggestions: required field missing
  - permission_type: unexpected field
```

**Supported Event Types**:
- PreToolUse, PostToolUse, SessionStart, SessionEnd, Stop
- PreCompact, UserPromptSubmit, PermissionRequest, Notification
- SubagentStop

**Design Rationale**:
- Validates at system boundary (fail fast)
- Single source of truth for valid event structure
- Handlers can trust input is well-formed
- Catches bugs during development without blocking production
- Performance overhead is negligible (~0.03ms)

### Init Script

**File**: `init.sh`

Bash functions for daemon lifecycle:

- `is_daemon_running()` - Check if daemon alive (PID file + process check)
- `start_daemon()` - Launch daemon in background, wait for socket
- `ensure_daemon()` - Start if not running (lazy startup)
- `send_request()` - Send JSON to socket via netcat (Python fallback)

Exported variables:
- `SOCKET_PATH` - Project-specific socket path
- `PID_FILE` - Project-specific PID file path
- `PROJECT_ROOT` - Detected project root directory

### Forwarder Scripts

**Files**: `hooks/pre-tool-use`, `hooks/post-tool-use`, `hooks/session-start`

Thin bash scripts that:
1. Source `init.sh` for daemon functions
2. Call `ensure_daemon()` (lazy startup)
3. Read hook input from stdin
4. Build JSON request with event name
5. Call `send_request()` to send to daemon
6. Output response to stdout

**Example** (`hooks/pre-tool-use`):
```bash
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"

ensure_daemon || { echo "ERROR: Failed to start daemon" >&2; exit 1; }

HOOK_INPUT=$(cat)
REQUEST_JSON=$(cat <<JSON
{
    "event": "PreToolUse",
    "hook_input": $HOOK_INPUT
}
JSON
)

send_request "$REQUEST_JSON"
```

### Configuration

**File**: `.claude/hooks-daemon.yaml`

```yaml
version: 2.0

# Daemon configuration
daemon:
  idle_timeout_seconds: 600  # Auto-shutdown after 10 minutes
  log_level: INFO

  # Input validation (v2.2.0+)
  input_validation:
    enabled: true              # Validate hook inputs (default: true)
    strict_mode: false         # Fail-closed on errors (default: false)
    log_validation_errors: true

# Handler configuration
handlers:
  pre_tool_use:
    destructive_git: {enabled: true, priority: 10}
    sed_blocker: {enabled: true, priority: 10}
    absolute_path: {enabled: true, priority: 12}
    worktree_file_copy: {enabled: true, priority: 15}
    git_stash: {enabled: true, priority: 20}
    eslint_disable: {enabled: true, priority: 30}
    tdd_enforcement: {enabled: true, priority: 35}
    web_search_year: {enabled: true, priority: 55}
    british_english: {enabled: true, priority: 60}

  post_tool_use: {}
  session_start: {}

plugins: []
```

### Daemon CLI

**Module**: `claude_code_hooks_daemon.daemon.cli`

Commands:
```bash
python3 -m claude_code_hooks_daemon.daemon.cli start   # Start daemon
python3 -m claude_code_hooks_daemon.daemon.cli stop    # Stop daemon
python3 -m claude_code_hooks_daemon.daemon.cli status  # Check if running
python3 -m claude_code_hooks_daemon.daemon.cli restart # Restart daemon
```

## Multi-Project Support

### Socket Namespacing

Each project gets its own daemon instance with unique socket path:

```python
from claude_code_hooks_daemon.daemon.paths import get_socket_path, get_pid_path
from pathlib import Path

project_a = Path("/home/dev/project-alpha")
get_socket_path(project_a)
# Returns: /tmp/claude-hooks-project-alpha-54357d86.sock

project_b = Path("/home/dev/project-beta")
get_socket_path(project_b)
# Returns: /tmp/claude-hooks-project-beta-45b4583e.sock
```

### Example Scenario

```
PROJECT A (/home/dev/alpha)
  Claude CLI Session 1 ────┐
  Claude CLI Session 2 ────┤───▶ Daemon Instance A
  Claude CLI Session 3 ────┘     socket: alpha-54357d86.sock

PROJECT B (/home/dev/beta)
  Claude CLI Session 4 ─────────▶ Daemon Instance B
                                  socket: beta-45b4583e.sock
```

- Same project = shared daemon (efficient)
- Different projects = isolated daemons (safe)

## Performance

### Benchmarks

**Before (Direct Process Spawn)**:
- ~21ms per hook call (Python interpreter startup + module loading)

**After (Daemon)**:
- ~85ms first call (daemon startup + handler loading)
- **<1ms** subsequent calls (warm socket communication)

**Speedup**: 20x faster after warmup

### Idle Timeout

Default: 600 seconds (10 minutes)

After 10 minutes of no hook calls:
1. Daemon detects idle timeout
2. Graceful shutdown initiated
3. Socket and PID files cleaned up
4. Next hook call automatically restarts daemon (lazy startup)

## Troubleshooting

### Daemon Won't Start

**Check socket file**:
```bash
ls -la /tmp/claude-hooks-*
```

If stale socket exists:
```bash
rm /tmp/claude-hooks-*.sock
```

**Check PID file**:
```bash
cat /tmp/claude-hooks-*.pid
ps aux | grep <pid>
```

If stale PID:
```bash
rm /tmp/claude-hooks-*.pid
```

### Permission Errors

Socket files require read/write permissions:
```bash
chmod 755 .claude/hooks/*
chmod 755 .claude/init.sh
```

### Daemon Crashes

Check logs:
```bash
tail -f .claude/hooks/daemon.log
```

Restart daemon:
```bash
python3 -m claude_code_hooks_daemon.daemon.cli restart
```

### Multiple Projects Conflict

Each project has unique socket - no conflicts possible.

Verify socket paths:
```bash
# From project A
echo $SOCKET_PATH

# From project B
echo $SOCKET_PATH
```

Should be different based on project path hash.

## Development

### Running Tests

```bash
# All tests
pytest

# Daemon tests only
pytest tests/daemon/

# With coverage
pytest --cov=claude_code_hooks_daemon --cov-report=html
```

### Test Structure

```
tests/daemon/
├── test_config.py      # DaemonConfig dataclass tests
├── test_paths.py       # Socket path generation tests (14 tests)
├── test_server.py      # HooksDaemon server tests
└── __init__.py
```

### Adding New Handlers

Handlers are loaded by `FrontController` - see `CLAUDE/ARCHITECTURE.md` in main repo.

Daemon automatically picks up new handlers on restart.

## Architecture Decisions

### Why Python (not Go)?

See Plan 104 research in site repo.

**TL;DR**: Python's `importlib` provides superior extensibility for project handlers vs Go plugins.

### Why Unix Sockets (not TCP)?

- Faster (no TCP/IP stack overhead)
- More secure (filesystem permissions)
- No port conflicts
- Standard pattern (Docker, MySQL, PostgreSQL)

### Why Asyncio (not Threading)?

- Hook handling is I/O-bound (read config, dispatch)
- Simpler for socket servers
- No GIL concerns (single thread)
- Standard library (no dependencies)

### Why Netcat (not pure Python)?

- Netcat universally available on Unix systems
- Simple one-liner socket communication
- Python fallback ensures portability

## Files

### Source Code

```
src/claude_code_hooks_daemon/daemon/
├── __init__.py         # Daemon package
├── server.py           # HooksDaemon asyncio server (~200 lines)
├── config.py           # DaemonConfig dataclass (~50 lines)
├── paths.py            # Socket path generation (~50 lines)
└── cli.py              # CLI commands (~150 lines)
```

### Tests

```
tests/daemon/
├── __init__.py
├── test_server.py      # Server tests
├── test_config.py      # Config tests
└── test_paths.py       # Path generation tests (14 tests)
```

### Scripts

```
init.sh                 # Daemon lifecycle functions (~100 lines)
install.py              # Installer script
hooks/
├── pre-tool-use        # Forwarder script
├── post-tool-use       # Forwarder script
└── session-start       # Forwarder script
```

## Related Documentation

- [ARCHITECTURE.md](../CLAUDE/ARCHITECTURE.md) - Handler system architecture
- [HANDLER_DEVELOPMENT.md](../CLAUDE/HANDLER_DEVELOPMENT.md) - Guide for creating custom handlers

## Status

✅ **Production Ready**

The daemon system is fully implemented and tested with comprehensive test coverage and documentation.

## License

Same as parent project.
