# Bug Reporting Guide

Report issues at: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues

## Quick Bug Report Generation

The daemon includes a debug info generator that automatically collects all diagnostic information needed for bug reports.

### In the Daemon Project (This Repository)

```bash
# Run from project root
./scripts/debug_info.py

# Or save to file for GitHub
./scripts/debug_info.py /tmp/bug_report.md
```

### In a Client Project (Where Daemon is Installed)

```bash
# Run from your project root
.claude/hooks-daemon/scripts/debug_info.py

# Or save to file
.claude/hooks-daemon/scripts/debug_info.py /tmp/bug_report.md
```

The script auto-detects:
- Project paths (socket, PID, config files)
- Daemon status and process state
- Installed handlers and configuration
- Hook test results
- Recent daemon logs

## What the Debug Info Includes

The generated report contains:

### 1. System Information
- OS, kernel, architecture
- Python version and location
- Hostname and environment

### 2. Project Paths
- Project root directory
- Daemon installation location
- Socket and PID file paths

### 3. Daemon Status
- Running/stopped state
- Process ID and uptime
- Socket availability

### 4. File System State
- Socket file existence and permissions
- PID file contents
- Process verification (stale detection)

### 5. Configuration Files
- Full `.claude/hooks-daemon.yaml` contents
- Environment overrides (`.claude/hooks-daemon.env`)

### 6. Hook Tests
- Simple command test (echo hello)
- Destructive git command test (git reset --hard)
- Shows whether handlers are blocking correctly

### 7. Daemon Logs
- Last 50 log entries from memory buffer
- Shows recent daemon activity

### 8. Installed Handlers
- Total handlers registered
- Handlers listed by event type
- Priority, terminal/non-terminal, tags
- Useful for confirming handler configuration

### 9. Health Summary
- ✅/❌ Daemon Running
- ✅/❌ Hooks Working
- ✅/❌ Handlers Loaded

## Manual Bug Report Template

If you can't run the debug script, provide:

### Required Information

**Environment:**
- OS and version
- Python version
- Claude Code version
- Daemon version (from `.claude/hooks-daemon/` git commit)

**Issue Description:**
- What you expected to happen
- What actually happened
- Steps to reproduce

**Configuration:**
- Relevant sections from `.claude/hooks-daemon.yaml`
- Any custom handlers in `.claude/hooks/handlers/`

**Logs:**
```bash
# Get daemon logs
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli logs

# Check daemon status
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status
```

**Hook Test:**
```bash
# Test a hook manually
echo '{"tool_name":"Bash","tool_input":{"command":"echo test"}}' | .claude/hooks/pre-tool-use
```

## Common Issues

### "Daemon status says NOT RUNNING but hooks work"

This is **normal behavior** with lazy startup:
- Daemon starts on first hook call
- Auto-shuts down after 10 minutes idle
- When you check status later, it may have already shut down

To see it running, check status immediately after a hook call:
```bash
echo '{"tool_name":"Bash","tool_input":{"command":"echo test"}}' | .claude/hooks/pre-tool-use && \
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status
```

### "Hooks not working after installation"

1. **Restart Claude session** - Hooks only activate after Claude reloads config
2. **Check `.claude/settings.json`** - Should contain hook registrations
3. **Run debug script** - `./scripts/debug_info.py` to see what's wrong

### "Handler not blocking commands as expected"

1. **Check handler is enabled** in `.claude/hooks-daemon.yaml`
2. **Use debug_hooks.sh** to see event flow:
   ```bash
   .claude/hooks-daemon/scripts/debug_hooks.sh start "Testing handler"
   # ... perform action ...
   .claude/hooks-daemon/scripts/debug_hooks.sh stop
   ```
3. **Check handler priority** - Lower priority runs first
4. **Check terminal flag** - Terminal handlers stop the chain

### "AttributeError: 'NoneType' object has no attribute 'get'"

This was a bug in v2.0.0 that's fixed in v2.1.0. Update your daemon:
```bash
cd .claude/hooks-daemon
git pull origin main
untracked/venv/bin/pip install -e .
```

## Getting Help

1. **Run debug script first**: `./scripts/debug_info.py /tmp/report.md`
2. **Create GitHub issue**: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues
3. **Paste debug report** into issue description
4. **Add context**: What you were doing when the issue occurred

## Contributing Bug Fixes

If you've identified and fixed a bug:

1. **Write tests first** (TDD):
   ```bash
   # Create test that reproduces the bug
   tests/test_my_bug.py

   # Verify test fails
   ./untracked/venv/bin/python -m pytest tests/test_my_bug.py
   ```

2. **Fix the bug**

3. **Verify tests pass**:
   ```bash
   ./scripts/qa/run_all.sh
   ```

4. **Submit PR** with:
   - Test that reproduces the bug
   - Fix implementation
   - Updated documentation if needed

See [CONTRIBUTING.md](CONTRIBUTING.md) for full contribution guidelines.
