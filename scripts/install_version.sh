#!/bin/bash
#
# install_version.sh - Layer 2: Version-specific fresh install orchestrator
#
# This script is called by the Layer 1 install.sh after cloning the repo.
# It orchestrates the complete fresh installation using modular library
# functions from scripts/install/.
#
# CRITICAL: This script must NEVER run in self-install mode.
#
# Usage (called by Layer 1):
#   bash scripts/install_version.sh "$PROJECT_ROOT" "$DAEMON_DIR"
#
# Arguments:
#   $1 - PROJECT_ROOT: Absolute path to the user's project root
#   $2 - DAEMON_DIR: Absolute path to the daemon installation directory
#        (typically $PROJECT_ROOT/.claude/hooks-daemon)
#
# Exit codes:
#   0 - Installation completed successfully
#   1 - Installation failed
#

set -euo pipefail

# Resolve script directory for sourcing library modules
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LIB_DIR="$SCRIPT_DIR/install"

# Source all library modules
# shellcheck source=install/output.sh
source "$INSTALL_LIB_DIR/output.sh"
# shellcheck source=install/mode_guard.sh
source "$INSTALL_LIB_DIR/mode_guard.sh"
# shellcheck source=install/prerequisites.sh
source "$INSTALL_LIB_DIR/prerequisites.sh"
# shellcheck source=install/project_detection.sh
source "$INSTALL_LIB_DIR/project_detection.sh"
# shellcheck source=install/venv.sh
source "$INSTALL_LIB_DIR/venv.sh"
# shellcheck source=install/python_fingerprint.sh
source "$INSTALL_LIB_DIR/python_fingerprint.sh"
# shellcheck source=install/hooks_deploy.sh
source "$INSTALL_LIB_DIR/hooks_deploy.sh"
# shellcheck source=install/gitignore.sh
source "$INSTALL_LIB_DIR/gitignore.sh"
# shellcheck source=install/slash_commands.sh
source "$INSTALL_LIB_DIR/slash_commands.sh"
# shellcheck source=install/validation.sh
source "$INSTALL_LIB_DIR/validation.sh"
# shellcheck source=install/daemon_control.sh
source "$INSTALL_LIB_DIR/daemon_control.sh"

# ============================================================
# Helper functions
# ============================================================

#
# generate_settings_json() - Generate settings.json from scratch
#
# Fallback for when the daemon repo doesn't include a settings.json file.
#
# Args:
#   $1 - project_root: Path to project root
#
generate_settings_json() {
    local project_root="$1"
    local target="$project_root/.claude/settings.json"

    cat > "$target" <<'SETTINGS_EOF'
{
  "statusLine": {
    "type": "command",
    "command": ".claude/hooks/status-line"
  },
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/pre-tool-use",
            "timeout": 60
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/post-tool-use",
            "timeout": 60
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/session-start"
          }
        ]
      }
    ],
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/notification"
          }
        ]
      }
    ],
    "PermissionRequest": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/permission-request"
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/pre-compact"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/session-end"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/stop"
          }
        ]
      }
    ],
    "SubagentStop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/subagent-stop"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/user-prompt-submit"
          }
        ]
      }
    ]
  }
}
SETTINGS_EOF

    print_success "Generated settings.json"
}

# ============================================================
# Argument parsing
# ============================================================

PROJECT_ROOT="${1:-}"
DAEMON_DIR="${2:-}"

if [ -z "$PROJECT_ROOT" ] || [ -z "$DAEMON_DIR" ]; then
    fail_fast "Usage: install_version.sh <PROJECT_ROOT> <DAEMON_DIR>"
fi

if [ ! -d "$PROJECT_ROOT" ]; then
    fail_fast "Project root does not exist: $PROJECT_ROOT"
fi

if [ ! -d "$DAEMON_DIR" ]; then
    fail_fast "Daemon directory does not exist: $DAEMON_DIR"
fi

# Derived paths — VENV_PYTHON populated after ensure_venv returns the real path
VENV_PYTHON=""
EXAMPLE_CONFIG="$DAEMON_DIR/.claude/hooks-daemon.yaml.example"
SETTINGS_JSON_SOURCE="$DAEMON_DIR/.claude/settings.json"

