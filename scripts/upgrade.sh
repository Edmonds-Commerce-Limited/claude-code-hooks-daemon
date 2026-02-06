#!/bin/bash
#
# Claude Code Hooks Daemon - Self-Locating Upgrade Script
#
# Automatically detects project root and performs a complete upgrade.
# Can be run from any directory within the project tree.
#
# Usage:
#   ./scripts/upgrade.sh [VERSION]
#   .claude/hooks-daemon/scripts/upgrade.sh [VERSION]
#
# Arguments:
#   VERSION - Git tag to upgrade to (e.g., v2.5.0)
#             If omitted, upgrades to the latest tagged release.
#
# Exit codes:
#   0 - Upgrade completed successfully
#   1 - Upgrade failed (rollback attempted)
#
# Examples:
#   ./scripts/upgrade.sh              # Upgrade to latest
#   ./scripts/upgrade.sh v2.5.0       # Upgrade to specific version
#

set -euo pipefail

# Colors for output (only when stdout is a terminal)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    CYAN=''
    BOLD=''
    NC=''
fi

# Target version (optional argument)
TARGET_VERSION="${1:-}"

# Rollback state
ROLLBACK_TAG=""
CONFIG_BACKUP=""
HOOKS_DAEMON_DIR=""
VENV_PYTHON=""

#
# cleanup() - Attempt rollback on failure
#
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ] && [ -n "$ROLLBACK_TAG" ] && [ -n "$HOOKS_DAEMON_DIR" ]; then
        echo ""
        echo -e "${YELLOW}Attempting rollback to $ROLLBACK_TAG...${NC}"

        if git -C "$HOOKS_DAEMON_DIR" checkout "$ROLLBACK_TAG" 2>/dev/null; then
            echo -e "${GREEN}Rolled back to $ROLLBACK_TAG${NC}"

            # Reinstall previous version
            if [ -n "$VENV_PYTHON" ] && [ -f "$VENV_PYTHON" ]; then
                local venv_pip
                venv_pip="$(dirname "$VENV_PYTHON")/pip"
                if [ -f "$venv_pip" ]; then
                    "$venv_pip" install -e "$HOOKS_DAEMON_DIR" --quiet 2>/dev/null || true
                fi
            fi
        else
            echo -e "${RED}Rollback failed. Manual intervention required.${NC}"
            echo "Previous version was: $ROLLBACK_TAG"
        fi

        # Restore config backup if it exists
        if [ -n "$CONFIG_BACKUP" ] && [ -f "$CONFIG_BACKUP" ]; then
            local config_file
            config_file="$(dirname "$CONFIG_BACKUP")/hooks-daemon.yaml"
            cp "$CONFIG_BACKUP" "$config_file"
            echo -e "${GREEN}Restored config backup${NC}"
        fi
    fi
}
trap cleanup EXIT

#
# log_step() - Print a numbered step
#
log_step() {
    local step="$1"
    local message="$2"
    echo ""
    echo -e "${BOLD}Step $step: $message${NC}"
    echo "----------------------------------------"
}

#
# detect_project_root() - Walk up directory tree to find project root
#
detect_project_root() {
    local dir
    dir="$(pwd)"

    while [ "$dir" != "/" ]; do
        if [ -f "$dir/.claude/hooks-daemon.yaml" ]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done

    return 1
}

#
# Main upgrade logic
#

echo -e "${BOLD}Claude Code Hooks Daemon - Upgrade${NC}"
echo "========================================"

# Step 1: Detect project root
log_step "1" "Detecting project root"

PROJECT_ROOT=""
if ! PROJECT_ROOT=$(detect_project_root); then
    echo -e "${RED}Could not find project root.${NC}"
    echo "No .claude/hooks-daemon.yaml found in any parent directory."
    echo "Current directory: $(pwd)"
    exit 1
fi

echo "Project root: $PROJECT_ROOT"

