---
name: configure
description: View and modify hooks daemon handler configuration - enable/disable handlers, change priorities, set handler options
argument-hint: "[list|<handler>|<handler> <option>=<value>]"
---

# /configure - Handler Configuration Skill

## Description

View and modify the hooks daemon configuration interactively. Supports listing handlers, viewing individual handler settings, and changing options (enabled, priority, handler-specific options) with automatic daemon restart and verification.

## Usage

```bash
# Show summary of current config (daemon settings + handler overview)
/configure

# List all handlers with their configurable options
/configure list

# Show config for one handler
/configure sed_blocker

# Set a handler option
/configure sed_blocker blocking_mode=direct_invocation_only

# Disable a handler
/configure sed_blocker enabled=false

# Re-enable a handler
/configure sed_blocker enabled=true

# Override a handler's priority
/configure sed_blocker priority=15

# Set options on handlers with nested options block
/configure git_stash mode=deny
/configure markdown_organization track_plans_in_project=CLAUDE/Plan
```

## Parameters

- **handler** (optional): Handler config key (e.g., `destructive_git`, `sed_blocker`)
  - If omitted: Show config summary
  - If `list`: Show all handlers with options
- **option=value** (optional): Key-value pair to set
  - `enabled=true|false` -- Enable or disable the handler
  - `priority=N` -- Override handler priority (integer)
  - `<option_key>=<value>` -- Set a handler-specific option

## What It Does

### Show Summary (`/configure`)

1. Reads `.claude/hooks-daemon.yaml`
2. Displays daemon settings (log_level, idle_timeout, etc.)
3. Lists all handlers grouped by event type with enabled/disabled status and priority

### List Handlers (`/configure list`)

1. Reads `.claude/hooks-daemon.yaml`
2. For each handler, shows:
   - Config key, event type, enabled status, priority
   - Any configurable options and their current values
   - Available options from source code (with defaults)

### Show Handler (`/configure <handler>`)

1. Reads `.claude/hooks-daemon.yaml`
2. Locates handler under its event type section
3. Displays all current settings and available options
4. Cross-references `docs/guides/HANDLER_REFERENCE.md` for description

### Set Option (`/configure <handler> <option>=<value>`)

1. Reads `.claude/hooks-daemon.yaml`
2. Locates the handler under `handlers.<event_type>`
3. Updates the setting:
   - `enabled` and `priority`: Set directly on the handler block
   - Other options: Set under the handler's `options:` sub-block
4. Saves the file (preserving YAML structure and comments where possible)
5. Restarts daemon to apply changes
6. Verifies daemon status is RUNNING
7. Reports result

## Python Path Detection

The skill detects the correct Python path automatically:

```bash
# Self-install mode (daemon development)
if [ -f "/workspace/untracked/venv/bin/python" ]; then
    PYTHON="/workspace/untracked/venv/bin/python"
# Normal install mode
elif [ -f ".claude/hooks-daemon/untracked/venv/bin/python" ]; then
    PYTHON=".claude/hooks-daemon/untracked/venv/bin/python"
fi
```

## Handler Options Reference

**📖 Single source of truth: [Handler Reference](../../docs/guides/HANDLER_REFERENCE.md)**

Every handler's configurable options, values, defaults, and examples are documented there. Do not duplicate that content here.

Quick examples of what options look like:
- `sed_blocker` → `blocking_mode` (`strict` | `direct_invocation_only`)
- `git_stash` → `mode` (`warn` | `deny`)
- `markdown_organization` → `track_plans_in_project`, `plan_workflow_docs`

All handlers also accept the common properties `enabled` (bool) and `priority` (int).

Use `/configure list` to see what options are set in your current config.

## Config File Location

The skill reads and writes to:

```
<project-root>/.claude/hooks-daemon.yaml
```

## Output

### On successful option change:

```
Updated sed_blocker.options.blocking_mode = direct_invocation_only

Restarting daemon...
Daemon: RUNNING (PID 12345)

Change applied successfully.
```

### On show handler:

```
Handler: sed_blocker
  Event type: pre_tool_use
  Enabled: true
  Priority: 11
  Type: Blocking

  Options:
    blocking_mode: strict (default)
      Values: strict | direct_invocation_only
      Description: Controls which invocations are blocked
```

## Error Handling

**Handler not found:**
```
Handler "destrutive_git" not found.
Did you mean: destructive_git?
```

**Invalid option:**
```
Unknown option "blcoking_mode" for sed_blocker.
Available options: blocking_mode
```

**Daemon fails to restart:**
```
WARNING: Daemon failed to start after config change.
Check logs: $PYTHON -m claude_code_hooks_daemon.daemon.cli logs
Consider reverting the change.
```

## Requirements

- `.claude/hooks-daemon.yaml` must exist
- Python venv must be available (self-install or normal install)
- Daemon must be installed and operational

## Documentation

**SINGLE SOURCE OF TRUTH:** @docs/guides/CONFIGURATION.md for config syntax
Handler options: @docs/guides/HANDLER_REFERENCE.md

## Version

Introduced in: v2.16.0
