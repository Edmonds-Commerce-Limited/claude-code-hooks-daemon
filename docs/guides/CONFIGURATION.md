# Configuration Guide

This guide covers everything you need to know about configuring the Claude Code Hooks Daemon.

---

## Config File Location

The daemon looks for its configuration file at:

```
<project-root>/.claude/hooks-daemon.yaml
```

It also accepts `.yml` as an extension. The daemon finds the config by searching upward from the current directory for a `.claude/` folder containing `hooks-daemon.yaml`.

You can also use JSON format (`hooks-daemon.json`), but YAML is recommended for readability.

### Generating a Config File

If you do not have a config file yet, use the `init-config` command:

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# Generate a full config with all handlers listed
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli init-config --mode full > .claude/hooks-daemon.yaml

# Generate a minimal config with just the structure
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli init-config --mode minimal > .claude/hooks-daemon.yaml
```

---

## Config Structure Overview

A complete config file has three top-level sections:

```yaml
version: "2.0"          # Config format version

daemon:                  # Daemon process settings
  # ...

handlers:                # Handler configuration by event type
  pre_tool_use:          # Handlers that run before tool execution
    # ...
  post_tool_use:         # Handlers that run after tool execution
    # ...
  session_start:         # Handlers that run at session start
    # ...
  # ... more event types

plugins:                 # Custom project-specific handlers
  # ...
```

---

## Daemon Settings

The `daemon` section controls the background process itself.

```yaml
daemon:
  idle_timeout_seconds: 600    # Shut down after N seconds of inactivity (default: 600)
  log_level: INFO              # Logging verbosity: DEBUG, INFO, WARNING, ERROR
  enable_hello_world_handlers: false  # Enable test handlers to verify hooks work
  strict_mode: false           # Fail-fast on all errors (useful for development)

  # Input validation (recommended)
  input_validation:
    enabled: true              # Validate incoming hook event data
    strict_mode: false         # true = fail-closed (deny on bad data), false = fail-open (allow)
    log_validation_errors: true
```

### Setting Details

| Setting | Default | Description |
|---------|---------|-------------|
| `idle_timeout_seconds` | `600` | Daemon shuts down after this many seconds without a hook call. It restarts automatically on the next call (lazy startup). |
| `log_level` | `INFO` | Controls how much detail appears in daemon logs. Use `DEBUG` when troubleshooting handler behavior. |
| `enable_hello_world_handlers` | `false` | Activates simple test handlers that add context to every event. Useful for confirming hooks are connected. |
| `strict_mode` | `false` | When `true`, the daemon crashes on any unexpected error instead of continuing. Recommended for development/testing. |
| `self_install_mode` | `false` | Used when the daemon runs from the project root instead of `.claude/hooks-daemon/`. Only needed for daemon development. |
| `input_validation.enabled` | `true` | Validates hook event data before processing. Catches malformed events early. |
| `input_validation.strict_mode` | `false` | When `true`, invalid events are denied. When `false`, invalid events are allowed through with a warning logged. |

---

## Handler Configuration

Handlers are grouped by the event type they respond to. Each handler has at minimum an `enabled` flag and a `priority` number.

### Basic Handler Syntax

```yaml
handlers:
  pre_tool_use:
    # Compact syntax (most common)
    destructive_git: {enabled: true, priority: 10}

    # Expanded syntax (when you need options)
    british_english:
      enabled: true
      priority: 60
      mode: warn              # Handler-specific option
      excluded_dirs:          # Handler-specific option
        - node_modules/
        - dist/