# ============================================================
# Step 1: Safety checks
# ============================================================

print_header "Claude Code Hooks Daemon - Fresh Install"

print_info "Project root: $PROJECT_ROOT"
print_info "Daemon directory: $DAEMON_DIR"

log_step "1" "Safety checks"

# CRITICAL: Abort if running in self-install mode
ensure_normal_mode_only "$DAEMON_DIR"

# Validate project structure
validate_project_structure "$PROJECT_ROOT" "true"

# ============================================================
# Step 2: Prerequisites
# ============================================================

log_step "2" "Checking prerequisites"
# Pass the daemon pyproject so the Python floor derives from its
# requires-python SSoT (F-PYFLOOR), not the bare 3.11 literal.
check_all_prerequisites "true" "$DAEMON_DIR/pyproject.toml"

# ============================================================
# Step 3: Virtual environment
# ============================================================

log_step "3" "Creating virtual environment"

# Plan 00099: venv is keyed by fingerprint of the target Python environment so
# concurrent containers (sharing the same project filesystem with different
# Pythons) each get their own venv without clobbering each other.
# Plan 00105 Phase 1: derive a schema-valid daemon version even when HEAD
# is not exactly tagged. The previous fallback (`git rev-parse --short HEAD`)
# returned a 7-char SHA which fails write-venv-metadata's strict
# 'vMAJOR.MINOR.PATCH' Pydantic validator and silently skipped writing
# .daemon-metadata.json on every non-release-tag install. Solution: when no
# exact tag matches, read the canonical version from pyproject.toml. Never
# fall back to a SHA — fail loudly instead.
if INSTALLED_VERSION=$(git -C "$DAEMON_DIR" describe --tags --exact-match 2>/dev/null); then
    : # tagged release — INSTALLED_VERSION is already vMAJOR.MINOR.PATCH
else
    PYPROJECT_FILE="$DAEMON_DIR/pyproject.toml"
    if [ ! -f "$PYPROJECT_FILE" ]; then
        fail_fast "cannot determine daemon version: HEAD is not tagged and $PYPROJECT_FILE is missing"
    fi
    PYPROJECT_VERSION=$(awk -F'"' '/^version[[:space:]]*=/ { print $2; exit }' "$PYPROJECT_FILE")
    if [ -z "$PYPROJECT_VERSION" ]; then
        fail_fast "cannot determine daemon version: pyproject.toml has no [project].version entry"
    fi
    INSTALLED_VERSION="v$PYPROJECT_VERSION"
fi
VENV_PATH=$(ensure_venv "$DAEMON_DIR" "$INSTALLED_VERSION" "${HOOKS_DAEMON_PYTHON:-python3}")
if [ -z "$VENV_PATH" ]; then
    fail_fast "ensure_venv returned empty path"
fi
VENV_PYTHON="$VENV_PATH/bin/python"

if ! verify_venv "$VENV_PYTHON" "$DAEMON_DIR"; then
    fail_fast "Virtual environment verification failed"
fi

# Plan 00099: clean up any pre-v3.7.0 legacy venv that may have been left by a
# previous install so users don't see two venv directories side by side.
LEGACY_VENV="$DAEMON_DIR/untracked/venv"
if [ -d "$LEGACY_VENV" ] && [ "$VENV_PATH" != "$LEGACY_VENV" ]; then
    print_info "Removing legacy pre-v3.7.0 venv at $LEGACY_VENV"
    rm -rf "$LEGACY_VENV"
fi

# ============================================================
# Step 4: Deploy hook scripts
# ============================================================

log_step "4" "Deploying hook scripts"
deploy_all_hooks "$PROJECT_ROOT" "$DAEMON_DIR" "normal"

# ============================================================
# Step 5: Deploy settings.json
# ============================================================

log_step "5" "Deploying settings.json"

TARGET_SETTINGS="$PROJECT_ROOT/.claude/settings.json"

