#!/bin/bash
#
# Claude Code Hooks Daemon - Self-Locating Upgrade Script
#
# 🚨 CRITICAL SECURITY WARNING 🚨
#
# NEVER run this script directly from your local git checkout!
# ALWAYS fetch the latest version from the live repository using curl,
# save it to a temporary file, READ IT IN FULL to verify contents,
# then execute it.
#
# WHY THIS MATTERS:
# - Local version may be outdated or modified
# - Live repo version includes latest security fixes
# - Reading full script allows security review before execution
#
# CORRECT USAGE:
#   # Step 1: Fetch latest script from GitHub
#   curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/scripts/upgrade.sh -o /tmp/upgrade.sh
#
#   # Step 2: CRITICAL - Read the entire script to verify it's safe
#   less /tmp/upgrade.sh
#   # (or use: cat /tmp/upgrade.sh)
#
#   # Step 3: Only after reading and verifying, execute it
#   bash /tmp/upgrade.sh
#
# ========================================
#
# Automatically detects project root and performs a complete upgrade.
# Can be run from any directory within the project tree.
#
# Arguments:
#   VERSION - Git tag to upgrade to (e.g., v2.5.0)
#             If omitted, upgrades to the latest tagged release.
#
# Exit codes:
#   0 - Upgrade completed successfully
#   1 - Upgrade failed (rollback attempted)
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

# Step 2: Pre-upgrade safety checks (for client projects only)
log_step "2" "Running pre-upgrade safety checks"

if [ "$SELF_INSTALL" = "false" ]; then
    echo "Running client installation safety checks..."

    # Check if venv exists before running checks
    if [ ! -f "$VENV_PYTHON" ]; then
        echo -e "${YELLOW}Venv not found yet - skipping pre-upgrade checks${NC}"
        echo "Safety checks will run after venv is created."
    else
        # Run Python validator using venv Python (not system python3)
        VALIDATION_SCRIPT=$(cat <<PYTHON_EOF
import sys
from pathlib import Path

# Add src to path
daemon_dir = Path("$HOOKS_DAEMON_DIR")
sys.path.insert(0, str(daemon_dir / "src"))

try:
    from claude_code_hooks_daemon.install import ClientInstallValidator

    # Run cleanup of stale runtime files
    result = ClientInstallValidator.cleanup_stale_runtime_files(Path("$PROJECT_ROOT"))
    for warning in result.warnings:
        print(f"  {warning}")

    # Check existing config
    result = ClientInstallValidator._check_existing_config(Path("$PROJECT_ROOT"))
    for warning in result.warnings:
        print(f"⚠️  {warning}")

    if not result.passed:
        for error in result.errors:
            print(f"❌ {error}", file=sys.stderr)
        sys.exit(1)

    print("✅ Pre-upgrade checks passed")
except Exception as e:
    print(f"⚠️  Warning: Could not run safety checks: {e}", file=sys.stderr)
    # Don't fail upgrade if validator can't run (might be old version)
PYTHON_EOF
)

        if ! "$VENV_PYTHON" -c "$VALIDATION_SCRIPT"; then
            echo -e "${RED}Pre-upgrade validation failed${NC}"
            echo "Please fix the issues above before upgrading."
            exit 1
        fi
    fi
else
    echo "Self-install mode - skipping client safety checks"
fi

# Step 3: Check current version and backup config
log_step "3" "Checking current version and backing up config"

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

# Backup config with timestamp
CONFIG_FILE="$PROJECT_ROOT/.claude/hooks-daemon.yaml"
if [ -f "$CONFIG_FILE" ]; then
    TIMESTAMP=$(date +%Y%m%d-%H%M%S)
    CONFIG_BACKUP="${CONFIG_FILE}.backup-${TIMESTAMP}"
    cp "$CONFIG_FILE" "$CONFIG_BACKUP"
    echo -e "${GREEN}Config backed up to: $CONFIG_BACKUP${NC}"
else
    echo -e "${YELLOW}No config file found at $CONFIG_FILE${NC}"
fi

# Step 4: Fetch and checkout target version
log_step "4" "Fetching latest tags and checking out target version"

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

SKIP_UPGRADE=false
if [ "$ROLLBACK_TAG" = "$NEW_VERSION" ]; then
    echo -e "${GREEN}Already at version $NEW_VERSION.${NC}"
    echo "Skipping code checkout, jumping to daemon validation..."
    SKIP_UPGRADE=true
    # Clear rollback state since we're not changing anything
    ROLLBACK_TAG=""
fi

