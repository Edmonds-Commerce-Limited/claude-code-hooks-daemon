# Implementation Plan: Daemon-Based Status Line System

**Plan ID**: 00006-daemon-statusline
**Created**: 2026-01-28
**Status**: Pending Approval

## Overview

Replace the current bash-based statusline with a daemon-powered system that accepts Claude data via socket and returns formatted status line text. This provides:
- **20x faster** response (socket vs process spawn)
- **Rich context**: Full Claude data + daemon health stats
- **Modular design**: Easy to extend with new components

## User Requirements

1. ✅ Single hard-coded statusline (not configurable yet)
2. ✅ Modular code architecture
3. ✅ Color-coded context percentage (from Claude data)
4. ✅ Display: model name, context %, git branch, daemon health
5. ✅ SessionStart handler to suggest statusline to users

## Architecture

### Event Flow
```
Claude Code (calls statusline)
  ↓
.claude/hooks/status-line (bash script)
  ↓
Daemon socket (Status event)
  ↓
DaemonController → EventRouter → HandlerChain
  ↓
Non-terminal handlers (accumulate text fragments):
  - model_context.py    (priority 10): "Model | Ctx: 42%"
  - git_branch.py       (priority 20): "| main"
  - daemon_stats.py     (priority 30): "| ⚡ 12.3s | 45MB"
  ↓
Concatenate all context → return plain text
  ↓
Claude Code displays in status bar
```

### Key Design Decisions

1. **Event Type**: Add `STATUS_LINE = "Status"` to `EventType` enum
   - Matches Claude Code's `hook_event_name: "Status"` in docs

2. **Non-Terminal Handlers**: All handlers are `terminal=False`
   - Accumulate text fragments in `result.context`
   - Final concatenation happens in response formatting

3. **Output Format**: Plain text with ANSI codes (NOT JSON hookSpecificOutput)
   - Special case: Status event returns raw text, not JSON
   - Join context list with spaces (no double newlines)

4. **Color Coding**: Context percentage uses traffic light colors
   - Green (0-40%): `\033[42m\033[30m`
   - Yellow (41-60%): `\033[43m\033[30m`
   - Orange (61-80%): `\033[48;5;208m\033[30m`
   - Red (81-100%): `\033[41m\033[97m`

## Implementation Steps

### Phase 1: Core Infrastructure

#### 1.1 Add STATUS_LINE Event Type
**File**: `src/claude_code_hooks_daemon/core/event.py`

```python
class EventType(StrEnum):
    # ... existing events ...
    STATUS_LINE = "Status"  # NEW
```

#### 1.2 Define Input Schema
**File**: `src/claude_code_hooks_daemon/core/input_schemas.py`

```python
STATUS_LINE_INPUT_SCHEMA = {
    "type": "object",
    "required": ["hook_event_name"],
    "properties": {
        "hook_event_name": {"type": "string", "const": "Status"},
        "session_id": {"type": "string"},
        "model": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "display_name": {"type": "string"}
            }
        },
        "context_window": {
            "type": "object",
            "properties": {
                "used_percentage": {"type": "number"},
                "total_input_tokens": {"type": "number"},
                "context_window_size": {"type": "number"}
            }
        },
        "workspace": {
            "type": "object",
            "properties": {
                "current_dir": {"type": "string"},
                "project_dir": {"type": "string"}
            }
        },
        "cost": {"type": "object"}
    },
    "additionalProperties": True
}

# Add to INPUT_SCHEMAS dict
INPUT_SCHEMAS["Status"] = STATUS_LINE_INPUT_SCHEMA
```

#### 1.3 Create Bash Hook Entry Point
**File**: `.claude/hooks/status-line` (new file)

```bash
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"

# Ensure daemon is running (lazy startup)
if ! ensure_daemon; then
    # Fallback: output minimal status if daemon fails
    echo "Claude | Ctx: N/A"
    exit 0
fi

# Pipe JSON directly through socket
# Note: Status event expects plain text response, not JSON
jq -c '{event: "Status", hook_input: .}' | send_request_stdin | jq -r '.result.text // "Claude"'
```

