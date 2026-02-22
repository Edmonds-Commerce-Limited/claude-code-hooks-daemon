# Getting Started with Claude Code Hooks Daemon

This guide walks you through installing and configuring the Claude Code Hooks Daemon in your project.

---

## What is the Hooks Daemon?

The Claude Code Hooks Daemon is a background process that intercepts Claude Code hook events and runs handler logic against them. It provides:

- **Safety protection** -- blocks destructive commands like `git reset --hard` and `sed -i` before they execute
- **Code quality enforcement** -- prevents QA suppression comments (`# noqa`, `// eslint-disable`, etc.)
- **Workflow automation** -- injects git context, enforces TDD, validates plans
- **20x faster response times** -- a long-running daemon with Unix socket IPC replaces per-hook process spawning

When Claude Code fires a hook event (for example, before running a Bash command), the daemon evaluates it against a chain of handlers and returns a decision: allow, deny, or add context.

---

## Prerequisites

Before installing, make sure you have:

- **Python 3.11 or higher**
  ```bash
  python3 --version
  # Must show 3.11, 3.12, or 3.13
  ```

- **Claude Code CLI** installed and working

- **Git** installed (the installer clones the daemon repository)

- **Clean git state** in your project (no uncommitted changes)
  ```bash
  git status --short
  # Should show nothing
  ```

---

## Installation

### Quick Install (Recommended)

From your **project root** (the directory containing `.claude/` and `.git/`):

```bash
# Download the installer
curl -sSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/install.sh -o /tmp/hooks-daemon-install.sh

# Inspect it (good security practice)
cat /tmp/hooks-daemon-install.sh

# Run it
bash /tmp/hooks-daemon-install.sh
```

This installer will:

1. Validate prerequisites (git, Python 3.11+)
2. Clone the daemon to `.claude/hooks-daemon/`
3. Create an isolated virtual environment
4. Deploy hook forwarder scripts to `.claude/hooks/`
5. Generate `settings.json` for Claude Code hook registration
6. Create a default `hooks-daemon.yaml` configuration
7. Start the daemon and verify it is running

### Install a Specific Version

```bash
curl -sSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/install.sh -o /tmp/hooks-daemon-install.sh
DAEMON_BRANCH=v2.7.0 bash /tmp/hooks-daemon-install.sh
```

### Create .gitignore (Required After Install)

The installer will display the required `.claude/.gitignore` content. You **must** create this file before committing:

```bash
cp .claude/hooks-daemon/.claude/.gitignore .claude/.gitignore
```

Then commit the installation:

```bash
git add .claude/
git commit -m "Install Claude Code Hooks Daemon"
git push
```

### Restart Claude Code

After installation, **restart your Claude Code session**. Hooks will not activate until Claude reloads `.claude/settings.json`.

---

## First Run

After restarting your Claude Code session, the daemon starts automatically on the first hook call (lazy startup). You can also manage it manually.

### Check Daemon Status

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status
```

You should see output indicating the daemon is **RUNNING** with a PID and socket path.

### Test That Hooks Work

Test a destructive git command (should be blocked):

```bash
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}' \
  | .claude/hooks/pre-tool-use
```

Expected: A JSON response with `"permissionDecision": "deny"` and a reason explaining why the command was blocked.

Test a safe command (should be allowed):

```bash
echo '{"tool_name": "Bash", "tool_input": {"command": "ls -la"}}' \
  | .claude/hooks/pre-tool-use
```

Expected: `{}` (empty JSON, meaning "allow").

### Enable Hello World Handlers (Optional)

To confirm hooks are connected end-to-end, you can temporarily enable the test handlers. Edit `.claude/hooks-daemon.yaml`:

```yaml
daemon:
  enable_hello_world_handlers: true
```

Then restart the daemon:

```bash
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart
```

The hello world handlers add a small context message to every hook event. Disable them once you have confirmed things work.

---

## Understanding the Config

The daemon is configured through `.claude/hooks-daemon.yaml`. Here is the basic structure:

```yaml
version: "2.0"

