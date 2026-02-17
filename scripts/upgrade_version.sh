#!/bin/bash
#
# upgrade_version.sh - Layer 2: Version-specific upgrade orchestrator
#
# This script is called by the Layer 1 upgrade.sh after determining the
# target version. It implements "Upgrade = Clean Reinstall + Config
# Preservation" using modular library functions from scripts/install/.
#
# CRITICAL: This script must NEVER run in self-install mode.
#
# Usage (called by Layer 1):
#   bash scripts/upgrade_version.sh "$PROJECT_ROOT" "$DAEMON_DIR" "$TARGET_VERSION"
#
# Arguments:
#   $1 - PROJECT_ROOT: Absolute path to the user's project root
#   $2 - DAEMON_DIR: Absolute path to the daemon installation directory
#   $3 - TARGET_VERSION: Git tag or ref to upgrade to (e.g., v2.6.0)
#
# Exit codes:
#   0 - Upgrade completed successfully
#   1 - Upgrade failed (rollback attempted)
#

set -euo pipefail

# Resolve script directory for sourcing library modules
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LIB_DIR="$SCRIPT_DIR/install"

# Source all library modules
source "$INSTALL_LIB_DIR/output.sh"
source "$INSTALL_LIB_DIR/mode_guard.sh"
source "$INSTALL_LIB_DIR/prerequisites.sh"
source "$INSTALL_LIB_DIR/project_detection.sh"
source "$INSTALL_LIB_DIR/venv.sh"
source "$INSTALL_LIB_DIR/hooks_deploy.sh"
source "$INSTALL_LIB_DIR/gitignore.sh"
source "$INSTALL_LIB_DIR/slash_commands.sh"
source "$INSTALL_LIB_DIR/validation.sh"
source "$INSTALL_LIB_DIR/daemon_control.sh"
source "$INSTALL_LIB_DIR/rollback.sh"
source "$INSTALL_LIB_DIR/config_preserve.sh"

# ============================================================
# Argument parsing
# ============================================================

PROJECT_ROOT="${1:-}"
DAEMON_DIR="${2:-}"
TARGET_VERSION="${3:-}"

if [ -z "$PROJECT_ROOT" ] || [ -z "$DAEMON_DIR" ] || [ -z "$TARGET_VERSION" ]; then
    fail_fast "Usage: upgrade_version.sh <PROJECT_ROOT> <DAEMON_DIR> <TARGET_VERSION>"
fi

if [ ! -d "$PROJECT_ROOT" ]; then
    fail_fast "Project root does not exist: $PROJECT_ROOT"
fi

if [ ! -d "$DAEMON_DIR" ]; then
    fail_fast "Daemon directory does not exist: $DAEMON_DIR"
fi

# Derived paths
VENV_PYTHON="$DAEMON_DIR/untracked/venv/bin/python"
EXAMPLE_CONFIG="$DAEMON_DIR/.claude/hooks-daemon.yaml.example"
SETTINGS_JSON_SOURCE="$DAEMON_DIR/.claude/settings.json"
TARGET_CONFIG="$PROJECT_ROOT/.claude/hooks-daemon.yaml"

# Rollback state
SNAPSHOT_ID=""
ROLLBACK_REF=""
UPGRADE_STARTED=false

# ============================================================
# Rollback trap
# ============================================================

