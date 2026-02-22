# Troubleshooting Guide

Practical solutions for common issues with the Claude Code Hooks Daemon. Work through these sections to diagnose and fix problems.

---

## 1. Quick Health Check

Run these commands to get a snapshot of your daemon's health:

```bash
# Check if the daemon is running
python -m claude_code_hooks_daemon.daemon.cli status

# View recent logs
python -m claude_code_hooks_daemon.daemon.cli logs

# Check loaded handlers
python -m claude_code_hooks_daemon.daemon.cli handlers

# Validate your configuration
python -m claude_code_hooks_daemon.daemon.cli config-validate
```

**Expected healthy output from `status`:**
```
Daemon: RUNNING
PID: 12345
Socket: /path/to/project/.claude/hooks-daemon/untracked/daemon-hostname.sock (exists)
```

If status shows the daemon is not running, see [Daemon Won't Start](#2-daemon-wont-start).

If status shows running but hooks are not working, see [Hooks Not Firing](#3-hooks-not-firing).

---

## 2. Daemon Won't Start

### Symptom: "Daemon failed to start" or status shows NOT RUNNING

**Step 1: Check for an existing daemon process**

```bash
python -m claude_code_hooks_daemon.daemon.cli status
```

If a stale PID file exists from a crashed daemon, stop it first:

```bash
python -m claude_code_hooks_daemon.daemon.cli stop
python -m claude_code_hooks_daemon.daemon.cli start
```

**Step 2: Check for configuration errors**

```bash
python -m claude_code_hooks_daemon.daemon.cli config-validate
```

If validation fails, fix the errors in `.claude/hooks-daemon.yaml`. Common YAML issues:
- Incorrect indentation (YAML uses spaces, not tabs)
- Missing colons after keys
- Boolean values must be `true`/`false` (not `yes`/`no`)

**Step 3: Check Python version**

The daemon requires Python 3.11 or later:

```bash
python --version
# Or if using a venv:
.claude/hooks-daemon/untracked/venv/bin/python --version
```

If your Python version is too old, install a newer version and reinstall the daemon.

**Step 4: Check for a stale socket file**

If the daemon crashed, the socket file may still exist:

```bash
ls -la .claude/hooks-daemon/untracked/daemon-*.sock
```

Remove the stale socket and restart:

```bash
rm .claude/hooks-daemon/untracked/daemon-*.sock
python -m claude_code_hooks_daemon.daemon.cli start
```

**Step 5: Check logs for startup errors**

```bash
python -m claude_code_hooks_daemon.daemon.cli logs
```

Look for import errors, missing dependencies, or configuration issues in the log output.

**Step 6: Repair the virtual environment**

If the venv is corrupted (e.g., after a Python upgrade):

```bash
python -m claude_code_hooks_daemon.daemon.cli repair
```

This runs `uv sync` to rebuild the virtual environment.

---

## 3. Hooks Not Firing

### Symptom: Claude Code runs normally but handlers never trigger

**Step 1: Verify the daemon is running**

```bash
python -m claude_code_hooks_daemon.daemon.cli status
```

If not running, start it:

```bash
python -m claude_code_hooks_daemon.daemon.cli start
```

**Step 2: Verify hook scripts are installed**

Check that Claude Code's `.claude/settings.json` contains hook script entries pointing to the daemon:

```bash
cat .claude/settings.json | python -m json.tool
```

Look for a `hooks` section with entries for the event types you expect. Each hook should point to a script that communicates with the daemon socket.

If hook scripts are missing, reinstall the daemon. The installer sets up both the daemon and the hook scripts in `.claude/settings.json`.

**Step 3: Verify the socket path matches**

The hook scripts must connect to the same socket the daemon is listening on:

```bash
# Check what socket the daemon is using
python -m claude_code_hooks_daemon.daemon.cli status
# Look for the "Socket:" line

# Check what socket the hook scripts expect
cat .claude/hooks-daemon/hooks/*.sh | head -20
# Look for SOCKET_PATH or similar variable
```

If the paths do not match, restart the daemon or reinstall the hook scripts.

**Step 4: Check the daemon log for incoming requests**

```bash
python -m claude_code_hooks_daemon.daemon.cli logs
```

If the daemon is receiving requests, you will see log lines like:
```
Routing PreToolUse event to chain with 17 handlers
```

If there are no request logs, the hook scripts are not reaching the daemon.

**Step 5: Test the socket manually**

Check that the socket file exists and is accessible:

```bash
ls -la .claude/hooks-daemon/untracked/daemon-*.sock
```

If the socket file does not exist, the daemon is not running or started with a different socket path.

---

## 4. Handler Not Triggering

### Symptom: Daemon is running, hooks fire, but a specific handler does not activate

**Step 1: Verify the handler is enabled**

```bash
python -m claude_code_hooks_daemon.daemon.cli config
```

Check that the handler appears in the output and is `enabled: true`. If it is missing or disabled, add or enable it in `.claude/hooks-daemon.yaml`:

```yaml
handlers:
  pre_tool_use:
    handler_name:
      enabled: true
      priority: 10
```

**Step 2: Verify the handler is loaded**

```bash
python -m claude_code_hooks_daemon.daemon.cli handlers
```

This lists all registered handlers. If your handler does not appear, the daemon may need a restart to pick up config changes:

```bash
python -m claude_code_hooks_daemon.daemon.cli restart
```

**Step 3: Check handler priority ordering**

Handlers run in priority order. A higher-priority (lower number) blocking handler may be intercepting the event before your handler runs. Check the handler list output for handlers that run before yours on the same event type.

**Step 4: Check the matches() logic**

The handler's `matches()` method determines whether it activates. Common reasons a handler does not match:

- **Wrong tool name:** The handler checks for `Bash` but the event is `Write`
- **Pattern mismatch:** The regex does not match the actual command
- **File extension filter:** The handler only checks `.py` files but the file is `.ts`
- **Directory filter:** The handler skips certain directories

Enable DEBUG logging to see exactly which handlers match:

```bash
# In .claude/hooks-daemon.yaml, set:
# daemon:
#   log_level: DEBUG

python -m claude_code_hooks_daemon.daemon.cli restart
# Trigger the event, then check logs:
python -m claude_code_hooks_daemon.daemon.cli logs
```

Look for log lines showing which handlers matched or did not match.

**Step 5: Restart the daemon after config changes**

The daemon loads configuration at startup. Any changes to `.claude/hooks-daemon.yaml` require a restart:

```bash
python -m claude_code_hooks_daemon.daemon.cli restart
```

---

## 5. Handler Blocking Too Much (False Positives)

### Symptom: A handler blocks legitimate operations

**Option 1: Disable the handler**

If you do not need the handler at all:

```yaml
handlers:
  pre_tool_use:
    handler_name:
      enabled: false
```

Then restart the daemon:

```bash
python -m claude_code_hooks_daemon.daemon.cli restart
```

**Option 2: Check handler options**

Some handlers have configurable options that affect their behaviour (e.g. switching from blocking to advisory mode). For the full list of per-handler options, values, and config examples, see **[Handler Reference](HANDLER_REFERENCE.md)**.

**Option 3: Adjust handler priority**

If a handler needs to run after another handler that provides context, adjust its priority:

```yaml
handlers:
  pre_tool_use:
    handler_name:
      enabled: true
      priority: 55  # Higher number = runs later
```

**Option 4: Check if the command can be rephrased**

Blocking handlers usually suggest safe alternatives in their error messages. Read the block message carefully for recommended alternatives.

---

## 6. Performance Issues

### Symptom: Claude Code feels slow or handlers take too long

**Step 1: Check daemon response times**

```bash
python -m claude_code_hooks_daemon.daemon.cli logs
```

Look for request processing times. Normal handler dispatch should complete in under 10ms.

**Step 2: Reduce log verbosity**

DEBUG logging adds overhead. Set log level to INFO or WARNING for production use:

```yaml
daemon:
  log_level: INFO  # Options: DEBUG, INFO, WARNING, ERROR
```

```bash
python -m claude_code_hooks_daemon.daemon.cli restart
```

**Step 3: Disable unused handlers**

Each enabled handler adds a small amount of processing time. Disable handlers you do not use:

```yaml
handlers:
  pre_tool_use:
    british_english:
      enabled: false  # Disable if you don't need British English checks
    validate_sitemap:
      enabled: false  # Disable if you don't have sitemaps
```

**Step 4: Check idle timeout**

The daemon auto-shuts down after a period of inactivity (default: 600 seconds / 10 minutes). It restarts automatically when the next hook fires. If this restart delay bothers you, increase the timeout:

```yaml
daemon:
  idle_timeout_seconds: 3600  # 1 hour
```

**Step 5: Check daemon memory usage**

```bash
python -m claude_code_hooks_daemon.daemon.cli health
```

If memory usage is high, the daemon may have accumulated too many in-memory logs. A restart clears the log buffer:

```bash
python -m claude_code_hooks_daemon.daemon.cli restart
```

---

## 7. Log Files

### Where logs are stored

The daemon uses **in-memory logging** by default. Logs are not written to disk files but stored in a circular memory buffer (last 1000 entries).

### Viewing logs

```bash
# View all in-memory logs
python -m claude_code_hooks_daemon.daemon.cli logs

# The daemon log file (if configured) is at:
# .claude/hooks-daemon/untracked/daemon-{hostname}.log
```

### Log levels

| Level | What it shows |
|-------|--------------|
| `DEBUG` | Everything: handler matching, dispatch chains, request details |
| `INFO` | Normal operations: startup, shutdown, handler blocks, warnings |
| `WARNING` | Issues that need attention but are not critical |
| `ERROR` | Failures that affect functionality |

### Changing log level

Edit `.claude/hooks-daemon.yaml`:

```yaml
daemon:
  log_level: DEBUG  # Temporarily increase for debugging
```

Then restart:

```bash
python -m claude_code_hooks_daemon.daemon.cli restart
```

Remember to set it back to `INFO` after debugging to avoid performance overhead.

### Log format

```
2026-01-27 04:37:27,189 [INFO] module.name: Log message here
```

Fields: timestamp, log level, module path, message.

---

## 8. Debug Mode

### Using DEBUG log level

For detailed insight into what the daemon is doing:

1. Set log level to DEBUG in your config:

```yaml
daemon:
  log_level: DEBUG
```

2. Restart the daemon:

```bash
python -m claude_code_hooks_daemon.daemon.cli restart
```

3. Trigger the action you want to debug (run a command in Claude Code).

4. Check the logs:

```bash
python -m claude_code_hooks_daemon.daemon.cli logs
```

5. Look for lines showing:
   - Which event type was routed
   - How many handlers were in the chain
   - Which handlers matched
   - What decision was made (allow/deny)
   - Processing time

6. Set log level back to INFO when done.

### Using the debug_hooks.sh script

For targeted debugging of specific scenarios:

```bash
# Start a debug session with a descriptive label
./scripts/debug_hooks.sh start "Testing git commit blocking"

# Perform the action in Claude Code that you want to debug

# Stop the session and view filtered logs
./scripts/debug_hooks.sh stop
```

This script:
- Temporarily enables DEBUG logging
- Injects boundary markers into the logs
- Filters to show only logs from your test session
- Saves the output to `/tmp/hook_debug_TIMESTAMP.log`
- Restores INFO logging when done

---

## 9. Configuration Issues

### YAML syntax errors

**Symptom:** Daemon fails to start with a configuration error.

Validate your configuration:

```bash
python -m claude_code_hooks_daemon.daemon.cli config-validate
```

Common YAML mistakes:

```yaml
# WRONG: tabs instead of spaces
handlers:
	pre_tool_use:    # Tab character - YAML requires spaces

# WRONG: missing space after colon
handlers:
  pre_tool_use:
    sed_blocker:
      enabled:true    # Needs space: enabled: true

# WRONG: incorrect boolean
handlers:
  pre_tool_use:
    sed_blocker:
      enabled: yes    # Must be true/false, not yes/no

# CORRECT:
handlers:
  pre_tool_use:
    sed_blocker:
      enabled: true
      priority: 10
```

### Missing handler in config

If a handler is not in your config file, it will not load. Use `init-config` to generate a template with all available handlers:

```bash
python -m claude_code_hooks_daemon.daemon.cli init-config
```

This generates a configuration file with all handlers listed. You can then copy the handler entries you need into your existing config.

### Comparing your config to the default

To see what differs between your config and the default:

```bash
python -m claude_code_hooks_daemon.daemon.cli config-diff
```

To merge new defaults into your existing config while preserving your customisations:

```bash
python -m claude_code_hooks_daemon.daemon.cli config-merge
```

### Version string

Your config file should have a version number at the top:

```yaml
version: "2.0"
```

If the version is missing or outdated, the daemon may report a configuration warning.

---

## 10. Common Error Messages

### "ERROR: Could not find .claude directory"

**Cause:** You are running the CLI from a directory that is not a project root (or subdirectory of one) with a `.claude` folder.

**Fix:** Navigate to your project root directory, or specify the project path:

```bash
cd /path/to/your/project
python -m claude_code_hooks_daemon.daemon.cli status
```

---

### "ERROR: hooks-daemon not installed at: /path/to/project"

**Cause:** The `.claude/hooks-daemon/` directory does not exist. The daemon has not been installed for this project.

**Fix:** Install the daemon following the Getting Started guide, or if this is the daemon's own repository, enable self-install mode:

```yaml
daemon:
  self_install_mode: true
```

---

### "Daemon already running (PID: XXXXX)"

**Cause:** A daemon instance is already running. This is not an error.

**Fix:** If you want to restart it:

```bash
python -m claude_code_hooks_daemon.daemon.cli restart
```

---

### "ERROR: Failed to communicate with daemon"

**Cause:** The daemon process exists but is not responding to socket connections. The socket file may be stale or the daemon may have hung.

**Fix:**

```bash
# Force stop and restart
python -m claude_code_hooks_daemon.daemon.cli stop
python -m claude_code_hooks_daemon.daemon.cli start
```

If that does not work, remove the socket and PID files manually:

```bash
rm .claude/hooks-daemon/untracked/daemon-*.sock
rm .claude/hooks-daemon/untracked/daemon-*.pid
python -m claude_code_hooks_daemon.daemon.cli start
```

---

### "ERROR: Invalid configuration in .claude/hooks-daemon.yaml"

**Cause:** The YAML configuration file has syntax errors or invalid values.

**Fix:** Run validation to see the specific errors:

```bash
python -m claude_code_hooks_daemon.daemon.cli config-validate
```

Fix the reported issues and try again. See [Configuration Issues](#9-configuration-issues) for common mistakes.

---

### "No module named 'claude_code_hooks_daemon'"

**Cause:** Python cannot find the daemon package. The virtual environment may be broken or not activated.

**Fix:**

```bash
# Repair the venv
python -m claude_code_hooks_daemon.daemon.cli repair

# Or if the CLI itself fails, use the venv Python directly:
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli repair
```

---

### "Socket path too long"

**Cause:** Unix sockets have a path length limit (typically 108 characters). Your project path may be too deep.

**Fix:** Override the socket path with an environment variable:

```bash
export CLAUDE_HOOKS_SOCKET_PATH="/tmp/hooks-daemon.sock"
python -m claude_code_hooks_daemon.daemon.cli restart
```

Note: Using `/tmp` for the socket is less secure but resolves path length issues. The daemon automatically sanitises the hostname-based suffix to keep paths short.

---

### Handler-specific "BLOCKED" messages

When a handler blocks an operation, it provides an explanation and alternatives directly in the block message. Read the message carefully -- it tells you:

1. **What was blocked** and why
2. **Safe alternatives** to achieve the same goal
3. **How to proceed** if the operation is truly necessary

If you believe the block is incorrect, see [Handler Blocking Too Much](#5-handler-blocking-too-much-false-positives).

---

## 11. Getting Help

### Check your daemon version

```bash
python -m claude_code_hooks_daemon.daemon.cli status
```

The version number is displayed in the status output.

### Gather debug information

Before reporting an issue, collect this information:

```bash
# Daemon status
python -m claude_code_hooks_daemon.daemon.cli status

# Configuration
python -m claude_code_hooks_daemon.daemon.cli config

# Handler list
python -m claude_code_hooks_daemon.daemon.cli handlers

# Recent logs
python -m claude_code_hooks_daemon.daemon.cli logs

# Python version
python --version

# OS information
uname -a
```

### Reporting issues

File issues on the GitHub repository with:

1. **Description** of the problem
2. **Steps to reproduce** the issue
3. **Expected behaviour** vs actual behaviour
4. **Debug information** from the commands above
5. **Configuration** (your `.claude/hooks-daemon.yaml`, with any sensitive values removed)

### CLI command reference

| Command | Description |
|---------|-------------|
| `status` | Check if daemon is running, show PID and socket path |
| `start` | Start daemon in background |
| `stop` | Stop the running daemon |
| `restart` | Stop and start the daemon |
| `logs` | View in-memory log buffer |
| `health` | Check daemon health (memory, uptime) |
| `handlers` | List all registered handlers |
| `config` | Show loaded configuration |
| `config-validate` | Validate config against schema |
| `config-diff` | Compare your config to default |
| `config-merge` | Merge new defaults into your config |
| `init-config` | Generate a configuration template |
| `repair` | Repair broken virtual environment |
| `generate-playbook` | Generate acceptance test playbook |