if [ -f "$SETTINGS_JSON_SOURCE" ]; then
    # Backup existing settings.json if present
    if [ -f "$TARGET_SETTINGS" ]; then
        backup_timestamp=$(date +%Y%m%d-%H%M%S)
        cp "$TARGET_SETTINGS" "${TARGET_SETTINGS}.bak-${backup_timestamp}"
        print_verbose "Backed up existing settings.json"
    fi

    cp "$SETTINGS_JSON_SOURCE" "$TARGET_SETTINGS"
    print_success "Deployed settings.json"
else
    # Generate settings.json if template not available (older daemon versions)
    print_warning "settings.json not found in daemon repo, generating..."
    generate_settings_json "$PROJECT_ROOT"
fi

# ============================================================
# Step 6: Deploy hooks-daemon.env
# ============================================================

log_step "6" "Deploying hooks-daemon.env"

ENV_FILE="$PROJECT_ROOT/.claude/hooks-daemon.env"

cat > "$ENV_FILE" <<'ENV_EOF'
# Claude Code Hooks Daemon - Environment Configuration
#
# This file overrides default daemon paths for self-installation or custom setups.
# It is sourced by init.sh before daemon startup.

# Root directory of the hooks daemon installation
# Default: $PROJECT_PATH/.claude/hooks-daemon
HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/.claude/hooks-daemon"
ENV_EOF

print_success "Deployed hooks-daemon.env"

# ============================================================
# Step 7: Deploy config
# ============================================================

log_step "7" "Deploying configuration"

TARGET_CONFIG="$PROJECT_ROOT/.claude/hooks-daemon.yaml"

if [ -f "$TARGET_CONFIG" ]; then
    print_info "Config already exists, keeping existing configuration"
else
    if [ -f "$EXAMPLE_CONFIG" ]; then
        cp "$EXAMPLE_CONFIG" "$TARGET_CONFIG"
        print_success "Deployed default config from example"
    else
        print_warning "No example config found at: $EXAMPLE_CONFIG"
        print_info "You'll need to create a config manually"
    fi
fi

# ============================================================
# Step 8: Setup .gitignore
# ============================================================

log_step "8" "Setting up .gitignore"
setup_all_gitignores "$PROJECT_ROOT" "$DAEMON_DIR" "normal" || print_warning ".gitignore setup had warnings (non-fatal)"

# ============================================================
# Step 9: Deploy slash commands
# ============================================================

log_step "9" "Deploying slash commands"
deploy_slash_commands "$PROJECT_ROOT" "$DAEMON_DIR" "normal"

# ============================================================
# Step 10: Deploy skills
# ============================================================

log_step "10" "Deploying user-facing skills"

"$VENV_PYTHON" -c "
from pathlib import Path
from claude_code_hooks_daemon.install.skills import deploy_skills

daemon_source = Path('$DAEMON_DIR')
project_root = Path('$PROJECT_ROOT')

try:
    deploy_skills(daemon_source, project_root)
    print('✓ Skills deployed to .claude/skills/hooks-daemon/')
except Exception as e:
    print(f'✗ Skill deployment failed: {e}')
    exit(1)
"

# ============================================================
# Step 11: Start daemon and verify
# ============================================================

log_step "11" "Starting daemon"
restart_daemon_verified "$VENV_PYTHON"

# ============================================================
# Step 12: Post-install validation
# ============================================================

log_step "12" "Running post-install validation"
run_post_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" "false"

# ============================================================
# Step 13: Generate handler documentation
# ============================================================

log_step "13" "Generating handler documentation"
if "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli generate-docs --project-root "$PROJECT_ROOT"; then
    print_success "Generated .claude/HOOKS-DAEMON.md"
else
    print_warning "Failed to generate handler docs (non-fatal)"
fi

# ============================================================
# Step 14: Plan workflow deployment (config-driven SSoT — Plan 00136)
# ============================================================
#
# Deployment is derived from the config the daemon actually reads
# (config.plan_workflow.enabled), NOT from a separate install-time switch.
# The legacy PLAN_WORKFLOW=yes env var was a second, orthogonal source of
# truth that never ran on upgrade — removed entirely for one clear SSoT.

log_step "14" "Deploying plan workflow (if enabled in config)"

if "$VENV_PYTHON" -c "
from pathlib import Path
from claude_code_hooks_daemon.install.plan_workflow import deploy_plan_workflow_if_enabled