if [ "$SKIP_UPGRADE" = false ]; then
    # Stop daemon before checkout (prevents file conflicts)
    echo "Stopping daemon..."
    if [ -f "$VENV_PYTHON" ]; then
        "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
    fi

    # Checkout target version
    echo "Checking out $NEW_VERSION..."
    git -C "$HOOKS_DAEMON_DIR" checkout "$NEW_VERSION" --quiet

    # Step 5: Install dependencies
    log_step "5" "Installing dependencies"

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

    # Update slash commands (if available)
    echo "Updating slash commands..."
    COMMANDS_DIR="$PROJECT_ROOT/.claude/commands"
    mkdir -p "$COMMANDS_DIR"

    SOURCE_CMD="$HOOKS_DAEMON_DIR/.claude/commands/hooks-daemon-update.md"
    DEST_CMD="$COMMANDS_DIR/hooks-daemon-update.md"

    if [ -f "$SOURCE_CMD" ]; then
        if [ "$SELF_INSTALL" = "true" ]; then
            # Self-install mode: create symlink
            if [ -L "$DEST_CMD" ] || [ -f "$DEST_CMD" ]; then
                rm -f "$DEST_CMD"
            fi
            ln -s "$SOURCE_CMD" "$DEST_CMD"
            echo -e "${GREEN}Symlinked /hooks-daemon-update command${NC}"
        else
            # Normal mode: copy file
            cp "$SOURCE_CMD" "$DEST_CMD"
            echo -e "${GREEN}Updated /hooks-daemon-update command${NC}"
        fi
    else
        echo -e "${YELLOW}Slash command not found (older version)${NC}"
    fi
fi  # End of SKIP_UPGRADE=false block

# Step 6: Restart daemon and verify config (ALWAYS RUN)
log_step "6" "Restarting daemon and validating config"

echo "Stopping daemon..."
"$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true

# Brief pause
sleep 1

echo "Starting daemon..."
"$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli start 2>/dev/null || true

# Brief pause for startup
sleep 1

# Check daemon status (DO NOT silence errors - we need to see config validation failures)
echo "Checking daemon status..."
STATUS_OUTPUT=$("$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli status 2>&1)
STATUS_EXIT_CODE=$?

if [ $STATUS_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ Daemon started successfully${NC}"
    echo "$STATUS_OUTPUT"
else
    echo -e "${RED}❌ Daemon failed to start - Config validation errors detected${NC}"
    echo ""
    echo "$STATUS_OUTPUT"
    echo ""
    echo -e "${YELLOW}${BOLD}⚠️  CONFIGURATION MIGRATION REQUIRED${NC}"
    echo "================================================"
    echo ""
    echo "The daemon configuration has validation errors (see above)."
    echo "This typically means config settings changed between versions."
    echo ""
    echo "TO FIX: Ask your project's Claude agent to fix the config:"
    echo ""
    echo "  1. Show Claude the error messages above"
    echo "  2. Ask: 'Fix my hooks-daemon config based on these errors'"
    echo "  3. Claude will read release notes at:"
    echo "     $HOOKS_DAEMON_DIR/RELEASES/v${NEW_VERSION}.md"
    echo "  4. Claude will update .claude/hooks-daemon.yaml automatically"
    echo ""
    echo "Config backup available at: ${CONFIG_BACKUP:-none}"
    echo ""
    echo "After Claude fixes config, restart daemon:"
    echo "  $VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart"
    echo ""
    exit 1
fi

# Step 7: Verify new version
log_step "7" "Verifying upgrade"

NEW_ACTUAL_VERSION=""
if [ -f "$VERSION_FILE" ]; then
    NEW_ACTUAL_VERSION=$("$VENV_PYTHON" -c "
from claude_code_hooks_daemon.version import __version__
print(__version__)
" 2>/dev/null || echo "unknown")
fi

# Step 8: Post-upgrade verification (for client projects only)
if [ "$SELF_INSTALL" = "false" ]; then
    log_step "8" "Running post-upgrade verification"

    VALIDATION_SCRIPT=$(cat <<PYTHON_EOF
import sys
from pathlib import Path

# Add src to path
daemon_dir = Path("$HOOKS_DAEMON_DIR")
sys.path.insert(0, str(daemon_dir / "src"))

try:
    from claude_code_hooks_daemon.install import ClientInstallValidator

    # Verify config is valid
    result = ClientInstallValidator._verify_config_valid(Path("$PROJECT_ROOT"))
    if not result.passed:
        for error in result.errors:
            print(f"❌ {error}", file=sys.stderr)
        sys.exit(1)

    # CRITICAL: Verify no self_install_mode in config
    result = ClientInstallValidator._verify_no_self_install_mode(Path("$PROJECT_ROOT"))
    if not result.passed:
        for error in result.errors:
            print(f"❌ {error}", file=sys.stderr)
        sys.exit(1)

    for warning in result.warnings:
        print(f"⚠️  {warning}")

    print("✅ Post-upgrade verification passed")
except Exception as e:
    print(f"⚠️  Warning: Could not run post-upgrade checks: {e}", file=sys.stderr)
    # Don't fail if verification can't run
PYTHON_EOF
)

    if ! "$VENV_PYTHON" -c "$VALIDATION_SCRIPT"; then
        echo -e "${RED}Post-upgrade verification failed${NC}"
        echo "Upgrade completed but configuration validation failed."
        echo "Please check the errors above."
        exit 1
    fi
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

echo -e "${YELLOW}${BOLD}⚠️  IMPORTANT: Restart Claude Code Now${NC}"
echo "========================================"
echo ""
echo "The daemon has been upgraded and restarted, but Claude Code CLI"
echo "still has the OLD hook script versions loaded in memory."
echo ""
echo "To activate the upgraded hooks, you MUST restart Claude Code:"
echo ""
echo "  1. Exit your current Claude Code session completely"
echo "  2. Start a new Claude Code session"
echo ""
echo "Until you restart, hooks will use the old versions and may behave incorrectly."