```

### Handler Properties

| Property | Required | Description |
|----------|----------|-------------|
| `enabled` | Yes | `true` to activate the handler, `false` to skip it |
| `priority` | Yes | Execution order -- lower numbers run first |
| `options` | No | Handler-specific configuration (varies per handler) |

### Enabling and Disabling Handlers

To enable a handler, set `enabled: true`. To disable it, set `enabled: false`. Changes take effect after a daemon restart:

```bash
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart
```

---

## Event Types

The daemon supports these hook event types:

| Event Type | Config Key | When It Fires |
|------------|-----------|---------------|
| PreToolUse | `pre_tool_use` | Before Claude executes a tool (Bash, Write, Read, etc.) |
| PostToolUse | `post_tool_use` | After a tool finishes executing |
| SessionStart | `session_start` | When a new Claude Code session begins |
| SessionEnd | `session_end` | When a session ends |
| PreCompact | `pre_compact` | Before conversation history is compacted |
| SubagentStop | `subagent_stop` | When a subagent completes its task |
| UserPromptSubmit | `user_prompt_submit` | When the user submits a prompt |
| PermissionRequest | `permission_request` | When a tool requests permission |
| Notification | `notification` | When a notification event occurs |
| Stop | `stop` | When Claude is about to stop responding |
| StatusLine | `status_line` | When generating the status bar display |

---

## Priority System

Priorities determine the order handlers execute within an event type. **Lower numbers run first.**

### Priority Ranges

| Range | Category | Purpose | Examples |
|-------|----------|---------|----------|
| 0-9 | Test | Test and debug handlers | `hello_world` (5) |
| 10-20 | Safety | Prevent destructive operations | `destructive_git` (10), `sed_blocker` (10), `curl_pipe_shell` (15) |
| 25-35 | Code Quality | Enforce development standards | `eslint_disable` (30), `tdd_enforcement` (35) |
| 36-55 | Workflow | Process and tool guidance | `plan_workflow` (45), `npm_command` (50), `web_search_year` (55) |
| 56-60 | Advisory | Non-blocking suggestions | `british_english` (60) |
| 100+ | Logging | Metrics and audit trails | `notification_logger` (100) |

### Why Priority Matters

When multiple handlers match the same event, they run in priority order. A safety handler at priority 10 runs before a workflow handler at priority 45.

**Terminal handlers** stop the chain when they match. If a terminal handler at priority 10 denies a command, handlers at priority 20 and above never see the event.

**Non-terminal handlers** add context but allow the chain to continue. Multiple non-terminal handlers can each contribute context to the same event.

### Customizing Priorities

You can override the default priority of any handler:

```yaml
handlers:
  pre_tool_use:
    # Move sed_blocker to run before destructive_git
    sed_blocker: {enabled: true, priority: 8}
    destructive_git: {enabled: true, priority: 10}
```

---

## Handler Options

Some handlers accept additional configuration through the `options` field or handler-specific keys.

### Handler-Specific Settings

```yaml
handlers:
  pre_tool_use:
    # British English handler with custom settings
    british_english:
      enabled: true
      priority: 60
      mode: warn             # "warn" (advisory) or "block" (deny)
      excluded_dirs:
        - node_modules/
        - dist/
        - vendor/

    # Absolute path handler with blocked prefixes
    absolute_path:
      enabled: true
      priority: 12
      blocked_prefixes:
        - /container-mount/
        - /tmp/claude-code/

    # YOLO container detection with tuning
    yolo_container_detection:
      enabled: true
      priority: 10
      min_confidence_score: 3          # Detection threshold (0-12)
      show_detailed_indicators: true   # Show what was detected
      show_workflow_tips: true         # Show container workflow tips
```

For the complete per-handler options reference (all handlers, all options, defaults, and examples), see **[Handler Reference](HANDLER_REFERENCE.md)**.

### Parent-Child Handler Relationships

Some handlers share configuration through a parent-child relationship. The child handler inherits `options` from the parent, avoiding duplication:

```yaml
handlers:
  pre_tool_use:
    # Parent handler defines shared options
    markdown_organization:
      enabled: true
      priority: 42
      options:
        track_plans_in_project: "CLAUDE/Plan"
        plan_workflow_docs: "CLAUDE/PlanWorkflow.md"

    # Child handler inherits options from markdown_organization
    plan_number_helper:
      enabled: true
      priority: 30
      # No need to repeat track_plans_in_project here
```

---

## Tag-Based Handler Selection

Instead of enabling handlers one by one, you can use tags to enable or disable groups of handlers.

### Using enable_tags

Only run handlers that have at least one of the specified tags:

```yaml
handlers:
  pre_tool_use:
    enable_tags: [python, safety, tdd]
    # Only handlers tagged with python, safety, or tdd will run
```

### Using disable_tags

Exclude handlers with specific tags:

```yaml
handlers:
  pre_tool_use:
    disable_tags: [ec-specific, project-specific]
    # Handlers with these tags will not run
```

### Combining Tags with Individual Settings

Individual `enabled: false` settings override tag filtering:

```yaml
handlers:
  pre_tool_use:
    enable_tags: [python]

    # This handler matches the python tag but is explicitly disabled
    python_qa_suppression_blocker:
      enabled: false
