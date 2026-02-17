#!/bin/bash
# Migration script for v2.10 → v2.11 upgrade
# Removes obsolete handler references from config file

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Config file location (relative to project root)
CONFIG_FILE=".claude/hooks-daemon.yaml"

echo -e "${BLUE}=== v2.10 → v2.11 Configuration Migration ===${NC}"
echo ""

# Check if config file exists
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo -e "${RED}❌ Config file not found: $CONFIG_FILE${NC}"
    echo "   Are you running this from the project root?"
    exit 1
fi

echo "Config file: $CONFIG_FILE"
echo ""

# Check if removed handlers are referenced
VALIDATE_SITEMAP_FOUND=false
REMIND_VALIDATOR_FOUND=false

if grep -q "validate_sitemap:" "$CONFIG_FILE"; then
    VALIDATE_SITEMAP_FOUND=true
fi

if grep -q "remind_validator:" "$CONFIG_FILE"; then
    REMIND_VALIDATOR_FOUND=true
fi

# If neither handler is found, no migration needed
if [[ "$VALIDATE_SITEMAP_FOUND" == "false" ]] && [[ "$REMIND_VALIDATOR_FOUND" == "false" ]]; then
    echo -e "${GREEN}✅ No removed handlers found in config${NC}"
    echo "   Your configuration is already compatible with v2.11"
    echo ""
    echo "No changes needed!"
    exit 0
fi

# Show what was found
echo -e "${YELLOW}⚠️  Found removed handlers in config:${NC}"
if [[ "$VALIDATE_SITEMAP_FOUND" == "true" ]]; then
    echo "   • validate_sitemap (PostToolUse)"
fi
if [[ "$REMIND_VALIDATOR_FOUND" == "true" ]]; then
    echo "   • remind_validator (SubagentStop)"
fi
echo ""

# Backup config
BACKUP_FILE="${CONFIG_FILE}.v2.10.backup"
echo "Creating backup: $BACKUP_FILE"
cp "$CONFIG_FILE" "$BACKUP_FILE"
echo -e "${GREEN}✅ Backup created${NC}"
echo ""

# Ask user for migration strategy
echo "Migration options:"
echo "  1) Comment out removed handlers (recommended)"
echo "  2) Delete removed handlers completely"
echo "  3) Cancel (no changes)"
echo ""
read -p "Choose option [1-3]: " OPTION

case "$OPTION" in
    1)
        echo ""
        echo "Commenting out removed handlers..."

        # Use Python to process the file
        python3 << 'PYTHON_SCRIPT'
import sys

CONFIG_FILE = ".claude/hooks-daemon.yaml"

# Read the file
with open(CONFIG_FILE, 'r') as f:
    lines = f.readlines()

# Process lines
output_lines = []
in_validate_sitemap = False
in_remind_validator = False
indent = ""

for line in lines:
    # Check if we're entering a removed handler section
    if "validate_sitemap:" in line and line.strip().startswith("validate_sitemap:"):
        in_validate_sitemap = True
        # Get indent
        indent = line[:len(line) - len(line.lstrip())]
        # Add commented header
        output_lines.append(f"{indent}# validate_sitemap:  # REMOVED in v2.11 - project-specific handler\n")
        output_lines.append(f"{indent}#   # This handler was removed because it's project-specific.\n")
        output_lines.append(f"{indent}#   # Migrate to .claude/project-handlers/ if you need this functionality.\n")
        output_lines.append(f"{indent}#   # See: CLAUDE/UPGRADES/v2/v2.10-to-v2.11/v2.10-to-v2.11.md\n")
        continue
    elif "remind_validator:" in line and line.strip().startswith("remind_validator:"):
        in_remind_validator = True
        # Get indent
        indent = line[:len(line) - len(line.lstrip())]
        # Add commented header
        output_lines.append(f"{indent}# remind_validator:  # REMOVED in v2.11 - project-specific handler\n")
        output_lines.append(f"{indent}#   # This handler was removed because it's project-specific.\n")
        output_lines.append(f"{indent}#   # Migrate to .claude/project-handlers/ if you need this functionality.\n")
        output_lines.append(f"{indent}#   # See: CLAUDE/UPGRADES/v2/v2.10-to-v2.11/v2.10-to-v2.11.md\n")
        continue

    # Check if we're exiting a handler section
    if in_validate_sitemap or in_remind_validator:
        stripped = line.strip()
        line_indent = len(line) - len(line.lstrip())
        base_indent = len(indent)

        # Exit if we hit a line at same or lower indentation with content
        if stripped and line_indent <= base_indent and ":" in line:
            in_validate_sitemap = False
            in_remind_validator = False
            output_lines.append(line)
            continue

        # Comment out lines in handler section
        if line.strip():
            output_lines.append(f"{indent}#{line[len(indent):]}")
        else:
            output_lines.append(line)
    else:
        # Normal line
        output_lines.append(line)

