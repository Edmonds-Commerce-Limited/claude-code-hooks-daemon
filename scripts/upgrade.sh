#!/bin/bash
#
# Claude Code Hooks Daemon - Upgrade Script (Layer 1)
#
# SECURITY: Always fetch the latest version from GitHub before running:
#   curl -fsSL https://raw.githubusercontent.com/.../scripts/upgrade.sh -o /tmp/upgrade.sh
#   less /tmp/upgrade.sh   # Review contents
#   bash /tmp/upgrade.sh --project-root /path/to/project [VERSION]
#
# This is a minimal Layer 1 script that:
# 1. Takes explicit project root (no magic detection)
# 2. Stops daemon (best-effort)
# 3. Checks out target version
# 4. Cleans up nested install artifacts
# 5. Delegates to Layer 2 (scripts/upgrade_version.sh)
#
# Arguments:
#   --project-root PATH  - REQUIRED: Project root directory
#   VERSION              - Git tag to upgrade to (optional, defaults to latest)
#

set -euo pipefail

# ============================================================
# Argument parsing
# ============================================================

PROJECT_ROOT=""
TARGET_VERSION=""

while [ $# -gt 0 ]; do
    case "$1" in
        --project-root)
            [ -n "${2:-}" ] || { echo "ERR --project-root requires a path argument" >&2; exit 1; }
            PROJECT_ROOT="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: upgrade.sh --project-root PATH [VERSION]"
            echo ""
            echo "  --project-root PATH  Project root directory (REQUIRED)"
            echo "  VERSION              Git tag to upgrade to (default: latest)"
            exit 0
            ;;
        -*)
            echo "ERR Unknown option: $1" >&2
            echo "Usage: upgrade.sh --project-root PATH [VERSION]" >&2
            exit 1
            ;;
        *)
            # Positional arg = version
            TARGET_VERSION="$1"
            shift
            ;;
    esac
done

# Minimal output functions
if [ -t 1 ]; then
    _RED='\033[0;31m'; _GREEN='\033[0;32m'; _YELLOW='\033[1;33m'
    _BLUE='\033[0;34m'; _BOLD='\033[1m'; _NC='\033[0m'
else
    _RED=''; _GREEN=''; _YELLOW=''; _BLUE=''; _BOLD=''; _NC=''
fi

_ok()   { echo -e "${_GREEN}OK${_NC} $1"; }
_err()  { echo -e "${_RED}ERR${_NC} $1" >&2; }
_warn() { echo -e "${_YELLOW}WARN${_NC} $1"; }
_info() { echo -e "${_BLUE}>>>${_NC} $1"; }
_fail() { _err "$1"; exit 1; }

# ============================================================
# Python version detection
# ============================================================

