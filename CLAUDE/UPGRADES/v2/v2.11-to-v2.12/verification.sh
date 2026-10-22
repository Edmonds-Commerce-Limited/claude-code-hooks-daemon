#!/usr/bin/env bash
# Verification script: v2.11 → v2.12
# Validates successful migration to lint_on_edit handler

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
CONFIG_FILE=".claude/hooks-daemon.yaml"
OLD_HANDLER="validate_eslint_on_write"
NEW_HANDLER="lint_on_edit"
EXPECTED_VERSION="2.12.0"

# Detect self-install mode
if [[ -f "src/claude_code_hooks_daemon/version.py" ]]; then
    VERSION_FILE="src/claude_code_hooks_daemon/version.py"
else
    VERSION_FILE=".claude/hooks-daemon/src/claude_code_hooks_daemon/version.py"
fi

# Resolve the daemon's interpreter (its venv bin/python via the canonical
# resolver, else $HOOKS_DAEMON_PYTHON). Never a bare python3 from PATH, which
# may be older than the daemon's floor or lack PyYAML. When none resolves,
# PYTHON_BIN stays empty and the checks that need it FAIL loudly.
RESOLVE_DAEMON_DIR=".claude/hooks-daemon"
if [[ ! -d "$RESOLVE_DAEMON_DIR" ]]; then
    RESOLVE_DAEMON_DIR="."
fi
RESOLVE_LIB="$RESOLVE_DAEMON_DIR/scripts/lib/resolve_venv.sh"
PYTHON_BIN=""
if [[ -f "$RESOLVE_LIB" ]]; then
    # shellcheck disable=SC1090
    source "$RESOLVE_LIB"
    PYTHON_BIN="$(resolve_venv_python "$(cd "$RESOLVE_DAEMON_DIR" && pwd)")" || PYTHON_BIN=""
elif [[ -n "${HOOKS_DAEMON_PYTHON:-}" ]]; then
    PYTHON_BIN="$HOOKS_DAEMON_PYTHON"