result = deploy_plan_workflow_if_enabled(Path('$PROJECT_ROOT'), Path('$TARGET_CONFIG'))
for msg in result.messages:
    print(f'  -> {msg}')
"; then
    print_success "Plan workflow deployment complete"
else
    print_warning "Plan workflow deployment had issues (non-fatal)"
fi

# ============================================================
# Step 14b: Deploy ccy PTY supervisor (config-gated — Plan 00147)
# ============================================================
#
# Deploys .claude/ccy/claude-supervise.py into the project's .claude/ccy/ when
# a .claude/ccy/ directory is present and ccy.deploy_supervisor is not false.
# Sources the tracked script from the daemon clone ($DAEMON_DIR/.claude/ccy/).

log_step "14b" "Deploying ccy supervisor (if a .claude/ccy/ project)"

if "$VENV_PYTHON" -c "
from pathlib import Path
from claude_code_hooks_daemon.install.ccy_supervisor import deploy_ccy_supervisor_if_enabled

result = deploy_ccy_supervisor_if_enabled(Path('$DAEMON_DIR'), Path('$PROJECT_ROOT'), Path('$TARGET_CONFIG'))
for msg in result.messages:
    print(f'  -> {msg}')
if result.recommend_enable:
    print('  -> TIP: set ccy.deploy_supervisor: true in .claude/hooks-daemon.yaml to keep this on')
"; then
    print_success "ccy supervisor deployment complete"
else
    print_warning "ccy supervisor deployment had issues (non-fatal)"
fi

# ============================================================
# Step 15: Handler profile (optional, via HANDLER_PROFILE=recommended|strict)
# ============================================================

HANDLER_PROFILE="${HANDLER_PROFILE:-minimal}"

if [ "$HANDLER_PROFILE" != "minimal" ]; then
    log_step "15" "Applying handler profile: $HANDLER_PROFILE"

    if "$VENV_PYTHON" -c "
from pathlib import Path
from claude_code_hooks_daemon.install.handler_profiles import apply_profile

config_path = Path('$TARGET_CONFIG')
try:
    count = apply_profile(config_path, '$HANDLER_PROFILE')
    print(f'  Enabled {count} additional handler(s)')
except ValueError as e:
    print(f'Error: {e}')
    exit(1)
"; then
        print_success "Profile '$HANDLER_PROFILE' applied"
    else
        print_warning "Profile application had issues (non-fatal)"
    fi

    # Restart daemon to pick up new config
    restart_daemon_verified "$VENV_PYTHON"

    # Regenerate docs with new handler state
    if "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli generate-docs --project-root "$PROJECT_ROOT"; then
        print_success "Regenerated .claude/HOOKS-DAEMON.md"
    fi
else
    log_step "15" "Handler profile: minimal (default)"
    print_info "HANDLER_PROFILE=recommended|strict seeds more handlers at install time"
fi

# ============================================================
# Complete
# ============================================================

print_header "Installation Complete"

print_success "Claude Code Hooks Daemon installed successfully!"
echo ""
echo "  Project:  $PROJECT_ROOT"
echo "  Daemon:   $DAEMON_DIR"
echo "  Config:   $TARGET_CONFIG"
echo "  Venv:     $VENV_PATH"
echo ""
if [ "$HANDLER_PROFILE" != "minimal" ]; then
echo "  Profile:  $HANDLER_PROFILE"
fi
echo ""
echo "Next steps:"
echo "  1. Review config:   vim $TARGET_CONFIG"
echo "  2. Commit hooks:    git add .claude/hooks/ .claude/settings.json .claude/hooks-daemon.yaml"
echo "  3. Hooks activate automatically on next tool use"
echo ""
echo "Customisation (edit $TARGET_CONFIG — it is the single source of truth):"
echo "  Profiles:  HANDLER_PROFILE=recommended|strict seeds extra handlers at"
echo "             FRESH-INSTALL time only; afterwards edit enabled: flags in config"
echo "  Plans:     edit plan_workflow.enabled in $TARGET_CONFIG (deployed when enabled)"
echo ""
echo "Daemon management:"
echo "  Status:   $VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status"
echo "  Restart:  $VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart"
echo ""

exit 0
