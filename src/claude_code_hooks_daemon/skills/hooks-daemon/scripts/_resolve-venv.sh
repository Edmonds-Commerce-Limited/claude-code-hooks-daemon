#!/bin/bash
#
# _resolve-venv.sh - Shared venv Python resolver for hooks-daemon skill wrappers.
#
# Plan 00100 Phase 2: the parallel bash implementation was deleted. All
# resolution logic now lives in the Python SSOT:
#   $DAEMON_DIR/src/claude_code_hooks_daemon/daemon/paths.py::resolve-venv
#
# The SSOT is invoked as a DIRECT SCRIPT (not `python -m`) so the package
# __init__.py — which imports pydantic — is bypassed. This matters here
# because the wrapper runs under whatever `python3` the host provides, which
# often has only stdlib at skill-invocation time.
#
# Sourced by daemon-cli.sh, health-check.sh, and init-handlers.sh.
#
# REQUIRES: DAEMON_DIR is set (caller-provided, e.g. $PROJECT_ROOT/.claude/hooks-daemon)
#
# SETS:     PYTHON  — path to the venv's bin/python (may not exist; caller checks)
#
# Precedence (delegated to the Python SSOT):
#   1. $HOOKS_DAEMON_VENV_PATH                      — explicit override
#   2. $DAEMON_DIR/untracked/venv-{fingerprint}/    — fingerprint-keyed (v3.7.0+)
#   3. $DAEMON_DIR/untracked/venv-*/                — any existing fingerprint venv
#   4. $DAEMON_DIR/untracked/venv/                  — legacy fallback (pre-v3.7.0)
#
# When every step misses we fall back to the legacy path string so the
# caller's own 'venv missing' diagnostic fires against a familiar filename.

if [ -z "${DAEMON_DIR:-}" ]; then
    echo "❌ _resolve-venv.sh: DAEMON_DIR must be set before sourcing" >&2
    # shellcheck disable=SC2317  # unreachable when sourced, intentional exec fallback
    return 1 2>/dev/null || exit 1
fi

_rv_paths_script="$DAEMON_DIR/src/claude_code_hooks_daemon/daemon/paths.py"
_rv_python_cmd="${HOOKS_DAEMON_PYTHON:-python3}"

if [ -f "$_rv_paths_script" ] \
    && PYTHON=$("$_rv_python_cmd" "$_rv_paths_script" resolve-venv --daemon-dir "$DAEMON_DIR" 2> /dev/null); then
    :
else
    # SSOT missing or reported "no venv found" — preserve the legacy path so
    # callers still surface a familiar 'venv missing' diagnostic.
    PYTHON="$DAEMON_DIR/untracked/venv/bin/python"
fi
# shellcheck disable=SC2034  # PYTHON is exported for the sourcing caller.
export PYTHON

unset _rv_paths_script _rv_python_cmd
