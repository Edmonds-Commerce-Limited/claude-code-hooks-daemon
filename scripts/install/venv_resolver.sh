#!/bin/bash
#
# venv_resolver.sh — thin bash wrapper around the Python SSOT.
#
# Plan 00100 Phase 2: the parallel bash implementation was deleted. All
# resolution logic now lives in
# src/claude_code_hooks_daemon/daemon/paths.py::resolve-venv, invoked as a
# direct script (NOT `python -m`) so the package __init__.py — which pulls
# pydantic — is bypassed. This matters at install-time, when the daemon venv
# may not yet exist and the host `python3` only has stdlib.
#
# This file preserves the bash-facing API (resolve_existing_venv_python,
# resolve_existing_venv_dir) so existing install/upgrade scripts keep
# working — they now shell out instead of re-implementing the precedence.

_VR_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
_VR_PATHS_SCRIPT="$_VR_PROJECT_ROOT/src/claude_code_hooks_daemon/daemon/paths.py"

# resolve_existing_venv_python <daemon_dir> [python_cmd]
#
# Prints the venv's bin/python. On Python SSOT failure (no venv found),
# prints the legacy path so bash callers still surface a "venv missing"
# message against a familiar filename. The CLI's per-step trace is
# discarded here — callers that want diagnostics should invoke the Python
# SSOT directly.
resolve_existing_venv_python() {
    local daemon_dir="$1"
    local python_cmd="${2:-${HOOKS_DAEMON_PYTHON:-python3}}"

    if [ -z "$daemon_dir" ]; then
        echo "resolve_existing_venv_python: daemon_dir required" >&2
        return 1
    fi

    if "$python_cmd" "$_VR_PATHS_SCRIPT" resolve-venv \
        --daemon-dir "$daemon_dir" 2> /dev/null; then
        return 0
    fi

    # SSOT said "nothing found" — preserve the legacy path for the caller's
    # own diagnostics (pre-v3.7.0 fallback filename).
    echo "$daemon_dir/untracked/venv/bin/python"
}

# resolve_existing_venv_dir <daemon_dir> [python_cmd]
#
# Same precedence as resolve_existing_venv_python, but returns the venv dir.
resolve_existing_venv_dir() {
    local python_path
    python_path=$(resolve_existing_venv_python "$@") || return 1
    echo "${python_path%/bin/python}"
}
