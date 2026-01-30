# Status Line System Architecture

**Last Updated**: January 2026

---

## Overview

The status line system provides a real-time information display in the Claude Code terminal, showing model name, context window usage, git branch, account identity, and daemon health metrics. It is implemented as a hook event type (`status_line`) processed by the daemon, making it approximately 20x faster than spawning individual processes for each status update.

Claude Code calls the status line hook repeatedly during a session to refresh the terminal status bar. Because this runs frequently, performance is critical -- the daemon-based architecture avoids process spawn overhead entirely after the initial warmup.

---

## Architecture

### Data Flow

```
Claude Code
    |
    | Calls .claude/hooks/status-line (bash script)
    | Passes JSON via stdin: { model, context_window, workspace, ... }
    |
    v
.claude/hooks/status-line
    |
    | source .claude/init.sh (ensure daemon running)
    | jq: adds hook_event_name, wraps in {event: "Status", hook_input: ...}
    | Pipes JSON to daemon via Unix socket (send_request_stdin)
    |
    v
Daemon (Unix socket server)
    |
    | FrontController routes to EventType.STATUS_LINE
    | HandlerChain executes all matching handlers in priority order
    | All status line handlers are non-terminal (accumulate context)
    |
    v
HandlerChain returns ChainExecutionResult
    |
    | HookResult.to_json("Status") joins context[] with spaces
    | Returns: {"text": "username | Model | Ctx: 12.3% | main | hook-icon 5.2m 34MB | INFO"}
    |
    v
.claude/hooks/status-line
    |
    | jq: extracts .result.context, joins with space
    | Outputs plain text to stdout
    |
    v
Claude Code displays in terminal status bar
```

### Key Components

| Component | Path | Role |
|-----------|------|------|
| Hook script | `.claude/hooks/status-line` | Entry point; forwards JSON to daemon, extracts text output |
| Init script | `.claude/init.sh` | Daemon lifecycle (ensure running, send via socket) |
| Handler chain | `src/claude_code_hooks_daemon/core/chain.py` | Executes handlers in priority order, accumulates context |
| HookResult | `src/claude_code_hooks_daemon/core/hook_result.py` | `to_json("Status")` joins context array into plain text |
| Handler registry | `src/claude_code_hooks_daemon/handlers/registry.py` | Maps `status_line` directory to `EventType.STATUS_LINE` |
| Handlers | `src/claude_code_hooks_daemon/handlers/status_line/` | Individual status line handlers |
| Configuration | `.claude/hooks-daemon.yaml` | Enable/disable handlers, set priorities |
| Settings | `.claude/settings.json` | Registers `statusLine.command` with Claude Code |

---

## Handler Chain

All status line handlers are **non-terminal** (`terminal=False`). They all return `matches() = True` for every status event (except `UsageTrackingHandler` which is currently disabled). Each handler contributes context fragments that are accumulated and joined with spaces.

### Handler Execution Order

| Priority | Handler | Config Key | Output Example | Data Source |
|----------|---------|------------|----------------|-------------|
| 5 | `AccountDisplayHandler` | `account_display` | `username \|` | `~/.claude/.last-launch.conf` |
| 10 | `ModelContextHandler` | `model_context` | `Claude Opus 4.5 \| Ctx: [colored]12.3%[/colored]` | `hook_input.model`, `hook_input.context_window` |
| 15 | `UsageTrackingHandler` | `usage_tracking` | `\| daily: 45.2% \| weekly: 23.1%` | `~/.claude/stats-cache.json` (DISABLED) |
| 20 | `GitBranchHandler` | `git_branch` | `\| main` | `git branch --show-current` subprocess |
| 30 | `DaemonStatsHandler` | `daemon_stats` | `\| hook-icon 5.2m 34MB \| INFO` | `DaemonController.get_stats()`, `psutil` |

### Handler Details

#### AccountDisplayHandler (Priority 5)

- **Purpose**: Shows the logged-in Claude account username
- **Data source**: Reads `~/.claude/.last-launch.conf`, extracts `LAST_TOKEN="..."` via regex
- **Output format**: `{username} |`
- **Failure mode**: Returns empty context (silent fail)

#### ModelContextHandler (Priority 10)