#
# _is_python_at_least_311() - Verify a Python interpreter is 3.11 or newer
#
# Plan 00103 Decision 3 Rule B: parses ``--version`` output rather than
# trusting the command name (because ``python3`` on RHEL/CentOS is 3.9 and
# on a Debian image may be anything from 3.7 to 3.13). Asserts MAJOR == 3
# AND MINOR >= 11, OR MAJOR > 3 (covers a hypothetical Python 4).
#
# Args:
#   $1 - cmd: Path or name of Python interpreter to probe
#
# Returns:
#   0 - cmd is executable AND reports Python 3.11+
#   1 - cmd missing, non-executable, or reports Python <3.11
#
# (Plan 00104 will move this helper into a shared library; currently
# duplicated between scripts/upgrade.sh and scripts/install/prerequisites.sh
# per the Decision 3 acceptance plan.)
#
_is_python_at_least_311() {
    local cmd="$1"
    [ -n "$cmd" ] || return 1
    if ! command -v "$cmd" > /dev/null; then
        return 1
    fi
    local version_output=""
    version_output="$("$cmd" --version 2>&1)" || return 1
    if [[ "$version_output" =~ Python[[:space:]]+([0-9]+)\.([0-9]+) ]]; then
        local major="${BASH_REMATCH[1]}"
        local minor="${BASH_REMATCH[2]}"
        if [ "$major" -gt 3 ]; then
            return 0
        fi
        if [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; then
            return 0
        fi
    fi
    return 1
}

#
# find_compatible_python() - Find a Python 3.11+ interpreter
#
# Plan 00103 Decision 3 Rule B (probe-list ban):
#   - Bare ``python3`` is INTENTIONALLY excluded from the candidate list.
#     Bare ``python3`` is a "diceroll" on the user's PATH (RHEL/CentOS-default
#     ``python3`` is 3.9, container images vary, etc). Probing it first means
#     the daemon gets bootstrapped against the wrong interpreter and fails
#     deep in the call stack with confusing errors. The probe must only use
#     versioned commands (``python3.11`` and up).
#   - ``compgen -c python3.`` enumerates PATH for any ``python3.NN`` so future
#     versions like 3.14 / 3.15 are picked up automatically without requiring
#     a daemon update.
#   - ``HOOKS_DAEMON_PYTHON`` is honoured as an explicit *input* override
#     (validated against the 3.11 minimum). An invalid override fails fast —
#     never silently falls back to PATH probing because that masks the user's
#     misconfiguration.
#
# Sets and exports HOOKS_DAEMON_PYTHON so Layer 2 scripts can use it.
#
# Returns:
#   0 - compatible Python found (HOOKS_DAEMON_PYTHON exported)
#   1 - no compatible Python found (exits via _fail)
#
find_compatible_python() {
    # Step 1: explicit override wins (validated, no fallback on failure).
    if [ -n "${HOOKS_DAEMON_PYTHON:-}" ]; then
        if _is_python_at_least_311 "$HOOKS_DAEMON_PYTHON"; then
            export HOOKS_DAEMON_PYTHON
            _ok "Compatible Python found: $HOOKS_DAEMON_PYTHON ($("$HOOKS_DAEMON_PYTHON" --version 2>&1))"
            return 0
        fi
        _fail "HOOKS_DAEMON_PYTHON=$HOOKS_DAEMON_PYTHON is not a usable Python 3.11+ interpreter.

Refusing to fall back to PATH probing — that would silently mask your broken override.

Either:
  - Unset HOOKS_DAEMON_PYTHON and let the installer probe PATH, or
  - Point HOOKS_DAEMON_PYTHON at an absolute path to a Python 3.11 or newer interpreter."
    fi

    # Step 2: build candidate list (versioned only) + open-ended discovery.
    local candidates=("python3.13" "python3.12" "python3.11")
    local discovered=""
    discovered="$(compgen -c "python3." 2> /dev/null)" || discovered=""
    if [ -n "$discovered" ]; then
        local cmd
        while IFS= read -r cmd; do
            [[ "$cmd" =~ ^python3\.[0-9]+$ ]] || continue
            local already=0
            local existing
            for existing in "${candidates[@]}"; do
                if [ "$existing" = "$cmd" ]; then
                    already=1
                    break
                fi
            done
            if [ "$already" -eq 0 ]; then
                candidates+=("$cmd")
            fi
        done <<< "$discovered"
    fi

    # Step 3: probe candidates in order; first 3.11+ match wins.
    local candidate
    for candidate in "${candidates[@]}"; do
        if _is_python_at_least_311 "$candidate"; then
            HOOKS_DAEMON_PYTHON="$(command -v "$candidate")"
            export HOOKS_DAEMON_PYTHON
            _ok "Compatible Python found: $HOOKS_DAEMON_PYTHON ($("$HOOKS_DAEMON_PYTHON" --version 2>&1))"
            return 0
        fi
    done

    _fail "No compatible Python (3.11+) found.

Searched (versioned commands only — bare ``python3`` is intentionally not probed
because it is unreliable across distros): ${candidates[*]}

Please install Python 3.11 or higher:
  Ubuntu/Debian: sudo apt-get install python3.11
  macOS: brew install python@3.11
  Fedora: sudo dnf install python3.11
  Arch: sudo pacman -S python

Or set HOOKS_DAEMON_PYTHON to the absolute path of a 3.11+ interpreter:
  HOOKS_DAEMON_PYTHON=/usr/bin/python3.12 ./upgrade.sh ..."
}

# ============================================================
# Main
# ============================================================

echo -e "${_BOLD}Claude Code Hooks Daemon - Upgrade${_NC}"
echo "========================================"

# Step 1: Validate project root
[ -n "$PROJECT_ROOT" ] || _fail "--project-root is required.\nUsage: upgrade.sh --project-root /path/to/project [VERSION]"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)" # Resolve to absolute path
[ -d "$PROJECT_ROOT" ] || _fail "Project root does not exist: $PROJECT_ROOT"
_ok "Project root: $PROJECT_ROOT"

# Step 2: Find compatible Python interpreter (3.11+)
find_compatible_python

