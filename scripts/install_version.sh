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

# Derived paths
VENV_PYTHON="$DAEMON_DIR/untracked/venv/bin/python"
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
check_all_prerequisites "true"

# ============================================================
# Step 3: Virtual environment
# ============================================================

log_step "3" "Creating virtual environment"
create_venv "$DAEMON_DIR"

if ! verify_venv "$VENV_PYTHON" "$DAEMON_DIR"; then
    fail_fast "Virtual environment verification failed"
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
# Step 10: Start daemon and verify
# ============================================================

log_step "10" "Starting daemon"
restart_daemon_verified "$VENV_PYTHON"

# ============================================================
# Step 11: Post-install validation
# ============================================================

log_step "11" "Running post-install validation"
run_post_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" "false"

# ============================================================
# Complete
# ============================================================

print_header "Installation Complete"

print_success "Claude Code Hooks Daemon installed successfully!"
echo ""
echo "  Project:  $PROJECT_ROOT"
echo "  Daemon:   $DAEMON_DIR"
echo "  Config:   $TARGET_CONFIG"
echo "  Venv:     $DAEMON_DIR/untracked/venv/"
echo ""
echo "Next steps:"
echo "  1. Review config:   vim $TARGET_CONFIG"
echo "  2. Commit hooks:    git add .claude/hooks/ .claude/settings.json .claude/hooks-daemon.yaml"
echo "  3. Hooks activate automatically on next tool use"
echo ""
echo "Daemon management:"
echo "  Status:   $VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status"
echo "  Restart:  $VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart"
echo ""

exit 0
