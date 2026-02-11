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
# find_compatible_python() - Find a Python 3.11+ interpreter
#
# Checks python3, then searches for python3.13, python3.12, python3.11 in PATH.
# Sets and exports HOOKS_DAEMON_PYTHON so Layer 2 scripts can use it.
#
# Returns:
#   0 - compatible Python found (HOOKS_DAEMON_PYTHON exported)
#   1 - no compatible Python found (exits via _fail)
#
find_compatible_python() {
    local candidates=("python3" "python3.13" "python3.12" "python3.11")
    local candidate

    for candidate in "${candidates[@]}"; do
        if command -v "$candidate" &>/dev/null; then
            if "$candidate" -c 'import sys; v=sys.version_info; exit(0 if v >= (3,11) else 1)' 2>/dev/null; then
                HOOKS_DAEMON_PYTHON="$(command -v "$candidate")"
                export HOOKS_DAEMON_PYTHON
                _ok "Compatible Python found: $HOOKS_DAEMON_PYTHON ($("$HOOKS_DAEMON_PYTHON" --version 2>&1))"
                return 0
            fi
        fi
    done

    _fail "No compatible Python (3.11+) found.

Searched for: ${candidates[*]}

Please install Python 3.11 or higher:
  Ubuntu/Debian: sudo apt-get install python3.11
  macOS: brew install python@3.11
  Fedora: sudo dnf install python3.11
  Arch: sudo pacman -S python"
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
VENV_PYTHON="$DAEMON_DIR/untracked/venv/bin/python"
if [ -f "$VENV_PYTHON" ]; then
    _info "Stopping daemon..."
    "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
    sleep 1
fi

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
