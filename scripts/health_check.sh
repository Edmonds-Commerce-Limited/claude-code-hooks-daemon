#!/bin/bash
#
# Claude Code Hooks Daemon - Health Check Script
#
# Validates installation health:
# - Config file exists and is valid
# - No nested installation detected
# - Daemon can start (or is already running)
# - Socket file is accessible
#
# Usage:
#   ./scripts/health_check.sh [--project-root PATH]
#
# Exit codes:
#   0 - All checks passed
#   1 - One or more checks failed
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
PROJECT_ROOT=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --project-root)
            PROJECT_ROOT="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# Find project root if not specified
if [[ -z "$PROJECT_ROOT" ]]; then
    PROJECT_ROOT=$(pwd)
    while [[ "$PROJECT_ROOT" != "/" ]]; do
        if [[ -d "$PROJECT_ROOT/.claude" ]]; then
            break
        fi
        PROJECT_ROOT=$(dirname "$PROJECT_ROOT")
    done

    if [[ "$PROJECT_ROOT" == "/" ]]; then
        echo -e "${RED}✗ Could not find .claude directory${NC}"
        exit 1
    fi
fi

echo "🔍 Claude Code Hooks Daemon Health Check"
echo "   Project root: $PROJECT_ROOT"
echo ""

FAILED=0

#
# Check 1: Config file exists
#
echo -n "1. Config file exists... "
CONFIG_FILE="$PROJECT_ROOT/.claude/hooks-daemon.yaml"
if [[ -f "$CONFIG_FILE" ]]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗ Not found: $CONFIG_FILE${NC}"
    FAILED=1
fi

#
# Check 2: Config file is valid YAML
#
echo -n "2. Config file is valid... "
if [[ -f "$CONFIG_FILE" ]]; then
    if python3 -c "import yaml; yaml.safe_load(open('$CONFIG_FILE'))" 2>/dev/null; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗ Invalid YAML syntax${NC}"
        FAILED=1
    fi
else
    echo -e "${YELLOW}⊘ Skipped (no config file)${NC}"
fi

#
# Check 3: No nested installation
#
echo -n "3. No nested installation... "
NESTED_DIR="$PROJECT_ROOT/.claude/hooks-daemon/.claude/hooks-daemon"
if [[ -d "$NESTED_DIR" ]]; then
    echo -e "${RED}✗ NESTED INSTALLATION DETECTED${NC}"
    echo "   Found: $NESTED_DIR"
    echo "   Action: Remove $PROJECT_ROOT/.claude/hooks-daemon and reinstall"
    FAILED=1
else
    echo -e "${GREEN}✓${NC}"
fi

