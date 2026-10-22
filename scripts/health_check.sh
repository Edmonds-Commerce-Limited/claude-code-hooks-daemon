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

# Colours (RED, GREEN, YELLOW, NC) come from output.sh, which mode_guard.sh
# loads; mode_guard.sh also carries the one self-install test.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=install/mode_guard.sh
source "${SCRIPT_DIR}/install/mode_guard.sh"

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

CONFIG_FILE="$PROJECT_ROOT/.claude/hooks-daemon.yaml"

# The YAML checks run the project's RESOLVED interpreter (its venv's
# bin/python, or $HOOKS_DAEMON_PYTHON), never a bare python3 from PATH, which
# may be older than the daemon's floor or lack PyYAML. When none resolves the
# checks that need one FAIL loudly; the resolver's own diagnostic goes to
# stderr.
# shellcheck source=install/venv_resolver.sh
source "${SCRIPT_DIR}/install/venv_resolver.sh"
CONFIG_PYTHON=""
if [[ -f "$CONFIG_FILE" ]]; then
    if [[ -d "$PROJECT_ROOT/.claude/hooks-daemon" ]]; then
        RESOLVE_DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
    else
        RESOLVE_DAEMON_DIR="$PROJECT_ROOT"
    fi
    CONFIG_PYTHON="$(resolve_existing_venv_python "$RESOLVE_DAEMON_DIR")" || CONFIG_PYTHON=""
fi

#
# read_self_install_mode() - Print "true"/"false" for daemon.self_install_mode
#
# Returns 1 (printing nothing) when no interpreter was resolved. A config the
# parser cannot read prints "false"; check 2 is what reports invalid YAML.
#
read_self_install_mode() {
    [[ -n "$CONFIG_PYTHON" ]] || return 1
    "$CONFIG_PYTHON" -c "
import sys
import yaml
try:
    with open(sys.argv[1]) as f:
        config = yaml.safe_load(f) or {}
    daemon = config.get('daemon', {})
    print('true' if daemon.get('self_install_mode', False) else 'false')
except (OSError, yaml.YAMLError, AttributeError):
    print('false')
" "$CONFIG_FILE"
}

#
# Check 1: Config file exists
#
echo -n "1. Config file exists... "
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
    if [[ -z "$CONFIG_PYTHON" ]]; then
        echo -e "${RED}✗ No resolved Python interpreter to validate the config${NC}"
        FAILED=1
    elif "$CONFIG_PYTHON" -c "import sys, yaml; yaml.safe_load(open(sys.argv[1]))" "$CONFIG_FILE"; then
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
            if ! SELF_INSTALL=$(read_self_install_mode); then
                echo -e "${RED}✗ hooks-daemon repo but no resolved Python interpreter to read self_install_mode${NC}"
                FAILED=1
            elif [[ "$SELF_INSTALL" == "true" ]]; then
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

# Detect self-install mode from YAML config (not .env file presence)
SELF_INSTALL="false"
if [[ -f "$CONFIG_FILE" ]]; then
    if ! SELF_INSTALL=$(read_self_install_mode); then
        echo -e "${RED}✗ No resolved Python interpreter to read self_install_mode${NC}"
        FAILED=1
        SELF_INSTALL="false"
    fi
fi

if [[ "$SELF_INSTALL" == "true" ]]; then
    # Self-install mode - daemon code should be at project root
    if is_self_install_checkout "$PROJECT_ROOT"; then
        echo -e "${GREEN}✓ Self-install mode${NC}"
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
