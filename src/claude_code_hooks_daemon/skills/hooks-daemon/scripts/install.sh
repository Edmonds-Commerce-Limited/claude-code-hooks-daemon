#!/bin/bash
#
# install.sh - Install hooks daemon into current project
#
# Usage:
#   ./install.sh [--force]
#
# Arguments:
#   --force (optional): Force reinstall over existing installation
#

set -euo pipefail

GITHUB_ORG="Edmonds-Commerce-Limited"
GITHUB_REPO="claude-code-hooks-daemon"
INSTALL_URL="https://raw.githubusercontent.com/${GITHUB_ORG}/${GITHUB_REPO}/main/install.sh"

# Detect project root by searching upward for .claude/
PROJECT_ROOT="$(pwd)"
while [ "$PROJECT_ROOT" != "/" ]; do
    if [ -d "$PROJECT_ROOT/.claude" ]; then
        break
    fi
    PROJECT_ROOT="$(dirname "$PROJECT_ROOT")"
done

if [ ! -d "$PROJECT_ROOT/.claude" ]; then
    echo "Error: Not in a Claude Code project (no .claude/ directory found)"
    echo ""
    echo "The hooks daemon must be installed in a project that has Claude Code configured."
    echo "Ensure you are in a project directory with a .claude/ folder."
    exit 1
fi

DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
FORCE_FLAG="${1:-}"

echo "Claude Code Hooks Daemon - Install"
echo ""
echo "Project: $PROJECT_ROOT"
echo ""

# Check if already installed
if [ -d "$DAEMON_DIR" ] && [ "$FORCE_FLAG" != "--force" ]; then
    echo "Daemon is already installed at: $DAEMON_DIR"
    echo ""
    echo "To upgrade to a new version:"
    echo "  /hooks-daemon upgrade"
    echo ""
    echo "To force reinstall:"
    echo "  /hooks-daemon install --force"
    exit 0
fi

# Download installer to temp file (never pipe curl to shell — we block that pattern)
INSTALLER="/tmp/hooks-daemon-install.sh"
echo "Downloading installer..."
echo "  URL: $INSTALL_URL"
curl -sSL "$INSTALL_URL" -o "$INSTALLER"

if [ ! -s "$INSTALLER" ]; then
    echo ""
    echo "Error: Failed to download installer (empty file)"
    echo "Check your network connection and try again."
    exit 1
fi

INSTALLER_SIZE=$(wc -c < "$INSTALLER")
echo "  Downloaded: ${INSTALLER_SIZE} bytes"
echo ""

# Run installer from project root
echo "Running installer..."
echo ""
cd "$PROJECT_ROOT"

if [ "$FORCE_FLAG" = "--force" ]; then
    FORCE=true bash "$INSTALLER"
else
    bash "$INSTALLER"
fi