cleanup_on_failure() {
    local exit_code=$?
    if [ $exit_code -ne 0 ] && [ "$UPGRADE_STARTED" = true ]; then
        echo ""
        print_warning "Upgrade failed - attempting rollback..."

        # Restore from snapshot if available
        if [ -n "$SNAPSHOT_ID" ]; then
            if restore_state_snapshot "$PROJECT_ROOT" "$DAEMON_DIR" "$SNAPSHOT_ID" "normal"; then
                print_success "Rolled back to pre-upgrade state (snapshot: $SNAPSHOT_ID)"
            else
                print_error "Rollback failed. Manual intervention required."
                print_info "Snapshot ID: $SNAPSHOT_ID"
                print_info "Snapshots: $(get_snapshot_dir "$DAEMON_DIR")"
            fi
        elif [ -n "$ROLLBACK_REF" ]; then
            # Fallback: just checkout the old ref
            if git -C "$DAEMON_DIR" checkout "$ROLLBACK_REF" 2>/dev/null; then
                print_success "Rolled back git to: $ROLLBACK_REF"
            else
                print_error "Git rollback failed. Previous ref: $ROLLBACK_REF"
            fi
        fi

        # Try to restart daemon with old code
        if [ -f "$VENV_PYTHON" ]; then
            print_info "Attempting to restart daemon with previous version..."
            restart_daemon_quick "$VENV_PYTHON" 2>/dev/null || true
        fi
    fi
}
trap cleanup_on_failure EXIT

# ============================================================
# Step 1: Safety checks
# ============================================================

print_header "Claude Code Hooks Daemon - Upgrade"

print_info "Project root: $PROJECT_ROOT"
print_info "Daemon directory: $DAEMON_DIR"
print_info "Target version: $TARGET_VERSION"

log_step "1" "Safety checks"

# CRITICAL: Abort if running in self-install mode
ensure_normal_mode_only "$DAEMON_DIR"

# Validate project structure
validate_project_structure "$PROJECT_ROOT" "true"

# Validate daemon is a git repo
if [ ! -d "$DAEMON_DIR/.git" ]; then
    fail_fast "Daemon directory is not a git repository: $DAEMON_DIR"
fi

# ============================================================
# Step 2: Pre-upgrade checks
# ============================================================

log_step "2" "Pre-upgrade checks"