**Important**: Make executable: `chmod +x .claude/hooks/status-line`

### Phase 2: Status Line Handlers

Create modular handlers in `src/claude_code_hooks_daemon/handlers/status_line/`

#### 2.1 Model + Context Handler
**File**: `src/claude_code_hooks_daemon/handlers/status_line/model_context.py`

```python
from claude_code_hooks_daemon.core import Handler, HookResult
from typing import Any

class ModelContextHandler(Handler):
    """Format model name and color-coded context percentage."""

    def __init__(self) -> None:
        super().__init__(
            name="status-model-context",
            priority=10,
            terminal=False,
            tags=["status", "display", "non-terminal"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True  # Always run for status events

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        # Extract data
        model = hook_input.get("model", {}).get("display_name", "Claude")
        ctx_data = hook_input.get("context_window", {})
        used_pct = ctx_data.get("used_percentage", 0)

        # Color code by percentage
        if used_pct <= 40:
            color = "\033[42m\033[30m"  # Green bg, black text
        elif used_pct <= 60:
            color = "\033[43m\033[30m"  # Yellow bg
        elif used_pct <= 80:
            color = "\033[48;5;208m\033[30m"  # Orange bg
        else:
            color = "\033[41m\033[97m"  # Red bg, white text
        reset = "\033[0m"

        # Format: "Model | Ctx: XX%"
        status = f"{model} | Ctx: {color}{used_pct:.1f}%{reset}"

        return HookResult(context=[status])
```

#### 2.2 Git Branch Handler
**File**: `src/claude_code_hooks_daemon/handlers/status_line/git_branch.py`

```python
import subprocess
from pathlib import Path
from claude_code_hooks_daemon.core import Handler, HookResult
from typing import Any

class GitBranchHandler(Handler):
    """Show current git branch if in a git repo."""

    def __init__(self) -> None:
        super().__init__(
            name="status-git-branch",
            priority=20,
            terminal=False,
            tags=["status", "git", "non-terminal"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        workspace = hook_input.get("workspace", {})
        cwd = workspace.get("current_dir") or workspace.get("project_dir")

        if not cwd or not Path(cwd).exists():
            return HookResult(context=[])

        try:
            # Check if in git repo
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=cwd,
                capture_output=True,
                timeout=0.5,
                check=False
            )

            if result.returncode != 0:
                return HookResult(context=[])  # Not a git repo

            # Get current branch
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=cwd,
                capture_output=True,
                timeout=0.5,
                check=True
            )

            branch = result.stdout.decode().strip()
            if branch:
                return HookResult(context=[f"| {branch}"])

        except Exception:
            # Fail silently - git errors shouldn't break status line
            pass

        return HookResult(context=[])
```

#### 2.3 Daemon Stats Handler
**File**: `src/claude_code_hooks_daemon/handlers/status_line/daemon_stats.py`

```python
import logging
import psutil
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.daemon.controller import get_controller
from typing import Any

logger = logging.getLogger(__name__)

class DaemonStatsHandler(Handler):
    """Show daemon health: uptime, memory, last error, log level."""

    def __init__(self) -> None:
        super().__init__(
            name="status-daemon-stats",
            priority=30,
            terminal=False,
            tags=["status", "daemon", "health", "non-terminal"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        parts = []

        try:
            # Get daemon stats
            controller = get_controller()
            stats = controller.get_stats()

            # Uptime
            uptime = stats.uptime_seconds
            if uptime < 60:
                uptime_str = f"{uptime:.1f}s"
            elif uptime < 3600:
                uptime_str = f"{uptime/60:.1f}m"
            else:
                uptime_str = f"{uptime/3600:.1f}h"

            # Memory usage
            process = psutil.Process()
            mem_mb = process.memory_info().rss / (1024 * 1024)

            # Log level
            log_level = logging.getLogger().level
            level_name = logging.getLevelName(log_level)

            # Format: "| ⚡ 12.3s | 45MB | INFO"
            parts.append(f"| ⚡ {uptime_str} | {mem_mb:.0f}MB | {level_name}")

            # Last error (if any)
            if stats.errors > 0:
                # Try to get last error from logs
                # For now, just show error count
                parts.append(f"| ❌ {stats.errors} err")

        except Exception as e:
            logger.debug(f"Failed to get daemon stats: {e}")
            # Fail silently - don't break status line

        return HookResult(context=parts)
```

