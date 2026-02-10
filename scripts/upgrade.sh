#!/bin/bash
#
# Claude Code Hooks Daemon - Self-Locating Upgrade Script (Layer 1)
#
# SECURITY: Always fetch the latest version from GitHub before running:
#   curl -fsSL https://raw.githubusercontent.com/.../scripts/upgrade.sh -o /tmp/upgrade.sh
#   less /tmp/upgrade.sh   # Review contents
#   bash /tmp/upgrade.sh   # Execute
#
# This is a minimal Layer 1 script that:
# 1. Detects project root (walks up directory tree)
# 2. Determines current and target versions
# 3. Delegates to Layer 2 (scripts/upgrade_version.sh) for full upgrade
# 4. Falls back to legacy inline upgrade if Layer 2 not available
#
# Arguments:
#   VERSION - Git tag to upgrade to (optional, defaults to latest tag)
#

set -euo pipefail

TARGET_VERSION="${1:-}"

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
# Main
# ============================================================

echo -e "${_BOLD}Claude Code Hooks Daemon - Upgrade${_NC}"
echo "========================================"

# Step 1: Detect project root
_info "Detecting project root..."
PROJECT_ROOT=""
SEARCH_DIR="$(pwd)"
# Primary signal: config file exists (ideal state)
while [ "$SEARCH_DIR" != "/" ]; do
    if [ -f "$SEARCH_DIR/.claude/hooks-daemon.yaml" ]; then
        PROJECT_ROOT="$SEARCH_DIR"
        break
    fi
    SEARCH_DIR="$(dirname "$SEARCH_DIR")"
done
# Fallback signal: daemon repo exists but config missing (broken install)
if [ -z "$PROJECT_ROOT" ]; then
    SEARCH_DIR="$(pwd)"
    while [ "$SEARCH_DIR" != "/" ]; do
        if [ -d "$SEARCH_DIR/.claude/hooks-daemon/.git" ]; then
            PROJECT_ROOT="$SEARCH_DIR"
            _warn "Config file missing - will be repaired during upgrade"
            break
        fi
        SEARCH_DIR="$(dirname "$SEARCH_DIR")"
    done
fi

[ -n "$PROJECT_ROOT" ] || _fail "Could not find project root (no .claude/hooks-daemon.yaml or .claude/hooks-daemon/.git in any parent directory)"
_ok "Project root: $PROJECT_ROOT"

# Step 2: Determine daemon directory and mode
DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
if [ -f "$PROJECT_ROOT/.claude/hooks-daemon.yaml" ] && command -v python3 &>/dev/null; then
    SELF_INSTALL=$(python3 -c "
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

# Step 3: Fetch tags and determine target version
_info "Fetching latest tags..."
git -C "$DAEMON_DIR" fetch --tags --quiet

if [ -z "$TARGET_VERSION" ]; then
    TARGET_VERSION=$(git -C "$DAEMON_DIR" describe --tags \
        "$(git -C "$DAEMON_DIR" rev-list --tags --max-count=1)" 2>/dev/null || echo "")
    if [ -z "$TARGET_VERSION" ]; then
        _warn "No tags found. Using main branch."
        TARGET_VERSION="main"
    fi
fi

# Verify target exists
git -C "$DAEMON_DIR" rev-parse "$TARGET_VERSION" &>/dev/null || \
    _fail "Version $TARGET_VERSION not found"
_ok "Target version: $TARGET_VERSION"

# Step 4: Delegate to Layer 2 (with fallback to legacy)
LAYER2_SCRIPT="$DAEMON_DIR/scripts/upgrade_version.sh"

if [ -f "$LAYER2_SCRIPT" ]; then
    _info "Delegating to version-specific upgrader..."
    exec bash "$LAYER2_SCRIPT" "$PROJECT_ROOT" "$DAEMON_DIR" "$TARGET_VERSION"
else
    # Fallback: legacy inline upgrade for older versions
    _warn "Layer 2 upgrader not found. Using legacy upgrade flow..."

    VENV_PYTHON="$DAEMON_DIR/untracked/venv/bin/python"

    # Stop daemon
    _info "Stopping daemon..."
    [ -f "$VENV_PYTHON" ] && "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
    sleep 1

    # Checkout target
    _info "Checking out $TARGET_VERSION..."
    git -C "$DAEMON_DIR" checkout "$TARGET_VERSION" --quiet

    # Reinstall
    VENV_PIP="$(dirname "$VENV_PYTHON")/pip"
    if [ -f "$VENV_PIP" ]; then
        _info "Installing package..."
        "$VENV_PIP" install -e "$DAEMON_DIR" --quiet
    fi

    # Restart daemon
    _info "Restarting daemon..."
    "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli start 2>/dev/null || true
    sleep 1
    "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli status 2>&1 || true

    echo ""
    _ok "Legacy upgrade complete. Restart Claude Code to activate."
fi
