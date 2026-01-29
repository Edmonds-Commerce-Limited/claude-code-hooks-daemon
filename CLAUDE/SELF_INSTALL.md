# Self-Install Mode - Complete Guide

## What Is Self-Install Mode?

When `self_install_mode: true` in `.claude/hooks-daemon.yaml`, the daemon runs from the **workspace root** instead of `.claude/hooks-daemon/`. This allows the hooks-daemon project to dogfood itself during development.

## Path Differences

### Normal Installation

```
.claude/hooks-daemon/
├── untracked/venv/              # Virtual environment
├── untracked/socket             # Unix socket
├── untracked/daemon.pid         # PID file
└── (daemon runs from pip package)
```

### Self-Install Mode (This Project)

```
/workspace/
├── untracked/venv/              # Virtual environment
├── untracked/socket             # Unix socket
├── untracked/daemon.pid         # PID file
├── src/claude_code_hooks_daemon/  # Source code (not pip package)
└── .claude/
    ├── hooks-daemon.yaml        # Config with self_install_mode: true
    └── hooks-daemon.env         # Sets HOOKS_DAEMON_ROOT_DIR
```

## Critical Paths

### Python Command

**ALWAYS use venv Python:**
```bash
PYTHON=/workspace/untracked/venv/bin/python
```