#### 2.4 Handler Package Init
**File**: `src/claude_code_hooks_daemon/handlers/status_line/__init__.py`

```python
"""Status line handlers for formatting daemon-based status display."""

from claude_code_hooks_daemon.handlers.status_line.model_context import ModelContextHandler
from claude_code_hooks_daemon.handlers.status_line.git_branch import GitBranchHandler
from claude_code_hooks_daemon.handlers.status_line.daemon_stats import DaemonStatsHandler

__all__ = [
    "ModelContextHandler",
    "GitBranchHandler",
    "DaemonStatsHandler",
]
```

### Phase 3: Response Formatting

#### 3.1 Update HookResult for Status Event
**File**: `src/claude_code_hooks_daemon/core/hook_result.py`

Modify `to_json()` method to handle Status event:

```python
def to_json(self, event_name: str) -> dict[str, Any]:
    """Convert to event-specific JSON format."""

    # Special case: Status event returns plain text
    if event_name == "Status":
        # Join all context fragments with spaces
        text = " ".join(self.context) if self.context else "Claude"
        return {"text": text}

    # ... existing code for other events ...
```

### Phase 4: SessionStart Suggestion Handler

#### 4.1 Create Suggestion Handler
**File**: `src/claude_code_hooks_daemon/handlers/session_start/suggest_statusline.py`

```python
from claude_code_hooks_daemon.core import Handler, HookResult
from typing import Any

class SuggestStatusLineHandler(Handler):
    """Suggest setting up daemon-based statusline on session start."""

    def __init__(self) -> None:
        super().__init__(
            name="suggest-statusline",
            priority=55,
            terminal=False,
            tags=["advisory", "workflow", "statusline", "non-terminal"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True  # Always suggest (Claude will check if already configured)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(
            context=[
                "💡 **Status Line Available**: This project has a daemon-based status line.",
                "",
                "To enable it, check if `.claude/settings.json` has a `statusLine` configuration.",
                "If not configured, consider adding:",
                "```json",
                '{',
                '  "statusLine": {',
                '    "type": "command",',
                '    "command": ".claude/hooks/status-line"',
                '  }',
                '}',
                "```",
                "",
                "The status line shows: model name, context usage %, git branch, and daemon health.",
            ]
        )
```

#### 4.2 Register Handler
**File**: `src/claude_code_hooks_daemon/handlers/session_start/__init__.py`

Add to imports and `__all__`:
```python
from claude_code_hooks_daemon.handlers.session_start.suggest_statusline import (
    SuggestStatusLineHandler,
)

__all__ = [
    # ... existing ...
    "SuggestStatusLineHandler",
]
```

### Phase 5: Configuration

#### 5.1 Update Daemon Config
**File**: `.claude/hooks-daemon.yaml`

Add handler configuration:
```yaml
handlers:
  status_line:
    model_context: {enabled: true, priority: 10}
    git_branch: {enabled: true, priority: 20}
    daemon_stats: {enabled: true, priority: 30}
  session_start:
    suggest_statusline: {enabled: true, priority: 55}
