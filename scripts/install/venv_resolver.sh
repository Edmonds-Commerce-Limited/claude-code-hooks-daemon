#!/bin/bash
#
# venv_resolver.sh - Resolve an existing venv's Python path, DAEMON_DIR-relative
#
# Used by install/upgrade/verify bash scripts that run AFTER the fingerprint-keyed
# venv has been provisioned. Mirrors the precedence in the shipped skill helper
# src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh so
# that install-time scripts find the same venv the skill wrappers find.
#
# Precedence (highest first):
#   1. $HOOKS_DAEMON_VENV_PATH                    — explicit override
#   2. $DAEMON_DIR/untracked/venv-{fingerprint}/  — recomputed fingerprint
#   3. $DAEMON_DIR/untracked/venv-*/              — any existing fingerprint venv
#   4. $DAEMON_DIR/untracked/venv/                — legacy fallback (pre-v3.7.0)
#
# Step 3 covers the case where the installer built the venv under one Python
# (e.g. /usr/bin/python3.13, HOOKS_DAEMON_PYTHON set) but the recomputing
# caller resolves a different fingerprint (e.g. `python3` → 3.9). The venv's
# own bin/python symlinks the installer-chosen interpreter, so any on-disk
# venv-*/bin/python is usable regardless of current PATH resolution.

# Ensure python_fingerprint.sh is sourced. Callers should source it explicitly;
# this sourced-or-not check lets us no-op safely if they already did.
if ! declare -F python_venv_fingerprint > /dev/null; then
    _vr_fp_helper="$(dirname "${BASH_SOURCE[0]}")/python_fingerprint.sh"
    if [ -f "$_vr_fp_helper" ]; then
        # shellcheck source=python_fingerprint.sh
        source "$_vr_fp_helper"
    fi
    unset _vr_fp_helper
fi

# resolve_existing_venv_python <daemon_dir> [python_cmd]
#
# Prints the path to the venv's bin/python. Does NOT check file existence on
# the final fallback — callers handle "missing" themselves so the error message
# still mentions the legacy path (useful diagnostic for brand-new installs
# where nothing has been provisioned yet).
#
# Args:
#   $1 - daemon_dir (required): Path to daemon install dir
#   $2 - python_cmd (optional): Python to fingerprint (default: HOOKS_DAEMON_PYTHON or python3)
resolve_existing_venv_python() {
    local daemon_dir="$1"
    local python_cmd="${2:-${HOOKS_DAEMON_PYTHON:-python3}}"

    if [ -z "$daemon_dir" ]; then
        echo "resolve_existing_venv_python: daemon_dir required" >&2
        return 1
    fi

    if [ -n "${HOOKS_DAEMON_VENV_PATH:-}" ]; then
        echo "$HOOKS_DAEMON_VENV_PATH/bin/python"
        return 0
    fi

    if declare -F python_venv_fingerprint > /dev/null; then
        local _fp
        # Fingerprint failure is an expected fallthrough condition (missing
        # interpreter, non-Python target). Downstream scan + legacy fallbacks
        # produce a valid result; the bash stderr from python itself is
        # preserved for diagnostic purposes.
        if _fp=$(python_venv_fingerprint "$python_cmd" 2> /dev/null); then
            local _keyed="$daemon_dir/untracked/venv-$_fp/bin/python"
            if [ -x "$_keyed" ]; then
                echo "$_keyed"
                return 0
            fi
        fi
    fi

    # Scan fallback: any existing venv-*/bin/python
    local _candidate
    for _candidate in "$daemon_dir"/untracked/venv-*/bin/python; do
        if [ -x "$_candidate" ]; then
            echo "$_candidate"
            return 0
        fi
    done

    # Legacy fallback
    echo "$daemon_dir/untracked/venv/bin/python"
}

# resolve_existing_venv_dir <daemon_dir> [python_cmd]
#
# Same precedence as resolve_existing_venv_python, but returns the directory.
resolve_existing_venv_dir() {
    local python_path
    python_path=$(resolve_existing_venv_python "$@") || return 1
    # Strip /bin/python suffix
    echo "${python_path%/bin/python}"
}
