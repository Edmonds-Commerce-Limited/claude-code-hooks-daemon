# Self-Install Mode - Complete Guide

## What Is Self-Install Mode?

When `self_install_mode: true` in `.claude/hooks-daemon.yaml`, the daemon runs from the **workspace root** instead of `.claude/hooks-daemon/`. This allows the hooks-daemon project to dogfood itself during development.

## Path Differences

### Normal Installation

```
.claude/hooks-daemon/
├── untracked/venv-{slug}-py{MM}-{fingerprint}/  # Virtual environment (see "Venv layout" below)
├── untracked/socket             # Unix socket
├── untracked/daemon.pid         # PID file
└── (daemon runs from pip package)
```

### Self-Install Mode (This Project)

```
/workspace/
├── untracked/venv-{slug}-py{MM}-{fingerprint}/  # Virtual environment (see "Venv layout" below)
├── untracked/venv/              # Legacy (pre-v3.7.0) — auto-deleted on upgrade
├── untracked/daemon-{host}.sock # Unix socket (hostname-scoped)
├── untracked/daemon-{host}.pid  # PID file (hostname-scoped)
├── src/claude_code_hooks_daemon/  # Source code (not pip package)
└── .claude/
    ├── hooks-daemon.yaml        # Config with self_install_mode: true
    └── hooks-daemon.env         # Sets HOOKS_DAEMON_ROOT_DIR
```

## Venv layout (canonical documented home)

**This section is the canonical documented home for the venv directory layout.**
The real source of truth is the code — `src/claude_code_hooks_daemon/daemon/paths.py`
(`python_venv_fingerprint()` and `get_daemon_venv_path()`) composes the name —
so this section states the derived fact once and every other doc points here.

The venv directory is:

```
untracked/venv-{slug}-py{MM}-{fingerprint}/
```

- `{slug}` — derived from the absolute project root path (v3.19.1+); keeps a
  host view (e.g. `/home/user/project`) and a container view (`/workspace`) of
  the SAME bind-mounted project on separate venvs.
- `py{MM}` — Python major+minor, e.g. `py311`.
- `{fingerprint}` — `md5(sys.version | sys.base_prefix | platform.machine())[:8]`;
  lets concurrent containers from the same image share one venv while distinct
  Pythons get distinct venvs.

In self-install mode (this repo) it lives under `{project}/untracked/`; in a
normal client install under `{project}/.claude/hooks-daemon/untracked/`.

**Never hand-build a venv and never hardcode this path** — the name changes
with machine, path and Python. Use the `bin/hooks-daemon` wrapper, or resolve
the interpreter via `scripts/lib/resolve_venv.sh` (see "Daemon CLI" below). A
hand-made `untracked/venv/` is the retired pre-v3.7.0 layout: `resolve_venv.sh`
refuses it and every wrapper call exits 5.

### Why the venv is fingerprint-keyed (v3.7.0+)

Pre-v3.7.0 all installs shared a single `untracked/venv/`. That corrupts when the same project directory is opened in two different Python environments — e.g. inside a YOLO container (Fedora `/usr/bin/python3`) **and** directly on the desktop host (pyenv, homebrew, distro, or different arch).

v3.7.0 introduced the fingerprint suffix; v3.19.1 added the project-path slug. CI sets `HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1` (or relies on `CI=true`) to bypass AUTOMATIC bootstrap: `ensure_venv` skips, and the hook path reports "switched off" naming the setting. An explicit `bin/hooks-daemon repair` is a deliberate request and builds regardless (it says it is overriding the setting).

What rebuilds a venv, and when:

