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
# Plan 00100 Task 0.3: daemon's requires-python is the single source of truth
# for minimum Python. Fetched from the repo's pyproject.toml below and used
# to pre-check the active python3 BEFORE the installer runs.
PYPROJECT_URL="https://raw.githubusercontent.com/${GITHUB_ORG}/${GITHUB_REPO}/main/pyproject.toml"

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

# Plan 00100 Task 0.3: Python version pre-check BEFORE download & install.
# Fetch the daemon's pyproject.toml to parse requires-python (single source
# of truth). If the active python3 is too old, emit an actionable
# HOOKS_DAEMON_PYTHON hint and exit WITHOUT downloading the installer.
PYPROJECT_TMP="/tmp/hooks-daemon-precheck-pyproject.toml.$$"
if curl -sSL "$PYPROJECT_URL" -o "$PYPROJECT_TMP" && [ -s "$PYPROJECT_TMP" ]; then
    REQ_LINE="$(grep -E '^requires-python\s*=' "$PYPROJECT_TMP" || echo '')"
    if [ -n "$REQ_LINE" ]; then
        MIN_PY="$(echo "$REQ_LINE" | grep -oE '[0-9]+\.[0-9]+' | head -n 1)"
        ACTIVE_PY_CMD="${HOOKS_DAEMON_PYTHON:-python3}"
        if [ -n "$MIN_PY" ] && command -v "$ACTIVE_PY_CMD" >/dev/null; then
            ACTIVE_PY_VER="$("$ACTIVE_PY_CMD" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
            MIN_MAJOR="${MIN_PY%.*}"; MIN_MINOR="${MIN_PY#*.}"
            ACT_MAJOR="${ACTIVE_PY_VER%.*}"; ACT_MINOR="${ACTIVE_PY_VER#*.}"
            if [ "$ACT_MAJOR" -lt "$MIN_MAJOR" ] || { [ "$ACT_MAJOR" -eq "$MIN_MAJOR" ] && [ "$ACT_MINOR" -lt "$MIN_MINOR" ]; }; then
                echo "Error: Active python3 is $ACTIVE_PY_VER but daemon requires >=$MIN_PY (from pyproject.toml:requires-python)"
                echo ""
                echo "Retry with a compatible interpreter:"
                echo "  HOOKS_DAEMON_PYTHON=python${MIN_PY} /hooks-daemon install"
                rm -f "$PYPROJECT_TMP"
                exit 1
            fi
        fi
    fi
    rm -f "$PYPROJECT_TMP"
fi

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