fi
if [[ -z "$PYTHON_BIN" ]]; then
    echo "No daemon Python interpreter resolved (no venv under $RESOLVE_DAEMON_DIR, HOOKS_DAEMON_PYTHON unset)." >&2
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}v2.12.0 Upgrade Verification${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

PASS_COUNT=0
FAIL_COUNT=0

# Check 1: Version
echo -e "${BLUE}[1/5] Checking daemon version...${NC}"
if [[ -f "$VERSION_FILE" ]]; then
    VERSION=$(grep -oP '__version__ = "\K[^"]+' "$VERSION_FILE" || echo "unknown")
    # Extract major.minor version for comparison (2.12.0 -> 2.12)
    VERSION_MAJOR_MINOR=$(echo "$VERSION" | cut -d. -f1,2)
    EXPECTED_MAJOR_MINOR=$(echo "$EXPECTED_VERSION" | cut -d. -f1,2)

    if [[ "$VERSION_MAJOR_MINOR" == "$EXPECTED_MAJOR_MINOR" ]] || [[ "$VERSION" > "$EXPECTED_VERSION" ]]; then
        echo -e "${GREEN}✅ PASS: Version is $VERSION (>= $EXPECTED_VERSION)${NC}"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "${RED}❌ FAIL: Version is $VERSION, expected >= $EXPECTED_VERSION${NC}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
else
    echo -e "${RED}❌ FAIL: Version file not found: $VERSION_FILE${NC}"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi
echo ""

# Check 2: Config exists and is valid YAML
echo -e "${BLUE}[2/5] Validating config file...${NC}"
if [[ -f "$CONFIG_FILE" ]]; then
    if [[ -z "$PYTHON_BIN" ]]; then
        echo -e "${RED}❌ FAIL: No daemon Python interpreter resolved to validate the config${NC}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    elif "$PYTHON_BIN" -c "import sys, yaml; yaml.safe_load(open(sys.argv[1]))" "$CONFIG_FILE"; then
        echo -e "${GREEN}✅ PASS: Config file is valid YAML${NC}"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "${RED}❌ FAIL: Config file has YAML syntax errors${NC}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
else
    echo -e "${RED}❌ FAIL: Config file not found: $CONFIG_FILE${NC}"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi
echo ""

# Check 3: No old handler name in config
echo -e "${BLUE}[3/5] Checking for old handler name...${NC}"
if grep -q "$OLD_HANDLER" "$CONFIG_FILE" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  WARNING: Old handler name '$OLD_HANDLER' still present in config${NC}"
    echo "Lines containing old name:"
    grep -n "$OLD_HANDLER" "$CONFIG_FILE"
    echo ""
    echo "Run migration script: bash CLAUDE/UPGRADES/v2/v2.11-to-v2.12/migration-script.sh"
    FAIL_COUNT=$((FAIL_COUNT + 1))
else
    echo -e "${GREEN}✅ PASS: No old handler name in config${NC}"
    PASS_COUNT=$((PASS_COUNT + 1))
fi
echo ""

# Check 4: New handler name present (if old one was present before)
echo -e "${BLUE}[4/5] Checking for new handler name...${NC}"
if grep -q "post_tool_use:" "$CONFIG_FILE" 2>/dev/null; then
    if grep -q "$NEW_HANDLER" "$CONFIG_FILE" 2>/dev/null; then
        echo -e "${GREEN}✅ PASS: New handler name '$NEW_HANDLER' found in config${NC}"
        grep -n "$NEW_HANDLER" "$CONFIG_FILE" | head -3
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "${YELLOW}ℹ️  INFO: New handler name not found (may not be configured)${NC}"
        echo "This is OK if you never used the old handler."
        PASS_COUNT=$((PASS_COUNT + 1))
    fi
else
    echo -e "${YELLOW}ℹ️  INFO: No PostToolUse handlers configured${NC}"
    PASS_COUNT=$((PASS_COUNT + 1))
fi
echo ""

# Check 5: Daemon can load handler
echo -e "${BLUE}[5/5] Checking handler loads successfully...${NC}"
if [[ -z "$PYTHON_BIN" ]]; then
    echo -e "${RED}❌ FAIL: No daemon Python interpreter resolved, cannot run the import check${NC}"
    FAIL_COUNT=$((FAIL_COUNT + 1))
else
    # Detect self-install mode vs normal install
    if [[ -d "src/claude_code_hooks_daemon" ]]; then
        # Self-install mode: running from project root
        DAEMON_DIR="."
    else
        # Normal install mode (PYTHON_BIN is absolute, so the cd is safe)
        DAEMON_DIR=".claude/hooks-daemon"
        if [[ -d "$DAEMON_DIR" ]]; then
            cd "$DAEMON_DIR"
        else
            echo -e "${YELLOW}⚠️  WARNING: Daemon directory not found: $DAEMON_DIR${NC}"
            FAIL_COUNT=$((FAIL_COUNT + 1))
            DAEMON_DIR=""
        fi
    fi

    if [[ -n "$DAEMON_DIR" ]]; then
        if "$PYTHON_BIN" -c "from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler; print('OK')"; then
            echo -e "${GREEN}✅ PASS: Handler imports successfully${NC}"
            PASS_COUNT=$((PASS_COUNT + 1))
        else
            echo -e "${RED}❌ FAIL: Handler import error${NC}"
            FAIL_COUNT=$((FAIL_COUNT + 1))
        fi
        if [[ "$DAEMON_DIR" != "." ]]; then
            cd - > /dev/null
        fi
    fi
fi
echo ""

# Summary
echo -e "${BLUE}========================================${NC}"
if [[ $FAIL_COUNT -eq 0 ]]; then
    echo -e "${GREEN}✅ All Verification Checks Passed${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "Results: $PASS_COUNT passed, $FAIL_COUNT failed"
    echo ""
    echo "Upgrade to v2.12.0 is complete and verified!"
    echo ""
    echo "Next steps:"
    echo "  1. Test linting in Claude Code session"
    echo "  2. Optional: Install extended linters (ruff, shellcheck, rubocop, etc.)"
    echo "  3. Optional: Configure language filtering in config"
    echo ""
    exit 0
else
    echo -e "${RED}❌ Verification Failed${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo "Results: $PASS_COUNT passed, $FAIL_COUNT failed"
    echo ""
    echo "Please review the failures above and:"
    echo "  1. Check daemon version: cat .claude/hooks-daemon/src/claude_code_hooks_daemon/version.py"
    echo "  2. Validate config: python3 -c \"import yaml; yaml.safe_load(open('.claude/hooks-daemon.yaml'))\""
    echo "  3. Run migration script if needed: bash CLAUDE/UPGRADES/v2/v2.11-to-v2.12/migration-script.sh"
    echo "  4. Check daemon logs: cat .claude/hooks-daemon/untracked/daemon.log"
    echo ""
    exit 1
fi
