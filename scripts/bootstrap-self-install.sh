#!/usr/bin/env bash
#
# Bootstrap a FRESH CLONE of the hooks-daemon repository into self-install mode.
#
# A clone carries the config, the forwarders and the package source. What it
# cannot carry is the per-checkout runtime: the virtualenv and
# .claude/hooks-daemon.env are gitignored by design, because both name absolute
# paths that are wrong in every other checkout. This script creates exactly
# those and nothing else.
#
# WHY THIS EXISTS AND NOT `install.py --self-install`
#
# install.py's create_daemon_config() and create_settings_json() do NOT skip an
# existing file. They rename it to `.bak` and write a DEFAULT TEMPLATE over it;
# `--force` only decides whether the backup is taken, so BOTH paths overwrite.
# On a CI runner that replaced this repository's own 1188-line
# hooks-daemon.yaml with a template invalid against the current schema, and the
# daemon then refused to start. install.py is the CLIENT installer: its job is
# to create files a client project does not have yet, and every one of them is
# already tracked here.
#
# The steps below are the ones .github/workflows/qa.yml proves on every run.
#
# Usage:
#   scripts/bootstrap-self-install.sh
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "Bootstrapping self-install at: $REPO_ROOT"

# Refuse to run anywhere but the daemon's own repository. Everywhere else this
# script is wrong in a way that is hard to see afterwards: it would write an
# env file pointing a CLIENT project's daemon at the client's own root, which
# is precisely the half-configured state init.sh's repo guard exists to catch.
if [[ ! -f "$REPO_ROOT/install.py" ]] || [[ ! -d "$REPO_ROOT/src/claude_code_hooks_daemon" ]]; then
    echo "ERROR: this is not the hooks-daemon repository (no install.py + src/claude_code_hooks_daemon)." >&2
    echo "       A client project installs the daemon with install.py instead." >&2
    exit 1
fi

if ! command -v uv >/dev/null; then
    echo "ERROR: 'uv' is required and was not found on PATH." >&2
    echo "       Install it from https://docs.astral.sh/uv/ then re-run this script." >&2
    exit 1
fi

PYTHON_CMD="$(command -v python3)"
echo "Using interpreter: $PYTHON_CMD"

# --fallback-target is the documented fresh-clone path: on a miss it echoes the
# fingerprint-keyed directory the CLI will later resolve on its own, rather than
# failing because no venv exists yet. Building anywhere else (a bare `uv sync`
# creates .venv/) produces a venv the resolver does not look in.
VENV_DIR="$(HOOKS_DAEMON_PYTHON="$PYTHON_CMD" bash scripts/lib/resolve_venv.sh dir "$REPO_ROOT" --fallback-target)"
echo "Virtualenv target:  $VENV_DIR"

UV_PROJECT_ENVIRONMENT="$VENV_DIR" uv sync --frozen --all-extras --python "$PYTHON_CMD"

# The gitignored file init.sh's repo guard accepts on mere existence. Written
# AFTER the venv so a failed sync never leaves a checkout that claims to be
# configured; the guard would then wave through a daemon that cannot start.
printf 'HOOKS_DAEMON_ROOT_DIR="%s"\n' "$REPO_ROOT" > .claude/hooks-daemon.env
echo "Wrote .claude/hooks-daemon.env"

./bin/hooks-daemon restart
./bin/hooks-daemon status

echo
echo "Done. Restart your Claude Code session so the hooks attach."