```

#### 5.2 Update Claude Settings
**File**: `.claude/settings.json`

Replace existing statusLine with:
```json
{
  "statusLine": {
    "type": "command",
    "command": ".claude/hooks/status-line"
  }
}
```

## Critical Files

### New Files
- `.claude/hooks/status-line` - Bash entry point
- `src/claude_code_hooks_daemon/handlers/status_line/__init__.py`
- `src/claude_code_hooks_daemon/handlers/status_line/model_context.py`
- `src/claude_code_hooks_daemon/handlers/status_line/git_branch.py`
- `src/claude_code_hooks_daemon/handlers/status_line/daemon_stats.py`
- `src/claude_code_hooks_daemon/handlers/session_start/suggest_statusline.py`

### Modified Files
- `src/claude_code_hooks_daemon/core/event.py` - Add STATUS_LINE event
- `src/claude_code_hooks_daemon/core/input_schemas.py` - Add STATUS_LINE schema
- `src/claude_code_hooks_daemon/core/hook_result.py` - Handle Status response format
- `src/claude_code_hooks_daemon/handlers/session_start/__init__.py` - Register handler
- `.claude/hooks-daemon.yaml` - Add handler configs
- `.claude/settings.json` - Update statusLine command

## Verification Plan

### 1. Unit Tests
```bash
# Test handler logic
pytest tests/unit/handlers/test_status_line.py -v

# Test event parsing
pytest tests/unit/core/test_event.py::test_status_line_event -v

# Test response formatting
pytest tests/unit/core/test_hook_result.py::test_status_response_format -v
```

### 2. Integration Test
```bash
# Test full flow: bash → socket → handlers → response
pytest tests/integration/test_status_line_flow.py -v
```

### 3. Manual Testing
```bash
# 1. Restart daemon
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart

# 2. Test status-line hook directly
echo '{"hook_event_name":"Status","model":{"display_name":"Sonnet"},"context_window":{"used_percentage":42.5}}' | \
  .claude/hooks/status-line

# Expected output: "Sonnet | Ctx: 42.5% | main | ⚡ 1.2s | 45MB | INFO"

# 3. Test in Claude Code
# Start a new session and verify:
#   - Status line appears at bottom
#   - Shows model name
#   - Context % is color-coded (green/yellow/orange/red)
#   - Git branch shows if in repo
#   - Daemon stats show uptime and memory

# 4. Test SessionStart suggestion
# Start fresh session, check for statusline suggestion in context
```

### 4. Performance Test
```bash
# Compare old bash vs new daemon approach
time (for i in {1..100}; do echo '{}' | .claude/hooks/status-line > /dev/null; done)

# Expected: ~20x faster after warmup (0.02s vs 0.4s for 100 calls)
```

## Rollback Plan

If issues occur:

1. **Revert settings.json**: Restore old bash statusLine command
2. **Disable handlers**: Set `enabled: false` in `.claude/hooks-daemon.yaml`
3. **Remove files**: Delete `.claude/hooks/status-line` and handler files

## Future Enhancements (NOT in this PR)

- [ ] Make components configurable via YAML (enable/disable git, daemon stats, etc.)
- [ ] Add more components: cost tracking, task count, active agents
- [ ] Support custom formatting templates
- [ ] Cache expensive operations (git, memory checks)
- [ ] Add metrics: track statusline render time

## Documentation Updates

After implementation:
- Update `README.md` with statusline feature
- Add `CLAUDE/STATUS_LINE.md` explaining architecture
- Update `CLAUDE.md` with handler count

---

**Ready for Approval**: This plan implements a simple, modular daemon-based statusline with the requested components (model, context %, git branch, daemon health). All code follows existing patterns and maintains backward compatibility.

## Sources

- [Status line configuration - Claude Code Docs](https://code.claude.com/docs/en/statusline)
- [Shipyard | Claude Code CLI Cheatsheet](https://shipyard.build/blog/claude-code-cheat-sheet/)
- [GitHub - ccstatusline projects](https://github.com/sirmalloc/ccstatusline)
