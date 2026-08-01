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
├── untracked/venv-py{MM}-{fp}/  # Virtual environment (fingerprint-keyed, v3.7.0+)
├── untracked/venv/              # Legacy (pre-v3.7.0) — auto-deleted on upgrade
├── untracked/daemon-{host}.sock # Unix socket (hostname-scoped)
├── untracked/daemon-{host}.pid  # PID file (hostname-scoped)
├── src/claude_code_hooks_daemon/  # Source code (not pip package)
└── .claude/
    ├── hooks-daemon.yaml        # Config with self_install_mode: true
    └── hooks-daemon.env         # Sets HOOKS_DAEMON_ROOT_DIR
```

### Why the venv is fingerprint-keyed (v3.7.0+)

Pre-v3.7.0 all installs shared a single `untracked/venv/`. That corrupts when the same project directory is opened in two different Python environments — e.g. inside a YOLO container (Fedora `/usr/bin/python3`) **and** directly on the desktop host (pyenv, homebrew, distro, or different arch).

v3.7.0 derives a fingerprint from `md5(sys.version | sys.base_prefix | platform.machine())[:8]` and uses it as the venv suffix. Two containers from the same image share a venv; different Pythons get different venvs and never collide. The daemon auto-detects stamp mismatches and rebuilds on first use in a new environment. CI sets `HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1` (or relies on `CI=true`) to bypass bootstrap.

Manage venvs with:

```bash
./bin/hooks-daemon list-venvs
./bin/hooks-daemon prune-venvs --legacy --dry-run
./bin/hooks-daemon prune-venvs --all-except-current --force
```

The current-environment venv is never deleted, even with `--force`.

## Critical Paths

### Daemon CLI

**Never name an interpreter.** The venv is fingerprint-keyed, so its path is
different on every machine and changes when the Python underneath it changes.
Use the wrapper — it resolves the interpreter itself:

```bash
./bin/hooks-daemon status
```

**NEVER use:**

- `python` / `python3` — the venv sets `include-system-site-packages = false`,
  so a PATH interpreter genuinely cannot import the package
- Any hardcoded `untracked/venv/bin/python` <!-- python-var-guidance-exempt: names the banned pattern to warn against it --> — that is the retired
  pre-v3.7.0 layout; `resolve_venv.sh` refuses it
- `$PYTHON` <!-- python-var-guidance-exempt: names the banned pattern to warn against it --> — never exported into your shell

**If you need the interpreter itself** (e.g. to run `pytest` directly), resolve
it through the canonical resolver rather than guessing:

```bash
source scripts/lib/resolve_venv.sh
PY="$(resolve_venv_python /workspace)"
"$PY" -m pytest tests/unit -q
```

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
./bin/hooks-daemon status

# Start daemon (if not running)
./bin/hooks-daemon start

# Stop daemon (graceful shutdown)
./bin/hooks-daemon stop

# Restart daemon (stop + start)
./bin/hooks-daemon restart

# View daemon logs
./bin/hooks-daemon logs

# Health check
./bin/hooks-daemon health
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
./bin/hooks-daemon restart

# Verify daemon is running
./bin/hooks-daemon status

# Debug hooks if needed
./scripts/debug_hooks.sh start "Testing my changes"
# ... perform actions that trigger hooks ...
./scripts/debug_hooks.sh stop
```

### 4. Check Logs

If something goes wrong:

```bash
# View daemon logs
./bin/hooks-daemon logs

# Or check log files directly
tail -f untracked/logs/daemon.log
```

## Common Issues

### "ModuleNotFoundError: No module named 'claude_code_hooks_daemon'"

**Cause**: You invoked a system `python3`. The daemon lives in an isolated,
fingerprint-keyed virtualenv built with `include-system-site-packages = false`,
so the PATH interpreter genuinely cannot import it. The package is installed —
the interpreter is simply the wrong one.

**Fix**: Use the wrapper. It resolves the correct interpreter itself, so you
never spell out a venv path (they are fingerprint-keyed and change):

```bash
./bin/hooks-daemon status
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
./bin/hooks-daemon restart
```

### "Socket already in use"

**Cause**: Old daemon process still running

**Fix**: Stop daemon forcefully

```bash
# Graceful stop
./bin/hooks-daemon stop

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
# Daemon root and socket location
./bin/hooks-daemon status
# Socket should be under /workspace/untracked/

# Venv location (fingerprint-keyed — never hardcode it)
./bin/hooks-daemon list-venvs
```

### Verify Config

```bash
# Check self_install_mode setting
./bin/hooks-daemon config
# The daemon section should show: self_install_mode: true
```

### Verify Source Import

```bash
# Confirm the install is importable and serving
./bin/hooks-daemon health
# In self-install mode the code is served from /workspace/src/
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

1. **Always use the wrapper**: `./bin/hooks-daemon` — never a hardcoded interpreter path
2. **Paths are at workspace root**: `untracked/`, not `.claude/hooks-daemon/untracked/`
3. **Config has self_install_mode: true**: In `.claude/hooks-daemon.yaml`
4. **Environment sets HOOKS_DAEMON_ROOT_DIR**: In `.claude/hooks-daemon.env`
5. **Restart daemon after code changes**: Code runs from workspace source