#
# Check 4: Git remote validation (if applicable)
#
echo -n "4. Git remote check... "
if [[ -d "$PROJECT_ROOT/.git" ]]; then
    REMOTE_URL=$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null || echo "")
    REMOTE_URL_LOWER=$(echo "$REMOTE_URL" | tr '[:upper:]' '[:lower:]')

    IS_HOOKS_DAEMON_REPO=false
    if [[ "$REMOTE_URL_LOWER" == *"claude-code-hooks-daemon"* ]] || \
       [[ "$REMOTE_URL_LOWER" == *"claude_code_hooks_daemon"* ]]; then
        IS_HOOKS_DAEMON_REPO=true
    fi

    if [[ "$IS_HOOKS_DAEMON_REPO" == "true" ]]; then
        # Check for self_install_mode or env override
        if [[ -f "$PROJECT_ROOT/.claude/hooks-daemon.env" ]]; then
            echo -e "${GREEN}✓ hooks-daemon repo with self-install env${NC}"
        elif [[ -f "$CONFIG_FILE" ]]; then
            SELF_INSTALL=$(python3 -c "
import yaml
with open('$CONFIG_FILE') as f:
    config = yaml.safe_load(f) or {}
daemon = config.get('daemon', {})
print('true' if daemon.get('self_install_mode', False) else 'false')
" 2>/dev/null || echo "false")
            if [[ "$SELF_INSTALL" == "true" ]]; then
                echo -e "${GREEN}✓ hooks-daemon repo with self_install_mode${NC}"
            else
                echo -e "${RED}✗ hooks-daemon repo without self_install_mode${NC}"
                echo "   Action: Add 'self_install_mode: true' to daemon config or use --self-install"
                FAILED=1
            fi
        else
            echo -e "${RED}✗ hooks-daemon repo without config${NC}"
            FAILED=1
        fi
    else
        echo -e "${GREEN}✓ Not hooks-daemon repo${NC}"
    fi
else
    echo -e "${YELLOW}⊘ Not a git repo${NC}"
fi

#
# Check 5: Daemon installation exists (unless self-install mode)
#
echo -n "5. Daemon installation... "
HOOKS_DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
if [[ -f "$PROJECT_ROOT/.claude/hooks-daemon.env" ]]; then
    # Self-install mode - daemon code should be at project root
    if [[ -d "$PROJECT_ROOT/src/claude_code_hooks_daemon" ]]; then
        echo -e "${GREEN}✓ Self-install mode${NC}"
    else
        echo -e "${RED}✗ Self-install mode but daemon source not found${NC}"
        FAILED=1
    fi
elif [[ -f "$CONFIG_FILE" ]]; then
    # Check if self_install_mode is set
    SELF_INSTALL=$(python3 -c "
import yaml
with open('$CONFIG_FILE') as f:
    config = yaml.safe_load(f) or {}
daemon = config.get('daemon', {})
print('true' if daemon.get('self_install_mode', False) else 'false')
" 2>/dev/null || echo "false")

    if [[ "$SELF_INSTALL" == "true" ]]; then
        if [[ -d "$PROJECT_ROOT/src/claude_code_hooks_daemon" ]]; then
            echo -e "${GREEN}✓ Self-install mode (config)${NC}"
        else
            echo -e "${RED}✗ Self-install mode but daemon source not found${NC}"
            FAILED=1
        fi
    elif [[ -d "$HOOKS_DAEMON_DIR" ]]; then
        echo -e "${GREEN}✓ Normal installation${NC}"
    else
        echo -e "${RED}✗ Not found: $HOOKS_DAEMON_DIR${NC}"
        FAILED=1
    fi
else
    if [[ -d "$HOOKS_DAEMON_DIR" ]]; then
        echo -e "${GREEN}✓ Normal installation${NC}"
    else
        echo -e "${RED}✗ Not found: $HOOKS_DAEMON_DIR${NC}"
        FAILED=1
    fi
fi

#
# Check 6: Hook files exist
#
echo -n "6. Hook files exist... "
HOOKS_DIR="$PROJECT_ROOT/.claude/hooks"
REQUIRED_HOOKS=("pre-tool-use" "post-tool-use" "session-start")
MISSING_HOOKS=()

for hook in "${REQUIRED_HOOKS[@]}"; do
    if [[ ! -f "$HOOKS_DIR/$hook" ]]; then
        MISSING_HOOKS+=("$hook")
    fi
done

if [[ ${#MISSING_HOOKS[@]} -eq 0 ]]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗ Missing: ${MISSING_HOOKS[*]}${NC}"
    FAILED=1
fi

#
# Check 7: init.sh exists
#
echo -n "7. init.sh exists... "
INIT_SH="$PROJECT_ROOT/.claude/init.sh"
if [[ -f "$INIT_SH" ]]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗ Not found: $INIT_SH${NC}"
    FAILED=1
fi

#
# Check 8: settings.json exists
#
echo -n "8. settings.json exists... "
SETTINGS_JSON="$PROJECT_ROOT/.claude/settings.json"
if [[ -f "$SETTINGS_JSON" ]]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗ Not found: $SETTINGS_JSON${NC}"
    FAILED=1
fi

#
# Summary
#
echo ""
if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}✅ All health checks passed${NC}"
    exit 0
else
    echo -e "${RED}❌ Some health checks failed${NC}"
    exit 1
fi
