#!/bin/bash
#
# upgrade.sh - Upgrade hooks daemon to new version
#
# Usage:
#   ./upgrade.sh [VERSION]
#
# Arguments:
#   VERSION (optional): Target version (e.g., 2.14.0 or v2.14.0)
#                       If omitted, upgrades to latest version
#

set -euo pipefail

# === SELF-BOOTSTRAP BEGIN (Plan 00104 Task 5.1, Decision 3.C) ===
# When this skill upgrade.sh is older than the latest release, replace
# ourselves with the freshly-downloaded version before doing any work.
# The 2026-05-01 field report (Issue #1) showed that a stale skill
# upgrade.sh ships the user a broken upgrade flow that no in-repo fix
# can save once the user already has the bad copy installed. Bootstrap
# from the GitHub release artifact, sha256-verify against the
# manifest, and re-exec with --already-bootstrapped to break recursion.
# Aborts loudly on any network or integrity failure — never silently
# falls back to the local stale copy (a silent fallback would mean a
# tampered or corrupted release reaches production).
#
# Override base URL for testing via HOOKS_DAEMON_BOOTSTRAP_BASE_URL.
_HOOKS_DAEMON_BOOTSTRAP_BASE_URL_DEFAULT="https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/releases/latest/download"
_HOOKS_DAEMON_BOOTSTRAP_BASE_URL="${HOOKS_DAEMON_BOOTSTRAP_BASE_URL:-$_HOOKS_DAEMON_BOOTSTRAP_BASE_URL_DEFAULT}"

if [ "${1:-}" = "--already-bootstrapped" ]; then
    shift
else
    _self_sha256() {
        if command -v sha256sum > /dev/null; then
            sha256sum "$1" | awk '{print $1}'
        elif command -v shasum > /dev/null; then
            shasum -a 256 "$1" | awk '{print $1}'
        else
            echo "Error: neither sha256sum nor shasum is available — cannot verify bootstrap integrity" >&2
            exit 1
        fi
    }

    _bootstrap_tmp_checksums="$(mktemp)"
    trap 'rm -f "$_bootstrap_tmp_checksums"' EXIT
    if ! curl -fsSL --max-time 30 -o "$_bootstrap_tmp_checksums" \
            "$_HOOKS_DAEMON_BOOTSTRAP_BASE_URL/bootstrap-checksums.txt"; then
        echo "Error: failed to download bootstrap-checksums.txt from" >&2
        echo "    $_HOOKS_DAEMON_BOOTSTRAP_BASE_URL/bootstrap-checksums.txt" >&2
        echo "Self-bootstrap aborted. Check network connectivity and retry." >&2
        exit 1
    fi

    _expected_sha="$(awk '/  upgrade\.sh$/ {print $1; exit}' "$_bootstrap_tmp_checksums")"
    if [ -z "$_expected_sha" ]; then
        echo "Error: bootstrap-checksums.txt has no entry for upgrade.sh" >&2
        echo "Self-bootstrap aborted. The release manifest is incomplete." >&2
        exit 1
    fi

    _own_sha="$(_self_sha256 "$0")"
    if [ "$_own_sha" != "$_expected_sha" ]; then
        _bootstrap_tmp_fresh="$(mktemp)"
        trap 'rm -f "$_bootstrap_tmp_checksums" "$_bootstrap_tmp_fresh"' EXIT
        if ! curl -fsSL --max-time 30 -o "$_bootstrap_tmp_fresh" \
                "$_HOOKS_DAEMON_BOOTSTRAP_BASE_URL/upgrade.sh"; then
            echo "Error: failed to download fresh upgrade.sh from" >&2
            echo "    $_HOOKS_DAEMON_BOOTSTRAP_BASE_URL/upgrade.sh" >&2
            echo "Self-bootstrap aborted. Check network connectivity and retry." >&2
            exit 1
        fi
        _fresh_sha="$(_self_sha256 "$_bootstrap_tmp_fresh")"
        if [ "$_fresh_sha" != "$_expected_sha" ]; then
            echo "Error: checksum mismatch for downloaded upgrade.sh" >&2
            echo "    Expected: $_expected_sha" >&2
            echo "    Got:      $_fresh_sha" >&2
            echo "Self-bootstrap aborted. The download was tampered with or the" >&2
            echo "release manifest is inconsistent — do not run this script." >&2
            exit 1
        fi
        chmod +x "$_bootstrap_tmp_fresh"
        exec bash "$_bootstrap_tmp_fresh" --already-bootstrapped "$@"
    fi
    trap - EXIT
    rm -f "$_bootstrap_tmp_checksums"
