---
name: mode
description: Get or set daemon operating mode - switch between default and unattended (blocks Stop events)
argument-hint: "[get|unattended|default] [message]"
---

# /mode - Daemon Mode Management

## Description

View or change the daemon's operating mode. Supports `default` (normal operation) and `unattended` (blocks Stop events to keep Claude working autonomously).

## Usage

```bash
# Show current mode
/mode
/mode get

# Switch to unattended mode (blocks Stop events)
/mode unattended

# Switch to unattended with custom task message
/mode unattended finish the release and run all tests

# Switch back to default mode
/mode default
```

## Modes

| Mode | Behavior |
|------|----------|
| `default` | Normal operation - all handlers process events as configured |
| `unattended` | Blocks Stop events unconditionally to keep Claude working without interruption |

## What Unattended Mode Does

When enabled, a **mode interceptor** runs before the handler chain on every event:
- **Stop events**: Blocked with a DENY response instructing Claude to continue working
- **SubagentStop events**: NOT blocked (subagents should stop normally)
- **All other events**: Pass through to normal handler chain unchanged

The interceptor includes re-entry protection (checks `stop_hook_active` flag) to prevent infinite loops.

## Custom Messages

When switching to unattended mode, you can include a custom message that gets appended to the block reason. This lets you give Claude specific instructions about what to work on:

```bash
/mode unattended complete all remaining tasks in the plan
```

The message appears in the Stop event denial reason, so Claude sees it when it tries to stop.

## Python Path Detection

The skill detects the correct Python path automatically:

```bash
if [ -f "/workspace/untracked/venv/bin/python" ]; then
    PYTHON="/workspace/untracked/venv/bin/python"
elif [ -f ".claude/hooks-daemon/untracked/venv/bin/python" ]; then
    PYTHON=".claude/hooks-daemon/untracked/venv/bin/python"
fi
```

## IPC Protocol

The skill communicates with the daemon via Unix socket system requests:

**Get mode:**
```json
{"event": "_system", "hook_input": {"action": "get_mode"}}
```

**Set mode:**
```json
{"event": "_system", "hook_input": {"action": "set_mode", "mode": "unattended", "custom_message": "optional"}}
```

## Output

### On get mode:
```
Mode: default
```

### On set unattended:
```
Mode: unattended (changed)
Message: finish the release
```

### On set default:
```
Mode: default (changed)
```

## Requirements

- Daemon must be running
- Python venv must be available (self-install or normal install)

## Version

Introduced in: v2.17.0
