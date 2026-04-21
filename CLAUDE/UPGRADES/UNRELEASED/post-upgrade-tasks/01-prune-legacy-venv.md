# Task: Prune legacy pre-fingerprint venv

**Type**: workflow-change
**Severity**: recommended
**Applies to**: all pre-v3.7.0 installs (upgrade will handle this automatically when the install succeeds, but manual cleanup is needed if the old venv was in an unusual location or the automatic cleanup was skipped)
**Idempotent**: yes

## Why

v3.7.0 changes the daemon's venv layout. Pre-v3.7.0 daemons used a single venv at `untracked/venv/` (or `.claude/hooks-daemon/untracked/venv/` in normal-install mode). That design breaks when the same project directory is opened in two different Python environments — e.g. once inside a YOLO container (Fedora `/usr/bin/python3`) and once directly on a desktop host (pyenv, homebrew, distro, or a different architecture). Each environment would rewrite the same shared venv, corrupting it for the other.

v3.7.0 keys the venv by a Python-environment fingerprint:

```
untracked/venv-py{MAJOR}{MINOR}-{fingerprint}/
```

where `{fingerprint} = md5(sys.version | sys.base_prefix | platform.machine())[:8]`. This lets concurrent containers from the same image share one venv while distinct Pythons are kept apart.

The installer and upgrader in v3.7.0 automatically delete the legacy `untracked/venv/` once the fingerprint-keyed venv is provisioned and the daemon is verified RUNNING. But if you have non-standard setups — custom venv paths, multiple project clones, or an aborted upgrade — you may still have a legacy venv on disk.

## How to detect if this applies to you

After upgrading to v3.7.0, list venvs under the daemon's untracked directory:

```bash
# sample — adapt to your install mode
$PYTHON -m claude_code_hooks_daemon.daemon.cli list-venvs
```

If the output shows a row labelled `(legacy pre-fingerprint)` alongside rows named `venv-py{MM}-{fingerprint}`, the legacy venv was not auto-deleted during upgrade.

You can also check directly:

```bash
# self-install mode
ls /workspace/untracked/ | grep '^venv'

# normal install mode
ls .claude/hooks-daemon/untracked/ | grep '^venv'
```

Presence of a bare `venv/` directory alongside one or more `venv-py{MM}-{fingerprint}/` directories = legacy venv is still present.

## How to handle

Use the new `prune-venvs` CLI. Always dry-run first:

```bash
# sample — what would be removed?
$PYTHON -m claude_code_hooks_daemon.daemon.cli prune-venvs --legacy --dry-run

# If the dry-run output matches your expectations, run it for real:
$PYTHON -m claude_code_hooks_daemon.daemon.cli prune-venvs --legacy --force
```

`prune-venvs --legacy` only removes the single legacy `untracked/venv/` — it will not touch any `venv-py{MM}-{fingerprint}/` directory. The current-environment fingerprint venv is never deleted, even with `--force`.

If you accidentally have multiple fingerprint venvs from unused environments (e.g. you switched Python versions several times during testing), you can clean those up too:

```bash
# sample — remove all except current env's venv
$PYTHON -m claude_code_hooks_daemon.daemon.cli prune-venvs --all-except-current --dry-run
$PYTHON -m claude_code_hooks_daemon.daemon.cli prune-venvs --all-except-current --force
```

The non-current environments will auto-rebuild their venvs lazily the next time the daemon starts under those environments (stamp mismatch triggers a rebuild).

## How to confirm

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli list-venvs
```

Expected: no `(legacy pre-fingerprint)` row. Only `venv-py{MM}-{fingerprint}/` rows, with the current environment's row marked with `←` or `current`.

Daemon still healthy:

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: Daemon: RUNNING
```

## Rollback / if this goes wrong

`prune-venvs` only removes directories under `untracked/` that are recognised as venvs (have `bin/python`). It does not touch source code, config, or hook scripts.

If the daemon won't start after pruning, the fingerprint venv for the current environment can always be rebuilt:

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli repair
```

This re-runs `uv sync` against `get_venv_path()` (the fingerprint-keyed path) and restarts the daemon. You do not need the legacy venv to recover — the rebuild is self-contained.