# Get current version info
CURRENT_VERSION="unknown"
VERSION_FILE="$DAEMON_DIR/src/claude_code_hooks_daemon/version.py"
if [ -f "$VERSION_FILE" ] && [ -f "$VENV_PYTHON" ]; then
    CURRENT_VERSION=$("$VENV_PYTHON" -c "
from claude_code_hooks_daemon.version import __version__
print(__version__)
" 2>/dev/null || echo "unknown")
fi

# Get current git ref for rollback
ROLLBACK_REF=$(git -C "$DAEMON_DIR" describe --tags --exact-match 2>/dev/null || \
               git -C "$DAEMON_DIR" rev-parse --short HEAD 2>/dev/null || \
               echo "")

print_info "Current version: $CURRENT_VERSION"
print_info "Current git ref: ${ROLLBACK_REF:-unknown}"

# Check if already at target version
if [ "$ROLLBACK_REF" = "$TARGET_VERSION" ]; then
    print_success "Already at version $TARGET_VERSION"
    print_info "Skipping code checkout, running validation only..."

    # Just verify and restart
    if [ -f "$VENV_PYTHON" ]; then
        restart_daemon_verified "$VENV_PYTHON" || true
    fi

    print_success "Upgrade verification complete"
    exit 0
fi

# Run pre-upgrade safety checks if venv exists
if [ -f "$VENV_PYTHON" ]; then
    run_pre_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" "false" || true
fi

# Pre-upgrade compatibility check (validates BEFORE any changes)
if [ -f "$TARGET_CONFIG" ] && [ -f "$VENV_PYTHON" ]; then
    print_info "Checking config compatibility with target version..."

    COMPAT_RESULT=$("$VENV_PYTHON" -c "
import json
import sys
from pathlib import Path

try:
    from claude_code_hooks_daemon.install.upgrade_compatibility import CompatibilityChecker

    changelog_path = Path('$DAEMON_DIR/CHANGELOG.md')
    if not changelog_path.exists():
        print('WARNING: CHANGELOG.md not found, skipping compatibility check', file=sys.stderr)
        sys.exit(0)

    # Load user config
    import yaml
    with open('$TARGET_CONFIG') as f:
        user_config = yaml.safe_load(f)

    # Check compatibility
    checker = CompatibilityChecker(
        changelog_path=changelog_path,
        current_version='$CURRENT_VERSION',
        target_version='$TARGET_VERSION'
    )

    report = checker.check_compatibility(user_config)

    if not report.is_compatible:
        print(checker.generate_user_friendly_report(report), file=sys.stderr)
        print('', file=sys.stderr)
        print('INCOMPATIBILITIES DETECTED', file=sys.stderr)
        print('', file=sys.stderr)
        print('Your config references handlers that are incompatible with $TARGET_VERSION.', file=sys.stderr)
        print('', file=sys.stderr)
        print('OPTIONS:', file=sys.stderr)
        print('  1. Fix config issues manually and re-run upgrade', file=sys.stderr)
        print('  2. Use --force to proceed anyway (config will be updated automatically)', file=sys.stderr)
        print('', file=sys.stderr)

        # Check for --force flag
        import os
        if '--force' not in os.environ.get('UPGRADE_FLAGS', ''):
            sys.exit(1)
        else:
            print('--force flag detected, proceeding with upgrade...', file=sys.stderr)
    else:
        print('✓ All handlers compatible with target version', file=sys.stderr)

except Exception as e:
    print(f'WARNING: Compatibility check failed: {e}', file=sys.stderr)
    sys.exit(0)
" 2>&1)
    COMPAT_EXIT=$?

    if [ $COMPAT_EXIT -ne 0 ]; then
        echo "$COMPAT_RESULT"
        if [[ "$*" == *"--force"* ]]; then
            print_warning "Proceeding despite incompatibilities (--force flag)"
        else
            fail_fast "Config compatibility check failed. Use --force to proceed anyway."
        fi
    fi
fi

# ============================================================
# Step 3: Create state snapshot
# ============================================================

log_step "3" "Creating state snapshot for rollback"

SNAPSHOT_ID=$(create_state_snapshot "$PROJECT_ROOT" "$DAEMON_DIR" "normal" 2>/dev/null | tail -1)

if [ -n "$SNAPSHOT_ID" ]; then
    print_success "Snapshot created: $SNAPSHOT_ID"
else
    print_warning "Could not create snapshot - upgrade will proceed without rollback capability"
fi

# Mark upgrade as started (enables rollback on failure)
UPGRADE_STARTED=true

# ============================================================
# Step 4: Stop daemon
# ============================================================

log_step "4" "Stopping daemon"
stop_daemon_safe "$VENV_PYTHON"
sleep 1

# ============================================================
# Step 5: Backup and extract config customizations
# ============================================================

log_step "5" "Preserving config customizations"

# Save the old example config before checkout (for diff baseline)
OLD_DEFAULT_CONFIG=""
if [ -f "$EXAMPLE_CONFIG" ]; then
    OLD_DEFAULT_CONFIG=$(mktemp /tmp/hooks_daemon_old_default_XXXXXX.yaml)
    cp "$EXAMPLE_CONFIG" "$OLD_DEFAULT_CONFIG"
    print_verbose "Saved old default config for diff baseline"
fi

# Backup current config
CONFIG_BACKUP=""
if [ -f "$TARGET_CONFIG" ]; then
    CONFIG_BACKUP=$(backup_config "$PROJECT_ROOT")
    print_verbose "Config backup: $CONFIG_BACKUP"
fi

# Breaking changes detection (compare old vs new default config)
if [ -f "$TARGET_CONFIG" ] && [ -f "$OLD_DEFAULT_CONFIG" ] && [ -f "$VENV_PYTHON" ]; then
    print_info "Analyzing config for breaking changes..."

    # Run config diff analyzer
    DIFF_RESULT=$("$SCRIPT_DIR/install/config_diff_analyzer.sh" "$TARGET_CONFIG" "$OLD_DEFAULT_CONFIG" 2>&1 || echo "{}")

    # Parse diff result and detect breaking changes
    "$VENV_PYTHON" -c "
import json
import sys
from pathlib import Path

try:
    from claude_code_hooks_daemon.install.breaking_changes_detector import BreakingChangesDetector

    changelog_path = Path('$DAEMON_DIR/CHANGELOG.md')
    if not changelog_path.exists():
        sys.exit(0)

    # Parse diff result
    diff_data = json.loads('''$DIFF_RESULT''')
    removed_handlers = diff_data.get('removed', [])
    renamed_handlers = diff_data.get('renamed', {})

    if not removed_handlers and not renamed_handlers:
        sys.exit(0)

    # Generate warnings for breaking changes
    detector = BreakingChangesDetector(changelog_path)
    warnings = detector.generate_warnings(
        removed_handlers=removed_handlers,
        renamed_handlers=renamed_handlers
    )

    if warnings:
        print('', file=sys.stderr)
        print('⚠️  BREAKING CHANGES DETECTED IN CONFIG', file=sys.stderr)
        print('=' * 70, file=sys.stderr)
        for warning in warnings:
            print(warning, file=sys.stderr)
            print('', file=sys.stderr)
        print('Your config will be automatically updated during merge.', file=sys.stderr)
        print('Review the config after upgrade completes.', file=sys.stderr)
        print('', file=sys.stderr)

except Exception as e:
    print(f'WARNING: Breaking changes detection failed: {e}', file=sys.stderr)
" || true
fi

# ============================================================
# Step 5a: Upgrade guide reading enforcement
# ============================================================

# Detect version jump and list required upgrade guides
if [ "$CURRENT_VERSION" != "unknown" ] && [ -f "$VENV_PYTHON" ]; then
    print_info "Checking for required upgrade guides..."

    GUIDE_CHECK=$("$VENV_PYTHON" -c "
import sys
from pathlib import Path

try:
    from claude_code_hooks_daemon.install.upgrade_compatibility import CompatibilityChecker

    changelog_path = Path('$DAEMON_DIR/CHANGELOG.md')
    if not changelog_path.exists():
        sys.exit(0)

    checker = CompatibilityChecker(
        changelog_path=changelog_path,
        current_version='$CURRENT_VERSION',
        target_version='$TARGET_VERSION'
    )

    # Get suggested upgrade guides
    guides = checker.suggest_upgrade_guides(Path('$DAEMON_DIR'))

    if not guides:
        sys.exit(0)

    print('', file=sys.stderr)
    print('📚 REQUIRED READING: Upgrade Guides', file=sys.stderr)
    print('=' * 70, file=sys.stderr)
    print(f'Upgrading from v{checker.current_version} to v{checker.target_version}', file=sys.stderr)
    print(f'You are skipping {len(guides)} intermediate version(s).', file=sys.stderr)
    print('', file=sys.stderr)
    print('Please review the following upgrade guides:', file=sys.stderr)
    for guide in guides:
        print(f'  • {guide}', file=sys.stderr)
    print('', file=sys.stderr)

    # Write guide list to temp file for bash to read
    with open('/tmp/upgrade_guides_list.txt', 'w') as f:
        for guide in guides:
            f.write(str(guide) + '\n')

    print('GUIDES_FOUND', file=sys.stderr)

except Exception as e:
    print(f'WARNING: Upgrade guide check failed: {e}', file=sys.stderr)
    sys.exit(0)
" 2>&1)

    if echo "$GUIDE_CHECK" | grep -q "GUIDES_FOUND"; then
        # Interactive prompt (unless --skip-reading-confirmation flag)
        if [[ "$*" != *"--skip-reading-confirmation"* ]]; then
            echo ""
            echo "Have you read all upgrade guides? (yes/no/show)"
            read -r -p "> " response

            while true; do
                case "$response" in
                    yes|y|Y)
                        print_success "Proceeding with upgrade..."
                        break
                        ;;
                    show|s|S)
                        # Display guides using pager
                        if [ -f /tmp/upgrade_guides_list.txt ]; then
                            while IFS= read -r guide_path; do
                                if [ -f "$guide_path" ]; then
                                    echo ""
                                    echo "========================================="
                                    echo "Displaying: $guide_path"
                                    echo "========================================="
                                    ${PAGER:-less} "$guide_path"
                                fi
                            done < /tmp/upgrade_guides_list.txt
                        fi
                        echo ""
                        echo "Have you read all upgrade guides? (yes/no/show)"
                        read -r -p "> " response
                        ;;
                    no|n|N)
                        echo ""
                        print_warning "Please review upgrade guides before proceeding."
                        print_info "Guides location: $DAEMON_DIR/CLAUDE/UPGRADES/"
                        fail_fast "Upgrade aborted - read guides and try again"
                        ;;
                    *)
                        echo "Please answer 'yes', 'no', or 'show'"
                        read -r -p "> " response
                        ;;
                esac
            done

            # Cleanup temp file
            rm -f /tmp/upgrade_guides_list.txt
        else
            print_info "--skip-reading-confirmation flag detected, skipping guide confirmation"
        fi
    fi