fi
# === SELF-BOOTSTRAP END ===

# Detect project root
PROJECT_ROOT="$(pwd)"
while [ "$PROJECT_ROOT" != "/" ]; do
    if [ -f "$PROJECT_ROOT/.claude/hooks-daemon.yaml" ]; then
        break
    fi
    PROJECT_ROOT="$(dirname "$PROJECT_ROOT")"
done

if [ ! -f "$PROJECT_ROOT/.claude/hooks-daemon.yaml" ]; then
    echo "Error: Not in a hooks daemon project (no .claude/hooks-daemon.yaml found)"
    exit 1
fi

DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
TARGET_VERSION="${1:-}"

echo "Claude Code Hooks Daemon - Upgrade"
echo ""
echo "Project:        $PROJECT_ROOT"
echo "Daemon:         $DAEMON_DIR"
echo "Target version: ${TARGET_VERSION:-latest (auto-detect)}"
echo ""

# Check if daemon directory exists
if [ ! -d "$DAEMON_DIR" ]; then
    echo "Error: Daemon directory not found: $DAEMON_DIR"
    echo ""
    echo "Run installation first:"
    echo "  /hooks-daemon install"
    exit 1
fi

# Plan 00100 Task 0.3: Python version pre-check BEFORE any daemon mutation.
# Parse the daemon's requires-python from pyproject.toml (single source of
# truth; never hardcoded) and compare with the active python3 --version.
# If the active python3 is too old and HOOKS_DAEMON_PYTHON is unset, emit
# an actionable hint and exit WITHOUT touching daemon state.
PYPROJECT_PATH="$DAEMON_DIR/pyproject.toml"
PARSE_MIN_PYTHON="$DAEMON_DIR/scripts/install/parse_min_python.sh"
if [ -f "$PYPROJECT_PATH" ] && [ -f "$PARSE_MIN_PYTHON" ]; then
    MIN_PY="$(bash "$PARSE_MIN_PYTHON" "$PYPROJECT_PATH")"
    ACTIVE_PY_CMD="${HOOKS_DAEMON_PYTHON:-python3}"
    if command -v "$ACTIVE_PY_CMD" >/dev/null; then
        ACTIVE_PY_VER="$("$ACTIVE_PY_CMD" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        MIN_MAJOR="${MIN_PY%.*}"; MIN_MINOR="${MIN_PY#*.}"
        ACT_MAJOR="${ACTIVE_PY_VER%.*}"; ACT_MINOR="${ACTIVE_PY_VER#*.}"
        if [ "$ACT_MAJOR" -lt "$MIN_MAJOR" ] || { [ "$ACT_MAJOR" -eq "$MIN_MAJOR" ] && [ "$ACT_MINOR" -lt "$MIN_MINOR" ]; }; then
            echo "Error: Active python3 is $ACTIVE_PY_VER but daemon requires >=$MIN_PY (from pyproject.toml)"
            echo ""
            echo "Retry with a compatible interpreter:"
            echo "  HOOKS_DAEMON_PYTHON=python${MIN_PY} /hooks-daemon upgrade"
            echo ""
            echo "Daemon state unchanged."
            exit 1
        fi
    fi
fi

# Check if upgrade script exists
UPGRADE_SCRIPT="$DAEMON_DIR/scripts/upgrade.sh"
if [ ! -f "$UPGRADE_SCRIPT" ]; then
    echo "Error: Upgrade script not found: $UPGRADE_SCRIPT"
    echo ""
    echo "Your daemon installation may be incomplete or from an older version."
    echo "Try reinstalling from scratch."
    exit 1
fi

# Plan 00104 Task 5.1 (Issue #3): remove stray ``uv.lock`` in the daemon
# directory before delegating to Layer 1. The Layer 1 upgrader runs
# ``git checkout`` against the new tag; if the previous run left a
# ``uv.lock`` untracked in $DAEMON_DIR, git refuses the checkout with
# "untracked working tree files would be overwritten by checkout".
# uv.lock is regenerated by every ``uv sync`` so removing it is safe.
if [ -f "$DAEMON_DIR/uv.lock" ]; then
    rm -f "$DAEMON_DIR/uv.lock"
fi

# Execute the daemon's upgrade script
echo "Executing upgrade..."
echo ""

cd "$PROJECT_ROOT"
if [ -n "$TARGET_VERSION" ]; then
    bash "$UPGRADE_SCRIPT" --project-root "$PROJECT_ROOT" "$TARGET_VERSION"
else
    bash "$UPGRADE_SCRIPT" --project-root "$PROJECT_ROOT"
fi
