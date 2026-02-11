#!/bin/bash
#
# Claude Code Hooks Daemon - One-Line Installer (Layer 1)
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/install.sh -o /tmp/hooks-daemon-install.sh && bash /tmp/hooks-daemon-install.sh
#
# This is a minimal Layer 1 script that:
# 1. Validates project root (.claude and .git must exist)
# 2. Clones daemon repository to .claude/hooks-daemon/
# 3. Delegates to Layer 2 (scripts/install_version.sh) for full setup
# 4. Falls back to legacy install.py if Layer 2 not available
#
# Environment variables:
#   DAEMON_BRANCH - Git branch/tag to install (default: main)
#   FORCE         - Set to "true" to reinstall over existing installation
#

set -euo pipefail

# Configuration
DAEMON_REPO="https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git"
DAEMON_BRANCH="${DAEMON_BRANCH:-main}"
FORCE="${FORCE:-false}"

# Minimal output functions (can't source library before clone)
if [ -t 1 ]; then
    _RED='\033[0;31m'; _GREEN='\033[0;32m'; _YELLOW='\033[1;33m'
    _BLUE='\033[0;34m'; _NC='\033[0m'
else
    _RED=''; _GREEN=''; _YELLOW=''; _BLUE=''; _NC=''
fi

_ok()   { echo -e "${_GREEN}OK${_NC} $1"; }
_err()  { echo -e "${_RED}ERR${_NC} $1" >&2; }
_warn() { echo -e "${_YELLOW}WARN${_NC} $1"; }
_info() { echo -e "${_BLUE}>>>${_NC} $1"; }
_fail() { _err "$1"; echo ""; echo "Installation aborted."; exit 1; }

# ============================================================
# Main
# ============================================================

echo ""
echo "============================================================"
echo " Claude Code Hooks Daemon - Installer"
echo "============================================================"
echo ""

PROJECT_ROOT="$(pwd)"
DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"

# Step 1: Minimal prerequisites (git required for clone)
_info "Checking prerequisites..."
command -v git &>/dev/null || _fail "git is not installed. Please install git first."
_ok "git found"

# Step 2: Validate project root
_info "Validating project root..."
[ -d ".claude" ] || _fail "No .claude directory found. Run from a Claude Code project root."
[ -d ".git" ]    || _fail "No .git directory found. Run from a git repository root."
_ok "Project root: $PROJECT_ROOT"

# Step 3: Clone daemon repository
_info "Checking daemon installation..."
if [ -d "$DAEMON_DIR" ]; then
    if [ "$FORCE" = "true" ]; then
        _warn "Removing existing installation (FORCE=true)..."
        rm -rf "$DAEMON_DIR"
    else
        _err "Daemon already installed at $DAEMON_DIR"
        echo ""
        echo "To reinstall: curl -sSL <url> | FORCE=true bash"
        echo "Or remove:    rm -rf $DAEMON_DIR"
        exit 1
    fi
fi

_info "Cloning from $DAEMON_REPO (branch: $DAEMON_BRANCH)..."
if ! git clone --branch "$DAEMON_BRANCH" --depth 1 "$DAEMON_REPO" "$DAEMON_DIR" >/dev/null 2>&1; then
    _fail "Failed to clone daemon repository"
fi
_ok "Daemon cloned to $DAEMON_DIR"

# Step 4: Delegate to Layer 2 (with fallback to legacy)
LAYER2_SCRIPT="$DAEMON_DIR/scripts/install_version.sh"

if [ -f "$LAYER2_SCRIPT" ]; then
    _info "Delegating to version-specific installer..."
    exec bash "$LAYER2_SCRIPT" "$PROJECT_ROOT" "$DAEMON_DIR"
else
    # Fallback: legacy install flow for older tags without Layer 2
    _warn "Layer 2 installer not found (older version). Using legacy flow..."

    # Legacy: install dependencies
    _info "Installing dependencies with uv..."
    if command -v uv &>/dev/null || {
        curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
        export PATH="$HOME/.local/bin:$PATH"
        command -v uv &>/dev/null
    }; then
        cd "$DAEMON_DIR"
        mkdir -p untracked
        echo "/untracked/" > untracked/.gitignore
        UV_PROJECT_ENVIRONMENT="$(pwd)/untracked/venv" uv sync --project . >/dev/null 2>&1 || true
        cd - >/dev/null
    fi

    # Legacy: run install.py
    if [ -f "$DAEMON_DIR/install.py" ]; then
        _info "Running legacy installer (install.py)..."
        python3 "$DAEMON_DIR/install.py" --force
    else
        _fail "No installer found in cloned repository"
    fi
fi