# Determine installation mode
SELF_INSTALL="false"
if command -v python3 &>/dev/null && [ -f "$PROJECT_ROOT/.claude/hooks-daemon.yaml" ]; then
    SELF_INSTALL=$(python3 -c "
import yaml
try:
    with open('$PROJECT_ROOT/.claude/hooks-daemon.yaml') as f:
        config = yaml.safe_load(f) or {}
    print('true' if config.get('daemon', {}).get('self_install_mode', False) else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo "false")
fi

if [ "$SELF_INSTALL" = "true" ]; then
    HOOKS_DAEMON_DIR="$PROJECT_ROOT"
    VENV_PYTHON="$PROJECT_ROOT/untracked/venv/bin/python"
    echo "Mode: self-install (development)"
else
    HOOKS_DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
    VENV_PYTHON="$HOOKS_DAEMON_DIR/untracked/venv/bin/python"
    echo "Mode: normal installation"
fi

echo "Daemon directory: $HOOKS_DAEMON_DIR"

# Validate hooks-daemon directory
if [ ! -d "$HOOKS_DAEMON_DIR/.git" ]; then
    echo -e "${RED}Hooks daemon directory is not a git repository: $HOOKS_DAEMON_DIR${NC}"
    exit 1
fi

# Step 2: Check current version and backup config
log_step "2" "Checking current version and backing up config"

# Get current version
CURRENT_VERSION=""
VERSION_FILE="$HOOKS_DAEMON_DIR/src/claude_code_hooks_daemon/version.py"
if [ -f "$VERSION_FILE" ]; then
    CURRENT_VERSION=$(python3 -c "
with open('$VERSION_FILE') as f:
    content = f.read()
for line in content.split('\n'):
    if '__version__' in line:
        print(line.split('\"')[1])
        break
" 2>/dev/null || echo "unknown")
fi

# Get current git ref for rollback
ROLLBACK_TAG=$(git -C "$HOOKS_DAEMON_DIR" describe --tags --exact-match 2>/dev/null || \
               git -C "$HOOKS_DAEMON_DIR" rev-parse --short HEAD 2>/dev/null || \
               echo "")

echo "Current version: ${CURRENT_VERSION:-unknown}"
echo "Current git ref: ${ROLLBACK_TAG:-unknown}"

# Backup config
CONFIG_FILE="$PROJECT_ROOT/.claude/hooks-daemon.yaml"
if [ -f "$CONFIG_FILE" ]; then
    CONFIG_BACKUP="${CONFIG_FILE}.upgrade-backup"
    cp "$CONFIG_FILE" "$CONFIG_BACKUP"
    echo -e "${GREEN}Config backed up to: $CONFIG_BACKUP${NC}"
else
    echo -e "${YELLOW}No config file found at $CONFIG_FILE${NC}"
fi

# Step 3: Fetch and checkout target version
log_step "3" "Fetching latest tags and checking out target version"

git -C "$HOOKS_DAEMON_DIR" fetch --tags --quiet

if [ -n "$TARGET_VERSION" ]; then
    # Use specified version
    if ! git -C "$HOOKS_DAEMON_DIR" rev-parse "$TARGET_VERSION" &>/dev/null; then
        echo -e "${RED}Version $TARGET_VERSION not found.${NC}"
        echo "Available versions:"
        git -C "$HOOKS_DAEMON_DIR" tag -l | sort -V | tail -10
        exit 1
    fi
    NEW_VERSION="$TARGET_VERSION"
else
    # Find latest tag
    NEW_VERSION=$(git -C "$HOOKS_DAEMON_DIR" describe --tags \
        "$(git -C "$HOOKS_DAEMON_DIR" rev-list --tags --max-count=1)" 2>/dev/null || echo "")

    if [ -z "$NEW_VERSION" ]; then
        echo -e "${YELLOW}No tags found. Using main branch.${NC}"
        NEW_VERSION="main"
    fi
fi

echo "Target version: $NEW_VERSION"

if [ "$ROLLBACK_TAG" = "$NEW_VERSION" ]; then
    echo -e "${GREEN}Already at version $NEW_VERSION. Nothing to upgrade.${NC}"
    # Clear rollback state since we did not change anything
    ROLLBACK_TAG=""
    exit 0
fi

# Stop daemon before checkout (prevents file conflicts)
echo "Stopping daemon..."
if [ -f "$VENV_PYTHON" ]; then
    "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
fi

# Checkout target version
echo "Checking out $NEW_VERSION..."
git -C "$HOOKS_DAEMON_DIR" checkout "$NEW_VERSION" --quiet

# Step 4: Install dependencies
log_step "4" "Installing dependencies"

VENV_PIP="$(dirname "$VENV_PYTHON")/pip"

if [ ! -f "$VENV_PYTHON" ]; then
    echo -e "${YELLOW}Venv not found. Creating...${NC}"
    VENV_DIR="$(dirname "$(dirname "$VENV_PYTHON")")"
    python3 -m venv "$VENV_DIR"
fi

if [ -f "$VENV_PIP" ]; then
    echo "Installing package..."
    "$VENV_PIP" install -e "$HOOKS_DAEMON_DIR" --quiet
    echo -e "${GREEN}Dependencies installed${NC}"
else
    echo -e "${RED}pip not found at $VENV_PIP${NC}"
    exit 1
fi

# Verify import works
echo "Verifying installation..."
if ! "$VENV_PYTHON" -c "import claude_code_hooks_daemon; print('OK')" 2>/dev/null; then
    echo -e "${RED}Import verification failed after install${NC}"
    exit 1
fi
echo -e "${GREEN}Import verification passed${NC}"

# Step 5: Restart daemon and verify
log_step "5" "Restarting daemon"

"$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli restart 2>/dev/null || true

# Brief pause for startup
sleep 1

# Check daemon status
if "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli status 2>/dev/null; then
    echo -e "${GREEN}Daemon restarted successfully${NC}"
else
    echo -e "${YELLOW}Daemon not running after restart.${NC}"
    echo "This may be normal if hooks trigger lazy startup."
    echo "The daemon will start automatically on the next hook call."
fi

# Step 6: Verify new version
log_step "6" "Verifying upgrade"

NEW_ACTUAL_VERSION=""
if [ -f "$VERSION_FILE" ]; then
    NEW_ACTUAL_VERSION=$("$VENV_PYTHON" -c "
from claude_code_hooks_daemon.version import __version__
print(__version__)
" 2>/dev/null || echo "unknown")
fi

echo ""
echo "========================================"
echo -e "${GREEN}${BOLD}Upgrade Complete${NC}"
echo "========================================"
echo ""
echo "  Previous version: ${CURRENT_VERSION:-unknown}"
echo "  Current version:  ${NEW_ACTUAL_VERSION:-$NEW_VERSION}"
echo "  Config backup:    ${CONFIG_BACKUP:-none}"
echo ""

# Check for new handlers
echo "To discover new handlers in this version, run:"
if [ "$SELF_INSTALL" = "true" ]; then
    echo "  $VENV_PYTHON scripts/handler_status.py"
else
    echo "  cd $HOOKS_DAEMON_DIR && $VENV_PYTHON scripts/handler_status.py"
fi
echo ""

# Check for upgrade guides
UPGRADE_DIR="$HOOKS_DAEMON_DIR/CLAUDE/UPGRADES"
if [ -d "$UPGRADE_DIR" ]; then
    echo "Check for version-specific upgrade notes:"
    echo "  ls $UPGRADE_DIR/"
fi
echo ""

# Clear rollback tag on success (prevents cleanup from rolling back)
ROLLBACK_TAG=""

echo -e "${GREEN}No Claude Code session restart needed${NC} (daemon restart is sufficient)."
echo "Exception: Restart Claude Code only if new hook event types were added."
