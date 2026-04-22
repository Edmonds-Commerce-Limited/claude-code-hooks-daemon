#!/bin/bash
#
# _resolve-venv.sh - Shared venv Python resolver for hooks-daemon skill wrappers
#
# Sourced by daemon-cli.sh, health-check.sh, and init-handlers.sh. Sets PYTHON
# to the correct venv interpreter using the same precedence as init.sh's
# _resolve_python_cmd(), so that v3.7.0+ fingerprint-keyed venvs are found.
#
# REQUIRES: DAEMON_DIR is set (caller-provided, e.g. $PROJECT_ROOT/.claude/hooks-daemon)
#
# SETS:     PYTHON  — path to the venv's bin/python (may not exist; caller checks)
#
# Precedence (highest first):
#   1. $HOOKS_DAEMON_VENV_PATH                      — explicit override
#   2. $DAEMON_DIR/untracked/venv-{fingerprint}/    — fingerprint-keyed (v3.7.0+)
#   3. $DAEMON_DIR/untracked/venv-*/                — any existing fingerprint venv
#   4. $DAEMON_DIR/untracked/venv/                  — legacy fallback (pre-v3.7.0)
#
# Step 3 exists because the installer picks Python via $HOOKS_DAEMON_PYTHON
# (often a specific interpreter like /usr/bin/python3.13), but this resolver
# runs from a skill wrapper where $HOOKS_DAEMON_PYTHON is not set and `python3`
# on PATH may resolve to a different interpreter (e.g. 3.9 via system default).
# Recomputing the fingerprint with the "wrong" Python produces a name that
# doesn't match the venv on disk. Scanning for any healthy venv-* directory
# handles that mismatch — the venv's own bin/python symlink points to whichever
# base interpreter the installer chose, so the venv is usable regardless.
#
# The fingerprint helper ships with every daemon install at
# $DAEMON_DIR/scripts/install/python_fingerprint.sh. If it's missing (busted
# install) we skip step 2 and fall straight to the scan + legacy fallbacks.

if [ -z "${DAEMON_DIR:-}" ]; then
    echo "❌ _resolve-venv.sh: DAEMON_DIR must be set before sourcing" >&2
    # shellcheck disable=SC2317  # unreachable when sourced, intentional exec fallback
    return 1 2>/dev/null || exit 1
fi

if [ -n "${HOOKS_DAEMON_VENV_PATH:-}" ]; then
    PYTHON="$HOOKS_DAEMON_VENV_PATH/bin/python"
else
    _fp_helper="$DAEMON_DIR/scripts/install/python_fingerprint.sh"
    PYTHON=""
    if [ -f "$_fp_helper" ]; then
        # shellcheck disable=SC1090
        source "$_fp_helper"
        _fingerprint=""
        if _fingerprint=$(python_venv_fingerprint "${HOOKS_DAEMON_PYTHON:-python3}" 2>/dev/null); then
            _keyed_venv="$DAEMON_DIR/untracked/venv-$_fingerprint"
            if [ -x "$_keyed_venv/bin/python" ]; then
                PYTHON="$_keyed_venv/bin/python"
            fi
        fi
        unset _fingerprint _keyed_venv
    fi
    unset _fp_helper

    # Scan fallback: any existing venv-*/bin/python. Handles installer-vs-resolver
    # Python mismatch (installer used python3.13, resolver sees python3=3.9).
    if [ -z "$PYTHON" ]; then
        for _candidate in "$DAEMON_DIR"/untracked/venv-*/bin/python; do
            if [ -x "$_candidate" ]; then
                PYTHON="$_candidate"
                break
            fi
        done
        unset _candidate
    fi

    # Legacy fallback (pre-v3.7.0 installs, or fingerprint venv absent)
    if [ -z "$PYTHON" ]; then
        PYTHON="$DAEMON_DIR/untracked/venv/bin/python"
    fi
fi