fi

# ============================================================
# Step 6: Checkout target version
# ============================================================

log_step "6" "Checking out target version"

print_info "Fetching tags..."
git -C "$DAEMON_DIR" fetch --tags --quiet

# Verify target version exists
if ! git -C "$DAEMON_DIR" rev-parse "$TARGET_VERSION" &>/dev/null; then
    fail_fast "Version $TARGET_VERSION not found. Available versions:
$(git -C "$DAEMON_DIR" tag -l | sort -V | tail -10)"
fi

print_info "Checking out $TARGET_VERSION..."
git -C "$DAEMON_DIR" checkout "$TARGET_VERSION" --quiet
print_success "Checked out $TARGET_VERSION"

# ============================================================
# Step 7: Recreate virtual environment (clean reinstall)
# ============================================================

log_step "7" "Recreating virtual environment"
recreate_venv "$DAEMON_DIR"

if ! verify_venv "$VENV_PYTHON" "$DAEMON_DIR"; then
    fail_fast "Virtual environment verification failed after recreate"
fi

# ============================================================
# Step 8: Redeploy hook scripts
# ============================================================

log_step "8" "Redeploying hook scripts"
deploy_all_hooks "$PROJECT_ROOT" "$DAEMON_DIR" "normal"

# ============================================================
# Step 9: Redeploy settings.json
# ============================================================