```

### Available Tags

**Language tags:** `python`, `php`, `typescript`, `javascript`, `go`

**Function tags:** `safety`, `tdd`, `qa-enforcement`, `qa-suppression-prevention`, `workflow`, `advisory`, `validation`, `logging`, `cleanup`

**Tool tags:** `git`, `npm`, `bash`

**Specificity tags:** `ec-specific`, `project-specific`

---

## Plugin System

The plugin system lets you add custom handlers specific to your project.

### Plugin Configuration

```yaml
plugins:
  paths: []      # Additional Python module search paths (optional)
  plugins:
    # Load a specific handler from a file
    - path: ".claude/hooks/handlers/pre_tool_use/my_handler.py"
      handlers: ["MyHandler"]   # Specific class names to load
      enabled: true

    # Load all handlers from a directory
    - path: ".claude/hooks/handlers/post_tool_use/"
      handlers: null            # null = load all Handler subclasses found
      enabled: true
```

### Writing a Custom Handler

Create a Python file in `.claude/hooks/handlers/<event_type>/`:

```python
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision

class MyHandler(Handler):
    def __init__(self) -> None:
        super().__init__(
            name="my-handler",
            priority=50,
            terminal=True   # True = stop chain on match, False = continue
        )

    def matches(self, hook_input: dict) -> bool:
        # REQUIRED: Filter by event type
        if hook_input.get("hook_event_name") != "PreToolUse":
            return False
        # Your matching logic
        command = hook_input.get("tool_input", {}).get("command", "")
        return "dangerous_pattern" in command

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(
            decision=Decision.DENY,
            reason="This operation is not allowed."
        )
```

**Important:** The directory path (e.g., `pre_tool_use/`) is a convention only. Your handler's `matches()` method must check `hook_event_name` to filter by event type.

### Plugin Search Paths

Use `paths` to add directories to the Python module search path, allowing your handlers to import shared utilities:

```yaml
plugins:
  paths:
    - ".claude/hooks/lib"   # Add this to sys.path
  plugins:
    - path: ".claude/hooks/handlers/"
      handlers: null
      enabled: true
```

---

## Environment Variables

These environment variables affect daemon behavior. They are typically set in `.claude/hooks-daemon.env`, which is sourced before the daemon starts.

| Variable | Description |
|----------|-------------|
| `HOOKS_DAEMON_ROOT_DIR` | Root directory of the daemon installation. Default: `$PROJECT_PATH/.claude/hooks-daemon`. Set to `$PROJECT_PATH` for self-install mode. |
| `CLAUDE_HOOKS_SOCKET_PATH` | Override the Unix socket path. Takes precedence over hostname-based paths. |
| `CLAUDE_HOOKS_PID_PATH` | Override the PID file path. |
| `CLAUDE_HOOKS_LOG_PATH` | Override the log file path. |
| `HOSTNAME` | Used for multi-environment isolation. Each unique hostname gets its own socket, PID, and log files (e.g., `daemon-laptop.sock`). |
| `DAEMON_BRANCH` | Git branch or tag to install (used by the installer only). Default: `main`. |
| `FORCE` | Set to `true` to force reinstall over an existing installation. |

### Hostname-Based Isolation

When running in multiple environments (containers, CI, different machines), each unique `HOSTNAME` gets isolated runtime files:

```
# With HOSTNAME=laptop
.claude/hooks-daemon/untracked/daemon-laptop.sock
.claude/hooks-daemon/untracked/daemon-laptop.pid
.claude/hooks-daemon/untracked/daemon-laptop.log

# With HOSTNAME=ci-runner-01
.claude/hooks-daemon/untracked/daemon-ci-runner-01.sock
```

This prevents conflicts when multiple daemon instances run for the same project across different machines.

---

## Minimal vs Full Config

### Minimal Config

Use a minimal config when you want a clean starting point and plan to enable handlers selectively:

```yaml
version: "1.0"

daemon:
  idle_timeout_seconds: 600
  log_level: INFO

handlers:
  pre_tool_use: {}
  post_tool_use: {}
  session_start: {}

plugins:
  paths: []
  plugins: []
