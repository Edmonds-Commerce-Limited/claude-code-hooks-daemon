#!/usr/bin/env bash
# Migration script: v2.11 → v2.12
# Renames validate_eslint_on_write handler to lint_on_edit

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

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}v2.11 → v2.12 Migration Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if config file exists
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo -e "${RED}❌ Error: Config file not found: $CONFIG_FILE${NC}"
    echo ""
    echo "This script must be run from the project root directory."
    exit 1
fi

echo -e "${BLUE}Config file: $CONFIG_FILE${NC}"
echo ""

# Check if old handler name exists
if ! grep -q "$OLD_HANDLER" "$CONFIG_FILE"; then
    echo -e "${GREEN}✅ No migration needed${NC}"
    echo ""
    echo "The old handler name '$OLD_HANDLER' was not found in your config."
    echo "Either you never used this handler, or you've already migrated."
    echo ""
    exit 0
fi

echo -e "${YELLOW}⚠️  Found old handler name: $OLD_HANDLER${NC}"
echo ""

# Show affected lines
echo -e "${BLUE}Affected lines in config:${NC}"
grep -n "$OLD_HANDLER" "$CONFIG_FILE" || true
echo ""

# Create backup
BACKUP_FILE="${CONFIG_FILE}.backup-$(date +%Y%m%d-%H%M%S)"
cp "$CONFIG_FILE" "$BACKUP_FILE"
echo -e "${GREEN}✅ Backup created: $BACKUP_FILE${NC}"
echo ""

# Perform replacement using Python (safe string replacement)
echo -e "${BLUE}Performing migration...${NC}"
python3 << 'PYTHON_SCRIPT'
import sys

config_file = ".claude/hooks-daemon.yaml"
old_handler = "validate_eslint_on_write"
new_handler = "lint_on_edit"

try:
    # Read file
    with open(config_file, 'r') as f:
        content = f.read()

    # Replace all occurrences
    updated_content = content.replace(old_handler, new_handler)

    # Write back
    with open(config_file, 'w') as f:
        f.write(updated_content)

    print(f"✅ Replaced {content.count(old_handler)} occurrence(s)")
    sys.exit(0)
except Exception as e:
    print(f"❌ Error: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON_SCRIPT

if [[ $? -ne 0 ]]; then
    echo -e "${RED}❌ Migration failed${NC}"
    echo "Restoring backup..."
    cp "$BACKUP_FILE" "$CONFIG_FILE"
    exit 1
fi

# Verify syntax
echo -e "${BLUE}Verifying YAML syntax...${NC}"
if python3 -c "import yaml; yaml.safe_load(open('$CONFIG_FILE'))" 2>/dev/null; then
    echo -e "${GREEN}✅ YAML syntax valid${NC}"
else
    echo -e "${RED}❌ YAML syntax error after migration${NC}"
    echo "Restoring backup..."
    cp "$BACKUP_FILE" "$CONFIG_FILE"
    exit 1
fi
echo ""

# Show diff
echo -e "${BLUE}Changes made:${NC}"
echo -e "${YELLOW}OLD:${NC} $OLD_HANDLER"
echo -e "${GREEN}NEW:${NC} $NEW_HANDLER"
echo ""

# Show updated lines
echo -e "${BLUE}Updated lines in config:${NC}"
grep -n "$NEW_HANDLER" "$CONFIG_FILE" || true
echo ""

# Success message
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ Migration Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Summary:"
echo "  • Old handler name: $OLD_HANDLER"
echo "  • New handler name: $NEW_HANDLER"
echo "  • Backup saved to: $BACKUP_FILE"
echo ""
echo "Next steps:"
echo "  1. Review changes: diff $BACKUP_FILE $CONFIG_FILE"
echo "  2. Restart daemon: cd .claude/hooks-daemon && untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart"
echo "  3. Verify status: cd .claude/hooks-daemon && untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status"
echo ""
echo "New capabilities:"
echo "  • JavaScript/TypeScript (ESLint) - preserved from v2.11"
echo "  • Python (py_compile + ruff)"
echo "  • Shell (bash -n + shellcheck)"
echo "  • Ruby (ruby -c + rubocop)"
echo "  • PHP (php -l + phpcs)"
echo "  • Go (go vet + golangci-lint)"
echo "  • Rust (rustc + clippy)"
echo "  • Java (checkstyle)"
echo "  • C/C++ (clang-tidy)"
echo ""
echo "To restrict to specific languages, add to config:"
echo "  lint_on_edit:"
echo "    options:"
echo "      languages:"
echo "        - JavaScript/TypeScript"
echo "        - Python"
echo ""