log_step "9" "Redeploying settings.json"

TARGET_SETTINGS="$PROJECT_ROOT/.claude/settings.json"

if [ -f "$SETTINGS_JSON_SOURCE" ]; then
    cp "$SETTINGS_JSON_SOURCE" "$TARGET_SETTINGS"
    print_success "Redeployed settings.json"
else
    print_verbose "No settings.json in daemon repo (using existing)"
fi

# ============================================================
# Step 10: Config preservation (merge customizations onto new default)
# ============================================================

log_step "10" "Merging config customizations"

NEW_DEFAULT_CONFIG="$EXAMPLE_CONFIG"

if [ -n "$OLD_DEFAULT_CONFIG" ] && [ -f "$OLD_DEFAULT_CONFIG" ] && [ -f "$NEW_DEFAULT_CONFIG" ] && [ -f "$TARGET_CONFIG" ]; then
    # Full config preservation: diff + merge + validate
    if preserve_config_for_upgrade "$VENV_PYTHON" "$PROJECT_ROOT" "$OLD_DEFAULT_CONFIG" "$NEW_DEFAULT_CONFIG"; then
        print_success "Config customizations preserved"
    else
        print_warning "Config preservation had issues - review config manually"
        print_info "Backup: $CONFIG_BACKUP"
    fi
elif [ ! -f "$TARGET_CONFIG" ] && [ -f "$NEW_DEFAULT_CONFIG" ]; then
    # No existing config - copy new default
    cp "$NEW_DEFAULT_CONFIG" "$TARGET_CONFIG"
    print_success "Installed new default config"