```

Generate one with:

```bash
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli init-config --mode minimal
```

### Full Config

Use a full config to see every available handler with descriptions and recommended settings. This is the default output of the installer and lists all event types and handlers:

```bash
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli init-config --mode full
```

### Recommended Starting Config

For most projects, the example config (`.claude/hooks-daemon.yaml.example` in the daemon repository) provides a good starting point. It enables all safety handlers and disables optional workflow/quality handlers with clear comments explaining each one.

---

## Config Validation

### Validating Your Config

The daemon validates its config on startup. If there are issues, you will see error messages in the logs:

```bash
# Check logs for config errors
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli logs | grep -i "config\|error\|warning"
```

### Common Config Errors

**Unknown handler name:**

```yaml
handlers:
  pre_tool_use:
    destrutive_git: {enabled: true}  # Typo -- should be "destructive_git"
```

The daemon will log a warning about an unrecognized handler. Check spelling against the example config.

**Wrong event type:**

```yaml
handlers:
  pre_tool_use:
    bash_error_detector: {enabled: true}  # Wrong -- this is a post_tool_use handler
```

Handlers only work under their correct event type. See the example config for the right placement.

**Invalid YAML syntax:**

```yaml
handlers:
  pre_tool_use:
    destructive_git: {enabled true}  # Missing colon after "enabled"
```

The daemon will fail to start with a YAML parse error. Use a YAML linter to check syntax.

**Missing version field:**

```yaml
# version: "2.0"  -- missing!
daemon:
  log_level: INFO
```

Always include the `version` field at the top of your config.

### Strict Mode

With `daemon.strict_mode: true`, the daemon fails fast on any error. This is useful during development to catch config issues immediately. In production, leave it `false` so the daemon continues running even if a single handler has a problem.

---

## Applying Config Changes

**Handler changes** (enabling, disabling, priority adjustments) require a daemon restart:

```bash
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart
```

**Claude Code settings** (`.claude/settings.json`) require a full Claude Code session restart. This file is managed by the installer and rarely needs manual changes.

---

## Example Configurations

### Python Project

```yaml
version: "2.0"

daemon:
  idle_timeout_seconds: 600
  log_level: INFO

handlers:
  pre_tool_use:
    # Safety
    destructive_git: {enabled: true, priority: 10}
    sed_blocker: {enabled: true, priority: 10}
    absolute_path: {enabled: true, priority: 12}
    curl_pipe_shell: {enabled: true, priority: 15}
    pip_break_system: {enabled: true, priority: 20}
    sudo_pip: {enabled: true, priority: 20}

    # Python quality
    python_qa_suppression_blocker: {enabled: true, priority: 26}
    tdd_enforcement: {enabled: true, priority: 35}

    # Workflow
    web_search_year: {enabled: true, priority: 55}

  post_tool_use:
    bash_error_detector: {enabled: true, priority: 10}

  session_start:
    yolo_container_detection: {enabled: true, priority: 10}

plugins:
  paths: []
  plugins: []
```

### JavaScript/TypeScript Project

```yaml
version: "2.0"

daemon:
  idle_timeout_seconds: 600
  log_level: INFO

handlers:
  pre_tool_use:
    # Safety
    destructive_git: {enabled: true, priority: 10}
    sed_blocker: {enabled: true, priority: 10}
    absolute_path: {enabled: true, priority: 12}
    lock_file_edit_blocker: {enabled: true, priority: 20}

    # JS/TS quality
    eslint_disable: {enabled: true, priority: 30}

    # Workflow
    global_npm_advisor: {enabled: true, priority: 42}
    npm_command: {enabled: true, priority: 50}
    web_search_year: {enabled: true, priority: 55}

  post_tool_use:
    bash_error_detector: {enabled: true, priority: 10}
    validate_eslint_on_write: {enabled: true, priority: 20}

  session_start:
    yolo_container_detection: {enabled: true, priority: 10}

plugins:
  paths: []
  plugins: []
```

### Safety-Only (Minimal Intervention)

```yaml
version: "2.0"

daemon:
  idle_timeout_seconds: 600
  log_level: INFO

handlers:
  pre_tool_use:
    destructive_git: {enabled: true, priority: 10}
    sed_blocker: {enabled: true, priority: 10}
    absolute_path: {enabled: true, priority: 12}
    curl_pipe_shell: {enabled: true, priority: 15}
    dangerous_permissions: {enabled: true, priority: 18}
    lock_file_edit_blocker: {enabled: true, priority: 20}
    pip_break_system: {enabled: true, priority: 20}
    sudo_pip: {enabled: true, priority: 20}

  post_tool_use: {}
  session_start: {}

plugins:
  paths: []
  plugins: []
```