- **Purpose**: Shows model display name and color-coded context window usage
- **Data source**: `hook_input["model"]["display_name"]` and `hook_input["context_window"]["used_percentage"]`
- **Output format**: `{model} | Ctx: {colored_percentage}`
- **Color coding** (ANSI escape codes, traffic light system):
  - 0-40%: Green background, black text
  - 41-60%: Yellow background, black text
  - 61-80%: Orange background, black text
  - 81-100%: Red background, white text
- **Failure mode**: Defaults to "Claude" model name, 0% usage

#### UsageTrackingHandler (Priority 15) -- CURRENTLY DISABLED

- **Purpose**: Shows daily and weekly token usage percentages
- **Data source**: `~/.claude/stats-cache.json` via `stats_cache_reader.py`
- **Status**: Disabled (`matches()` returns `False`). The approach is flawed because `stats-cache.json` only contains completed historical days, daily limits are hardcoded, and there is no reliable way to get real-time current-day token counts.
- **Supporting module**: `stats_cache_reader.py` provides `read_stats_cache()`, `calculate_daily_usage()`, `calculate_weekly_usage()` with hardcoded daily limits (200k Sonnet, 100k Opus)
- **Options**: `show_daily` (bool), `show_weekly` (bool)

#### GitBranchHandler (Priority 20)

- **Purpose**: Shows current git branch
- **Data source**: Runs `git rev-parse --show-toplevel` then `git branch --show-current` as subprocesses
- **Output format**: `| {branch_name}`
- **Working directory**: Uses `hook_input["workspace"]["current_dir"]` or `["project_dir"]`
- **Timeout**: `Timeout.GIT_STATUS_SHORT` (defined in constants)
- **Failure mode**: Returns empty context on non-git directories, subprocess errors, or timeouts

#### DaemonStatsHandler (Priority 30)

- **Purpose**: Shows daemon health metrics
- **Data source**: `DaemonController.get_stats()` for uptime/errors, `psutil.Process().memory_info()` for memory
- **Output format**: `| hook-icon {uptime}{memory} | {log_level}` and optionally `| error-icon {count} err`
- **Uptime formatting**: `<60s` = seconds, `<3600s` = minutes, `>=3600s` = hours
- **Memory**: Only shown if `psutil` package is available
- **Error count**: Only shown if `stats.errors > 0`
- **Failure mode**: Returns empty context (silent fail)

---

## Output Format

### How Context Fragments Become Text

1. Each handler returns `HookResult(context=[...])` with a list of string fragments
2. The `HandlerChain` accumulates all context lists from non-terminal handlers into a single list
3. `HookResult.to_json("Status")` joins all context items with a single space: `" ".join(self.context)`
4. The result is `{"text": "joined string"}` (note: NOT the standard `hookSpecificOutput` format)
5. The bash hook script extracts `.result.context | join(" ")` via jq

### Example Composed Output

```
jdoe | Claude Opus 4.5 | Ctx: [green]12.3%[/green] | main | hook-icon 5.2m 34MB | INFO
```

### Separator Convention

Handlers use `|` (pipe with surrounding spaces) as the visual separator between sections. Each handler is responsible for including its own leading `|` separator (except `AccountDisplayHandler` which includes a trailing `|`).

---

## Configuration

### Claude Code Settings (`settings.json`)

The status line hook is registered in `.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": ".claude/hooks/status-line"
  }
}
```

### Daemon Configuration (`hooks-daemon.yaml`)

Each handler can be enabled/disabled and have its priority overridden:

```yaml
handlers:
  status_line:
    account_display:
      enabled: true
      priority: 5

    model_context:
      enabled: true
      priority: 10

    usage_tracking:
      enabled: true       # Note: handler also self-disables via matches()
      priority: 15
      options:
        show_daily: true
        show_weekly: true

    git_branch:
      enabled: true
      priority: 20

    daemon_stats:
      enabled: true
      priority: 30
```

### Disabling a Handler

Set `enabled: false` in `hooks-daemon.yaml`:

```yaml
handlers:
  status_line:
    daemon_stats:
      enabled: false
```

### Reordering Handlers

Change the `priority` value. Lower numbers execute first and appear earlier (leftmost) in the output:

```yaml
handlers:
  status_line:
    git_branch:
      priority: 8   # Move git branch before model context
```