# Write back
with open(CONFIG_FILE, 'w') as f:
    f.writelines(output_lines)

print("Processing complete")
PYTHON_SCRIPT

        echo -e "${GREEN}✅ Removed handlers commented out${NC}"
        ;;

    2)
        echo ""
        echo "Deleting removed handlers..."

        # Use Python to process the file
        python3 << 'PYTHON_SCRIPT'
import sys

CONFIG_FILE = ".claude/hooks-daemon.yaml"

# Read the file
with open(CONFIG_FILE, 'r') as f:
    lines = f.readlines()

# Process lines
output_lines = []
in_validate_sitemap = False
in_remind_validator = False
indent = ""

for line in lines:
    # Check if we're entering a removed handler section
    if "validate_sitemap:" in line and line.strip().startswith("validate_sitemap:"):
        in_validate_sitemap = True
        indent = line[:len(line) - len(line.lstrip())]
        continue
    elif "remind_validator:" in line and line.strip().startswith("remind_validator:"):
        in_remind_validator = True
        indent = line[:len(line) - len(line.lstrip())]
        continue

    # Check if we're exiting a handler section
    if in_validate_sitemap or in_remind_validator:
        stripped = line.strip()
        line_indent = len(line) - len(line.lstrip())
        base_indent = len(indent)

        # Exit if we hit a line at same or lower indentation with content
        if stripped and line_indent <= base_indent and ":" in line:
            in_validate_sitemap = False
            in_remind_validator = False
            output_lines.append(line)
            continue

        # Skip lines in handler section
        continue
    else:
        # Normal line
        output_lines.append(line)

# Write back
with open(CONFIG_FILE, 'w') as f:
    f.writelines(output_lines)

print("Processing complete")
PYTHON_SCRIPT

        echo -e "${GREEN}✅ Removed handlers deleted${NC}"
        ;;

    3)
        echo ""
        echo "Cancelled. No changes made."
        echo "Removing backup..."
        rm "$BACKUP_FILE"
        exit 0
        ;;

    *)
        echo ""
        echo -e "${RED}Invalid option${NC}"
        echo "Removing backup..."
        rm "$BACKUP_FILE"
        exit 1
        ;;
esac

echo ""
echo -e "${BLUE}=== Migration Complete ===${NC}"
echo ""
echo "Changes made:"
echo "  • Original config backed up to: $BACKUP_FILE"
echo "  • Removed handlers processed in: $CONFIG_FILE"
echo ""

if [[ "$VALIDATE_SITEMAP_FOUND" == "true" ]] || [[ "$REMIND_VALIDATOR_FOUND" == "true" ]]; then
    echo -e "${YELLOW}Next steps:${NC}"
    echo ""
    echo "1. Review the changes:"
    echo "   diff $BACKUP_FILE $CONFIG_FILE"
    echo ""
    echo "2. If you need the removed functionality:"
    echo "   • Read migration guide: CLAUDE/UPGRADES/v2/v2.10-to-v2.11/v2.10-to-v2.11.md"
    echo "   • See project handlers docs: .claude/hooks-daemon/CLAUDE/PROJECT_HANDLERS.md"
    echo "   • Recreate as project handlers in: .claude/project-handlers/"
    echo ""
    echo "3. Restart the daemon:"
    echo "   cd .claude/hooks-daemon"
    echo "   untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart"
    echo ""
fi

echo -e "${GREEN}Migration successful!${NC}"