# Daemon process settings
daemon:
  idle_timeout_seconds: 600  # Auto-shutdown after 10 minutes idle
  log_level: INFO            # DEBUG, INFO, WARNING, ERROR

# Handler configuration, grouped by event type
handlers:
  pre_tool_use:    # Runs before tool execution
    destructive_git: {enabled: true, priority: 10}
    sed_blocker: {enabled: true, priority: 10}
    # ... more handlers ...

  post_tool_use:   # Runs after tool execution
    bash_error_detector: {enabled: true, priority: 10}

  session_start:   # Runs when a session begins
    yolo_container_detection: {enabled: true, priority: 10}

  # ... more event types ...

# Custom project-specific handlers
plugins:
  paths: []
  plugins: []
```

Each handler has:
- **enabled** -- `true` or `false` to toggle it
- **priority** -- lower numbers run first; determines execution order

For full configuration details, see the [Configuration Guide](CONFIGURATION.md).

---

## Enabling Your First Handlers

The default config enables several safety handlers out of the box. Here are the most important ones and what they do:

### 1. Destructive Git Blocker (enabled by default)

```yaml
destructive_git: {enabled: true, priority: 10}
```

Blocks commands that permanently destroy data: `git reset --hard`, `git clean -f`, `git push --force`, `git checkout -- file`, `git restore`, and `git stash drop/clear`. When triggered, it tells Claude to ask the user to run the command manually.

### 2. Sed Blocker (enabled by default)

```yaml
sed_blocker: {enabled: true, priority: 10}
```

Blocks all `sed` command usage. Claude frequently gets sed syntax wrong, which can corrupt files at scale. The handler directs Claude to use the Edit tool instead, which is safe, atomic, and trackable.

### 3. Absolute Path Enforcer (enabled by default)

```yaml
absolute_path: {enabled: true, priority: 12}
```

Ensures file operations use absolute paths, preventing mistakes from relative path resolution in different working directories.

### 4. Curl Pipe Shell Blocker (enabled by default)

```yaml
curl_pipe_shell: {enabled: true, priority: 15}
```

Blocks dangerous patterns like `curl ... | bash` that download and execute arbitrary code.

### Enabling Additional Handlers

To enable a handler that is off by default, change `enabled: false` to `enabled: true` in your config. For example, to enable TDD enforcement:

```yaml
handlers:
  pre_tool_use:
    tdd_enforcement: {enabled: true, priority: 35}
```

Then restart the daemon:

```bash
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart
```

### Handler Options

Many handlers have configurable options (e.g. `blocking_mode`, `mode`, `priority`). For the full per-handler options reference, see **[Handler Reference → Options](HANDLER_REFERENCE.md)**.

---

## Verifying It Works

### Trigger a Safety Handler

In your Claude Code session, ask Claude to run a destructive git command:

> "Run `git reset --hard HEAD`"

You should see Claude's attempt blocked with a message explaining why the command is dangerous and suggesting safe alternatives.

### Check Handler Status

Generate a report of all handlers and their current state:

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python scripts/handler_status.py
```

This shows every handler, whether it is enabled or disabled, its priority, and its tags.

### View Daemon Logs

```bash
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli logs
```

Logs show which handlers matched, what decisions were made, and any errors.

---

## Common Daemon Commands

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# Check if daemon is running
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Start the daemon (usually not needed -- lazy startup handles this)
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli start

# Stop the daemon
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli stop

# Restart after config or code changes
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart

# View recent logs
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli logs
```

---

## Next Steps

- **[Configuration Guide](CONFIGURATION.md)** -- Full reference for all config options, handler settings, priority system, plugins, and environment variables
- **[Handler Reference](HANDLER_REFERENCE.md)** -- Detailed documentation for every built-in handler
- **[Troubleshooting](TROUBLESHOOTING.md)** -- Common issues and how to fix them
- **README.md** (project root) -- Architecture overview, changelog, and development guide