# Step 3: Determine daemon directory and mode
DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
SELF_INSTALL="false"
if [ -f "$PROJECT_ROOT/.claude/hooks-daemon.yaml" ] && [ -n "${HOOKS_DAEMON_PYTHON:-}" ]; then
    SELF_INSTALL=$("$HOOKS_DAEMON_PYTHON" -c "
import yaml
try:
    with open('$PROJECT_ROOT/.claude/hooks-daemon.yaml') as f:
        c = yaml.safe_load(f) or {}
    print('true' if c.get('daemon', {}).get('self_install_mode', False) else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo "false")
    if [ "$SELF_INSTALL" = "true" ]; then
        DAEMON_DIR="$PROJECT_ROOT"
    fi
fi

[ -d "$DAEMON_DIR/.git" ] || _fail "Daemon directory is not a git repository: $DAEMON_DIR"
_ok "Daemon directory: $DAEMON_DIR"

# Step 4: Best-effort daemon stop (before checkout)
# Plan 00100 Task 2.5: PID-kill only. The previous implementation resolved a
# venv python just to invoke `daemon.cli stop`, reintroducing the very
# precedence logic the Phase 2 SSOT consolidated. Bootstrap now reads PID
# files directly so zero venv / Python resolution is needed here.
#
# Contract (pinned by tests/integration/test_upgrade_sh_stop_bootstrap.py):
#   - SIGTERM every PID listed in $DAEMON_DIR/untracked/daemon-*.pid
#   - Skip missing/empty/non-numeric/stale PID files silently
#   - Skip missing untracked/ directory silently
#   - Never invoke python, python3, or daemon.cli
_stop_running_daemons() {
    local daemon_dir="$1"
    local untracked="$daemon_dir/untracked"
    [ -d "$untracked" ] || return 0

    local pid_file pid_raw pid
    local any_killed=0
    for pid_file in "$untracked"/daemon-*.pid; do
        [ -f "$pid_file" ] || continue
        if ! pid_raw=$(tr -d '[:space:]' < "$pid_file" 2> /dev/null); then
            continue
        fi
        pid="$pid_raw"
        # Require a pure positive integer; skip empty / garbage / stale.
        case "$pid" in
            '' | *[!0-9]*) continue ;;
        esac
        if kill -0 "$pid" 2> /dev/null; then
            if kill -TERM "$pid" 2> /dev/null; then
                any_killed=1
            fi
        fi
    done
    # Give terminated daemons a moment to shut sockets before checkout runs.
    [ "$any_killed" -eq 1 ] && sleep 1
    return 0
}

_info "Stopping daemon (best-effort, PID-only)..."
_stop_running_daemons "$DAEMON_DIR"

# Step 5: Fetch tags and determine target version
_info "Fetching latest tags..."
git -C "$DAEMON_DIR" fetch --tags --quiet

if [ -z "$TARGET_VERSION" ]; then
    TARGET_VERSION=$(git -C "$DAEMON_DIR" describe --tags \
        "$(git -C "$DAEMON_DIR" rev-list --tags --max-count=1)" 2>/dev/null || echo "")
    if [ -z "$TARGET_VERSION" ]; then
        _fail "No tags found. Specify a version explicitly."
    fi
fi

# Normalise version: prepend 'v' if missing
if [[ -n "$TARGET_VERSION" && ! "$TARGET_VERSION" =~ ^v ]]; then
    TARGET_VERSION="v${TARGET_VERSION}"
fi

git -C "$DAEMON_DIR" rev-parse "$TARGET_VERSION" &>/dev/null || \
    _fail "Version $TARGET_VERSION not found"
_ok "Target version: $TARGET_VERSION"

# Step 6: Checkout target version FIRST (before looking for Layer 2)
_info "Checking out $TARGET_VERSION..."
git -C "$DAEMON_DIR" checkout "$TARGET_VERSION" --quiet
_ok "Checked out $TARGET_VERSION"

# Step 7: Clean up nested install artifacts
# When daemon repo has .claude/ in git (self-install dogfooding), normal installs
# can end up with runtime artifacts at the wrong path:
#   .claude/hooks-daemon/.claude/hooks-daemon/untracked/ (socket, pid, log files)
# This is a nested install artifact, not a legitimate directory.
if [ "$SELF_INSTALL" != "true" ]; then
    NESTED_INSTALL="$DAEMON_DIR/.claude/hooks-daemon"
    if [ -d "$NESTED_INSTALL" ]; then
        _warn "Cleaning up nested install artifacts: $NESTED_INSTALL"
        rm -rf "$NESTED_INSTALL"
        _ok "Nested install artifacts removed"
    fi
fi

# Step 8: Delegate to Layer 2 (now available after checkout)
LAYER2_SCRIPT="$DAEMON_DIR/scripts/upgrade_version.sh"

if [ -f "$LAYER2_SCRIPT" ]; then
    _info "Delegating to version-specific upgrader..."
    exec bash "$LAYER2_SCRIPT" "$PROJECT_ROOT" "$DAEMON_DIR" "$TARGET_VERSION"
else
    _fail "Layer 2 upgrader not found at: $LAYER2_SCRIPT
Target version $TARGET_VERSION does not include the upgrade system.
Use a fresh install instead: see CLAUDE/LLM-INSTALL.md"
fi