**NEVER use:**
- `python` (might be system Python)
- `python3` (might be system Python)
- `.claude/hooks-daemon/untracked/venv/bin/python` (doesn't exist in self-install mode)

### Config File

```bash
CONFIG=/workspace/.claude/hooks-daemon.yaml
```

Key setting:
```yaml
daemon:
  self_install_mode: true  # Runs from workspace root
```

### Environment File

`.claude/hooks-daemon.env`:
```bash
# Override daemon root directory to workspace
export HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"
```

This file is sourced by `.claude/init.sh` before any daemon operations.

### Source Code

Daemon imports from workspace source:
```
/workspace/src/claude_code_hooks_daemon/
```

NOT from pip installed package in venv.

## Daemon Lifecycle Commands

All commands use venv Python:

```bash
# Check if daemon is running
$PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Start daemon (if not running)
$PYTHON -m claude_code_hooks_daemon.daemon.cli start

# Stop daemon (graceful shutdown)
$PYTHON -m claude_code_hooks_daemon.daemon.cli stop

# Restart daemon (stop + start)
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart

# View daemon logs
$PYTHON -m claude_code_hooks_daemon.daemon.cli logs

# Health check
$PYTHON -m claude_code_hooks_daemon.daemon.cli health
```

## Development Workflow

### 1. Make Code Changes

Edit files in `/workspace/src/claude_code_hooks_daemon/`

### 2. Run QA

```bash
# Format and lint (auto-fixes)
./scripts/qa/run_autofix.sh

# Full QA suite
./scripts/qa/run_all.sh

# Individual checks
./scripts/qa/run_tests.sh         # Pytest with 95% coverage
./scripts/qa/run_type_check.sh    # MyPy strict mode
./scripts/qa/run_lint.sh           # Ruff linter
./scripts/qa/run_format_check.sh  # Black formatter
```

### 3. Test Changes

```bash
# Restart daemon to pick up code changes
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart

# Verify daemon is running
$PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Debug hooks if needed
./scripts/debug_hooks.sh start "Testing my changes"
# ... perform actions that trigger hooks ...
./scripts/debug_hooks.sh stop
```

### 4. Check Logs

If something goes wrong:
```bash
# View daemon logs
$PYTHON -m claude_code_hooks_daemon.daemon.cli logs

# Or check log files directly
tail -f untracked/logs/daemon.log
```

## Common Issues

### "ModuleNotFoundError: No module named 'claude_code_hooks_daemon'"

**Cause**: Using system Python instead of venv Python

**Fix**: Use `$PYTHON` (venv Python) for all commands
```bash
PYTHON=/workspace/untracked/venv/bin/python
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
```

### "Config file not found"

**Cause**: Daemon looking in wrong location (`.claude/hooks-daemon/` instead of `/workspace/`)

**Fix**: Ensure `.claude/hooks-daemon.env` exists and sets `HOOKS_DAEMON_ROOT_DIR`
```bash
# Should be set
echo $HOOKS_DAEMON_ROOT_DIR
# Output: /workspace (or similar)
```

### Changes Not Taking Effect

**Cause**: Daemon running old code from before restart

**Fix**: Restart daemon after code changes
```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
```

### "Socket already in use"

**Cause**: Old daemon process still running

**Fix**: Stop daemon forcefully
```bash
# Graceful stop
$PYTHON -m claude_code_hooks_daemon.daemon.cli stop

# If still running, check PID file
cat untracked/daemon.pid

# Kill process manually if needed
kill <PID>
rm untracked/daemon.pid
```

## How Self-Install Mode Works

### 1. Environment Setup

`.claude/init.sh` sources `.claude/hooks-daemon.env`:
```bash
if [ -f "$PROJECT_PATH/.claude/hooks-daemon.env" ]; then
    source "$PROJECT_PATH/.claude/hooks-daemon.env"
fi
```

### 2. Root Directory Override

`.claude/hooks-daemon.env` sets:
```bash
export HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"
```

This tells daemon code to use workspace root instead of `.claude/hooks-daemon/`.

### 3. Path Resolution

Daemon code (in `daemon/paths.py`) checks for `HOOKS_DAEMON_ROOT_DIR`:
```python
def get_daemon_root() -> Path:
    # Check environment override (for self-install mode)
    override = os.environ.get("HOOKS_DAEMON_ROOT_DIR")
    if override:
        return Path(override)

    # Normal mode: .claude/hooks-daemon/
    return get_workspace_root() / ".claude" / "hooks-daemon"
```

### 4. Config Detection

Daemon loads config and checks `self_install_mode`:
```python
config = load_config()
if config.get("daemon", {}).get("self_install_mode", False):
    # Running in self-install mode
    # All paths relative to workspace root
```

### 5. Source Import

Python imports modules from workspace source:
```python
# These resolve to /workspace/src/claude_code_hooks_daemon/
from claude_code_hooks_daemon.core import Handler
from claude_code_hooks_daemon.daemon.server import DaemonServer
```

Not from pip package in venv site-packages.

## Testing Self-Install Mode

### Verify Paths

```bash
# Check daemon root
$PYTHON -c "
from claude_code_hooks_daemon.daemon.paths import get_daemon_root
print(get_daemon_root())
"
# Should output: /workspace

# Check venv location
$PYTHON -c "import sys; print(sys.prefix)"
# Should output: /workspace/untracked/venv

# Check socket location
$PYTHON -c "
from claude_code_hooks_daemon.daemon.paths import get_socket_path
print(get_socket_path())
"
# Should output: /workspace/untracked/socket
```

### Verify Config

```bash
# Check self_install_mode setting
$PYTHON -c "
from claude_code_hooks_daemon.config.loader import ConfigLoader
config = ConfigLoader.load()
print(config.get('daemon', {}).get('self_install_mode', False))
"
# Should output: True
```

### Verify Source Import

```bash
# Check where code is imported from
$PYTHON -c "
import claude_code_hooks_daemon
print(claude_code_hooks_daemon.__file__)
"
# Should output: /workspace/src/claude_code_hooks_daemon/__init__.py
# NOT: /workspace/untracked/venv/lib/.../site-packages/...
```

## Switching Between Modes

### Normal Mode → Self-Install Mode

1. Set `self_install_mode: true` in config
2. Create `.claude/hooks-daemon.env` with `HOOKS_DAEMON_ROOT_DIR`
3. Install package in editable mode: `pip install -e .`
4. Restart daemon

### Self-Install Mode → Normal Mode

1. Set `self_install_mode: false` in config
2. Remove `.claude/hooks-daemon.env`
3. Install package normally: `pip install .`
4. Restart daemon

## When to Use Self-Install Mode

**Use self-install mode when:**
- Developing the hooks-daemon project itself (dogfooding)
- Testing unreleased features
- Debugging daemon internals
- Contributing to the project

**Use normal mode when:**
- Using hooks-daemon in other projects
- Running stable released version
- Don't need to modify daemon code

## Summary

Key points for self-install mode:

1. **Always use venv Python**: `/workspace/untracked/venv/bin/python`
2. **Paths are at workspace root**: `untracked/`, not `.claude/hooks-daemon/untracked/`
3. **Config has self_install_mode: true**: In `.claude/hooks-daemon.yaml`
4. **Environment sets HOOKS_DAEMON_ROOT_DIR**: In `.claude/hooks-daemon.env`
5. **Restart daemon after code changes**: Code runs from workspace source