- **A venv that is MISSING for this project path is built on first use, from the hook path.** The usual case is the second view (host vs container) of a bind-mounted project, which shares the clone but not its per-path venv. The first hook that finds a real clone with a readable version and no venv for its path runs the clone's `scripts/venv_bootstrap.sh`. That script checks five conditions without a venv: `uv` on PATH (or in `~/.local/bin`), a parseable `pyproject.toml`, a `uv.lock`, a Python meeting `requires-python`, and a writable `untracked/`. If all five hold, it starts ONE detached `ensure_venv` build under the venv build lock, and the hook returns at once with the build's log path (`untracked/.venv-bootstrap-<fingerprint>.log`). Hooks time out at 60s and a `uv sync` can take longer, which is why the build is detached. Concurrent hooks start no second build. The next hook after the build finishes starts the daemon. If a condition does not hold, nothing is changed, and the hook message names each failed condition with its fix.
- **The detached build is bounded and findable, on every platform.** The build runs as its own process group, watched by a watchdog in the build process itself (no `timeout` command needed, so stock macOS is bounded too). `HOOKS_DAEMON_VENV_BUILD_TIMEOUT` seconds (900) after the hook started it, the group gets TERM, then KILL 30s later, and only that is recorded as "timed out". Any other stop (a shutdown, someone ending the pid) records no failure, so the next hook retries, and no stop counts as a failure when the venv resolves anyway. While it runs, `untracked/.venv-bootstrap.current` records its log, start time, bound and pid, and the hook message shows the pid and how long it has run. `repair`, the skill's in-place repair and an upgrade that find the lock held by that build wait out the build's own bound, not the generic 120s lock wait. Without `flock`, the lock is a directory whose holder refreshes its age every `HOOKS_DAEMON_VENV_LOCK_HEARTBEAT_SECONDS` (60), so a long build is never mistaken for a dead one (600s), and a holder only ever removes a lock whose `pid` is its own. Only a holder that keeps the lock runs a heartbeat (a hook that takes the lock just to read the failed marker does not), and stopping a heartbeat also stops its `sleep`.
- **A failed automatic build is not retried on every hook.** It leaves `untracked/.venv-bootstrap-<fingerprint>.failed`, judged under the build lock so a hook racing the failure cannot retry it. Hooks report "the last build failed" with the log, and retry only after `pyproject.toml`, `uv.lock`, the interpreter or the uv binary (its path, size or mtime, so `uv self update` counts) changes. `bin/hooks-daemon repair` retries at once, in the foreground: it builds the venv even when none exists, then runs the normal repair with the same uv the build used (`~/.local/bin` included).
- **A venv that exists but is stale** (its `lock_hash` no longer matches `pyproject.toml` + `uv.lock`) is rebuilt by `ensure_venv` on install, upgrade and `repair`, not by a hook. A stale venv still resolves, so the daemon still starts from it.
- **The automatic build and `repair` never touch another environment's venv.** A version-CHANGING upgrade is different: it deliberately removes every other `venv-*` (Plan 00100's eager cleanup), and each other environment's next hook then builds its own again. `HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1` or `CI=true` switches the automatic build off. The hook message then names the setting and `repair`, which builds regardless.

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

### The conventional client path (`.claude/hooks-daemon/bin/hooks-daemon`)

Every hooks-daemon project should expose the CLI at
`<project>/.claude/hooks-daemon/bin/hooks-daemon` -- external session
managers look for it there, because a normal client install's cloned daemon
already lives at that path. A self-install checkout has no clone: `bin/`
sits at the project root instead. `ProjectContext.initialize` (the single
chokepoint every daemon-adjacent process passes through once at startup)
creates a relative symlink to close that gap:

```text
.claude/hooks-daemon/bin/hooks-daemon -> ../../../bin/hooks-daemon
```

So both paths work from the very first daemon start or CLI invocation in a
self-install checkout, main or worktree:

```bash
./bin/hooks-daemon status                              # always worked
.claude/hooks-daemon/bin/hooks-daemon status            # now also works
```

**Generated, not tracked.** The link is created idempotently (never
overwrites an existing symlink or a real file) and lives under
`.claude/hooks-daemon/`, which `.claude/.gitignore` already excludes for a
different reason (it is where a CLIENT'S clone would go). A tracked link
would defeat that: clients install by cloning this repository into
`<client>/.claude/hooks-daemon/`, so a tracked link would land at
`<client>/.claude/hooks-daemon/.claude/hooks-daemon/` in every client --
and `.claude/init.sh`'s nested-installation check treats exactly that
directory as a broken install.

Because `.claude/hooks-daemon/` now genuinely exists in a self-install
checkout (once the daemon has started at least once), every check that
used to read "does this directory exist" as "is a client clone installed
here" had to be re-keyed on a REAL clone instead -- something a client
clone has and the link-only marker does not, namely its own
`pyproject.toml`. See Plan 00455 for the full audit of affected sites (bash
and Python) and which were already safe.

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

# Full QA suite (agent entry point; run_all.sh is the human-verbose variant)
./scripts/qa/llm_qa.py all

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
from claude_code_hooks_daemon.daemon.server import HooksDaemon
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
# NOT: /workspace/untracked/venv-*/lib/.../site-packages/...
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