else
    print_info "Config preservation skipped (missing baseline or config)"
    if [ -n "$CONFIG_BACKUP" ]; then
        print_info "Your config backup: $CONFIG_BACKUP"
    fi
fi

# Clean up temp file
if [ -n "$OLD_DEFAULT_CONFIG" ] && [ -f "$OLD_DEFAULT_CONFIG" ]; then
    rm -f "$OLD_DEFAULT_CONFIG"
fi

# ============================================================
# Step 11: Setup .gitignore
# ============================================================

log_step "11" "Verifying .gitignore"
setup_all_gitignores "$PROJECT_ROOT" "$DAEMON_DIR" "normal" || print_warning ".gitignore setup had warnings (non-fatal)"

# ============================================================
# Step 12: Redeploy slash commands
# ============================================================

log_step "12" "Redeploying slash commands"
deploy_slash_commands "$PROJECT_ROOT" "$DAEMON_DIR" "normal"

# ============================================================
# Step 13: Redeploy skills
# ============================================================

log_step "13" "Redeploying user-facing skills"

"$VENV_PYTHON" -c "
from pathlib import Path
from claude_code_hooks_daemon.install.skills import deploy_skills

daemon_source = Path('$DAEMON_DIR')
project_root = Path('$PROJECT_ROOT')

try:
    deploy_skills(daemon_source, project_root)
    print('✓ Skills redeployed to .claude/skills/hooks-daemon/')
except Exception as e:
    print(f'✗ Skill redeployment failed: {e}')
    exit(1)
"

# ============================================================
# Step 14: Restart daemon and verify
# ============================================================

log_step "14" "Restarting daemon"

if ! restart_daemon_verified "$VENV_PYTHON"; then
    print_error "Daemon failed to start after upgrade"
    print_info "This may indicate config validation errors"
    print_info "Check: $VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status"

    if [ -n "$CONFIG_BACKUP" ]; then
        echo ""
        print_info "To restore previous config:"
        echo "  cp $CONFIG_BACKUP $TARGET_CONFIG"
        echo "  $VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart"
    fi

    # Don't trigger rollback for daemon start failure - code is updated
    # User can fix config manually
    UPGRADE_STARTED=false
    exit 1
fi

# ============================================================
# Step 15: Post-upgrade validation
# ============================================================

log_step "15" "Running post-upgrade validation"
run_post_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" "false" || true

# ============================================================
# Step 16: Cleanup old snapshots
# ============================================================

log_step "16" "Cleanup"
cleanup_old_snapshots "$DAEMON_DIR" 3

# Get new version
NEW_VERSION="unknown"
if [ -f "$VERSION_FILE" ] && [ -f "$VENV_PYTHON" ]; then
    NEW_VERSION=$("$VENV_PYTHON" -c "
from claude_code_hooks_daemon.version import __version__
print(__version__)
" 2>/dev/null || echo "unknown")
fi

# ============================================================
# Complete
# ============================================================

# Disable rollback on success
UPGRADE_STARTED=false

print_header "Upgrade Complete"

print_success "Claude Code Hooks Daemon upgraded successfully!"
echo ""
echo "  Previous version: $CURRENT_VERSION"
echo "  Current version:  $NEW_VERSION"
echo "  Config:           $TARGET_CONFIG"
echo "  Config backup:    ${CONFIG_BACKUP:-none}"
echo "  Rollback snapshot: ${SNAPSHOT_ID:-none}"
echo ""

# Check for upgrade guides
UPGRADE_DIR="$DAEMON_DIR/CLAUDE/UPGRADES"
if [ -d "$UPGRADE_DIR" ]; then
    echo "Version-specific upgrade notes:"
    echo "  ls $UPGRADE_DIR/"
    echo ""
fi

echo "IMPORTANT: Restart Claude Code to activate upgraded hooks."
echo "  1. Exit your current Claude Code session"
echo "  2. Start a new Claude Code session"
echo ""

exit 0