---

## Performance

### Why It Is Fast

1. **No process spawn**: After daemon warmup, all status updates go through an already-running Python process via Unix socket IPC. This avoids the ~200ms Python interpreter startup cost on every call.
2. **Non-terminal chain**: All handlers execute in a single pass through the chain. No early exits, no re-dispatching.
3. **Minimal I/O**: Most handlers read from in-memory state or fast local files. Only `GitBranchHandler` shells out to a subprocess.
4. **Silent failures**: Every handler catches exceptions and returns empty context rather than crashing the chain.

### Performance Characteristics by Handler

| Handler | I/O Type | Expected Latency |
|---------|----------|-----------------|
| `AccountDisplayHandler` | File read (`~/.claude/.last-launch.conf`) | <1ms |
| `ModelContextHandler` | In-memory (from hook_input) | <0.1ms |
| `UsageTrackingHandler` | File read (`stats-cache.json`) | <1ms (disabled) |
| `GitBranchHandler` | Subprocess (`git`) | 5-50ms |
| `DaemonStatsHandler` | In-process (`get_stats()` + `psutil`) | <2ms |

### Total Expected Latency

Under normal conditions, the full status line handler chain completes in **10-60ms**, dominated by the git subprocess call. Without git, it completes in under 5ms.

---

## Adding New Status Line Elements

### Step 1: Create Handler

Create a new file in `src/claude_code_hooks_daemon/handlers/status_line/`:

```python
"""My new status element handler."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Handler, HookResult


class MyElementHandler(Handler):
    """Display my element in the status line."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MY_ELEMENT,  # Add to HandlerID first
            priority=Priority.MY_ELEMENT,      # Add to Priority first
            terminal=False,                     # MUST be False for status line
            tags=[HandlerTag.STATUS, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Generate status text."""
        # Include leading separator
        return HookResult(context=["| my-data"])
```

### Step 2: Register Constants

1. Add `HandlerIDMeta` to `src/claude_code_hooks_daemon/constants/handlers.py`
2. Add priority value to `src/claude_code_hooks_daemon/constants/priority.py`
3. Add to `HandlerKey` literal type in `handlers.py`

### Step 3: Export from Package

Add the import and `__all__` entry in `src/claude_code_hooks_daemon/handlers/status_line/__init__.py`.

### Step 4: Configure

Add to `.claude/hooks-daemon.yaml` under `handlers.status_line`.

### Step 5: Write Tests

Create `tests/handlers/status_line/test_my_element.py` with tests for `matches()` and `handle()`.

### Important Rules

- **Always set `terminal=False`** -- terminal handlers would stop the chain and suppress all subsequent status elements.
- **Always return `HookResult(context=[...])`** -- never use `decision="deny"`.
- **Always fail silently** -- catch all exceptions and return `HookResult(context=[])`.
- **Include the `|` separator** in your output fragment.
- **Priority determines position** -- lower priority = further left in the status line.

---

## Troubleshooting

### Status line shows "DAEMON FAILED"

The daemon is not running. Check:
```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
```

### Status line shows "NO STATUS DATA"

All handlers returned empty context. Check:
- Are handlers enabled in `hooks-daemon.yaml`?
- Check daemon logs: `$PYTHON -m claude_code_hooks_daemon.daemon.cli logs`

### Status line shows "ERROR: ..."

The daemon returned an error. The jq in the hook script formats `.error` from the response. Check daemon logs for details.

### Git branch not showing

- Not in a git repository
- `git` command not found or not in PATH
- Git subprocess timed out (`Timeout.GIT_STATUS_SHORT`)
- Working directory from `hook_input` does not exist

### Memory not showing in daemon stats

The `psutil` package is not installed. It is an optional dependency.

### Account name not showing

- `~/.claude/.last-launch.conf` does not exist
- File does not contain `LAST_TOKEN="..."` pattern

### Context percentage always 0%

The `hook_input.context_window.used_percentage` field is not being provided by Claude Code or is null. The handler defaults to 0.

### Changing what appears in the status line

Edit `.claude/hooks-daemon.yaml` under `handlers.status_line`. Set `enabled: false` to hide elements, or adjust `priority` to reorder them. Restart the daemon after config changes.
