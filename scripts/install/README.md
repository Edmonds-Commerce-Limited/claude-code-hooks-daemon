# Install/Upgrade Shared Library

Modular bash library used by both `install_version.sh` (Layer 2 install) and `upgrade_version.sh` (Layer 2 upgrade). Each module provides focused functions for a single concern.

## Architecture

```
Layer 1 (curl-fetched, stable)     Layer 2 (version-specific)
  install.sh  ──exec──>  scripts/install_version.sh  ──sources──> scripts/install/*.sh
  scripts/upgrade.sh ──exec──>  scripts/upgrade_version.sh ──sources──> scripts/install/*.sh
```

Layer 1 scripts are minimal (~100 lines), handle cloning/detection, then `exec` into Layer 2. Layer 2 orchestrators source this shared library and call functions in sequence.

## Modules

### output.sh - Formatted Console Output

Colored output with consistent prefix formatting. All other modules depend on this.

| Function | Args | Description |
|----------|------|-------------|
| `print_header "text"` | message | Bold header line |
| `print_success "text"` | message | Green "OK" prefix |
| `print_error "text"` | message | Red "ERR" prefix (to stderr) |
| `print_warning "text"` | message | Yellow "WARN" prefix |
| `print_info "text"` | message | Blue ">>>" prefix |
| `log_step "N" "text"` | step_number, message | Numbered step: `[N] text` |
| `fail_fast "text"` | message | Print error and `exit 1` |
| `print_verbose "text"` | message | Only prints if `VERBOSE=true` |

Colors auto-disable when stdout is not a terminal.

### mode_guard.sh - Self-Install Mode Protection

Prevents install/upgrade scripts from running in the daemon's own development repository.

| Function | Args | Description |
|----------|------|-------------|
| `detect_self_install_mode` | none | Returns 0 if self-install mode detected |
| `ensure_normal_mode_only` | none | Aborts with error if self-install mode |
| `require_normal_mode` | none | Alias for `ensure_normal_mode_only` |
| `get_install_mode` | none | Prints "self-install" or "normal" |

### prerequisites.sh - System Requirements

Validates required tools and Python version.

| Function | Args | Description |
|----------|------|-------------|
| `check_git` | none | Verifies git is installed |
| `check_uv` | none | Verifies uv is installed (installs if missing) |
| `check_all_prerequisites` | none | Runs all prerequisite checks |
| `get_python_version` | none | Prints Python version string |
| `get_python_major_minor` | none | Prints major.minor (e.g., "3.12") |

### project_detection.sh - Project Root Discovery

Locates project root by walking up directory tree looking for `.claude/hooks-daemon.yaml` or `.claude/`.

| Function | Args | Description |
|----------|------|-------------|
| `detect_project_root` | none | Walks up from cwd, prints project root |
| `detect_project_root_current_dir` | none | Checks only current directory |
| `validate_project_structure` | project_root | Validates `.claude/` and `.git/` exist |
| `detect_install_mode` | project_root | Prints "self-install" or "normal" |
| `get_daemon_dir` | project_root | Prints daemon directory path |
| `get_venv_python` | daemon_dir | Prints path to venv python binary |
| `detect_and_validate_project` | none | Combined detect + validate |

### venv.sh - Virtual Environment Management

Creates, recreates, and verifies isolated Python virtual environments.

| Function | Args | Description |
|----------|------|-------------|
| `create_venv` | daemon_dir | Creates venv at `{daemon_dir}/untracked/venv/` |
| `recreate_venv` | daemon_dir | Removes and recreates venv (for upgrades) |
| `verify_venv` | daemon_dir | Checks venv exists and python works |
| `get_venv_python_version` | daemon_dir | Prints venv Python version |
| `install_package_editable` | daemon_dir | Runs `pip install -e .` in venv |

Uses `uv` for venv creation when available, falls back to `python3 -m venv`.

### hooks_deploy.sh - Hook Script Deployment

Deploys hook forwarder scripts to `.claude/hooks/`.

| Function | Args | Description |
|----------|------|-------------|
| `deploy_hook_scripts` | project_root, daemon_dir | Deploys all hook forwarders |
| `deploy_init_script` | project_root, daemon_dir | Deploys `.claude/init.sh` |
| `set_hook_permissions` | project_root | Sets executable permissions on hooks |
| `deploy_all_hooks` | project_root, daemon_dir | Combined: scripts + init + permissions |
| `verify_hooks_deployed` | project_root | Verifies all expected hooks exist |

### daemon_control.sh - Daemon Lifecycle

Start, stop, restart the daemon process with verification.

| Function | Args | Description |
|----------|------|-------------|
| `stop_daemon_safe` | venv_python | Graceful stop with timeout |
| `start_daemon_safe` | venv_python | Start and verify running |
| `get_daemon_status` | venv_python | Prints daemon status |
| `check_daemon_running` | venv_python | Returns 0 if running |
| `restart_daemon_verified` | venv_python | Stop + start + verify |
| `wait_for_daemon_stop` | venv_python, timeout | Wait for daemon to fully stop |
| `restart_daemon_quick` | venv_python | Restart without full verification |

### gitignore.sh - Gitignore Management

Ensures proper `.gitignore` files exist to exclude generated/runtime files.

| Function | Args | Description |
|----------|------|-------------|
| `ensure_root_gitignore` | project_root | Ensures project root `.gitignore` has daemon entries |
| `verify_claude_gitignore` | project_root | Checks `.claude/.gitignore` exists and is correct |
| `create_daemon_untracked_gitignore` | daemon_dir | Creates `untracked/.gitignore` |
| `show_gitignore_instructions` | project_root | Displays manual gitignore setup instructions |
| `verify_gitignore_complete` | project_root | Full verification of all gitignore files |
| `setup_all_gitignores` | project_root, daemon_dir | Combined setup for all gitignore files |

### validation.sh - Pre/Post Install Validation

Validates installation state before and after operations.

| Function | Args | Description |
|----------|------|-------------|
| `run_pre_install_checks` | project_root, daemon_dir | Pre-install validation (git clean, no conflicts) |
| `run_post_install_checks` | project_root, daemon_dir | Post-install validation (hooks, venv, daemon) |
| `cleanup_stale_runtime_files` | daemon_dir | Removes stale .sock/.pid files |
| `verify_config_valid` | config_path | Validates YAML config syntax and structure |

### rollback.sh - State Snapshot and Rollback

Creates snapshots of installation state for upgrade rollback.

| Function | Args | Description |
|----------|------|-------------|
| `get_snapshot_dir` | daemon_dir | Prints snapshot directory path |
| `create_state_snapshot` | daemon_dir, project_root | Saves hooks, config, settings to snapshot |
| `restore_state_snapshot` | snapshot_path, project_root | Restores from snapshot (full rollback) |
| `list_snapshots` | daemon_dir | Lists available snapshots |
| `cleanup_old_snapshots` | daemon_dir, keep_count | Removes old snapshots, keeps N most recent |
| `get_latest_snapshot` | daemon_dir | Prints path to most recent snapshot |

Snapshots are stored at `{daemon_dir}/untracked/upgrade-snapshots/{timestamp}/` and contain a `manifest.json` plus copies of all critical files.

### slash_commands.sh - Slash Command Deployment

Deploys Claude Code slash command files to `.claude/commands/`.

| Function | Args | Description |
|----------|------|-------------|
| `deploy_slash_commands` | project_root, daemon_dir | Deploys all slash commands |
| `verify_slash_commands_deployed` | project_root | Verifies slash commands exist |
| `list_slash_commands` | daemon_dir | Lists available slash commands |
| `remove_slash_command` | project_root, name | Removes a specific slash command |
| `deploy_single_slash_command` | project_root, daemon_dir, name | Deploys one slash command |

### config_preserve.sh - Config Preservation (Upgrade)

Bridges the Python config preservation CLI for use in bash upgrade orchestration. Uses diff/merge/validate pipeline to preserve user customizations across upgrades.

| Function | Args | Description |
|----------|------|-------------|
| `backup_config` | config_path | Copies config to timestamped backup, prints backup path |
| `extract_custom_config` | old_default, user_config, venv_python | Diffs to find user customizations |
| `merge_custom_config` | new_default, custom_diff, venv_python | Merges customizations into new default |
| `validate_merged_config` | merged_config, venv_python | Validates merged config structure |
| `report_incompatibilities` | old_default, new_default, venv_python | Reports breaking changes between versions |
| `preserve_config_for_upgrade` | old_default, user_config, new_default, venv_python | Full pipeline: diff + merge + validate |

Calls Python CLI via `$venv_python -m claude_code_hooks_daemon.daemon.cli config-diff|config-merge|config-validate`.

## Test Modules

Test files (`test_*.sh`) provide manual verification for each module. They are not part of the library and should not be sourced by orchestrators.

| File | Tests |
|------|-------|
| `test_output_manual.sh` | All output functions with color |
| `test_prerequisites_manual.sh` | Prerequisite detection |
| `test_venv_manual.sh` | Venv creation/verification |
| `test_gitignore_manual.sh` | Gitignore setup/verification |
| `test_validation_manual.sh` | Pre/post install checks |
| `test_slash_commands_manual.sh` | Slash command deployment |
| `test_helpers.sh` | Shared test utilities (assertions, temp dirs) |

## Usage Pattern

Orchestrators source modules they need:

```bash
#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$1"
DAEMON_DIR="$2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source shared library
source "$SCRIPT_DIR/install/output.sh"
source "$SCRIPT_DIR/install/prerequisites.sh"
source "$SCRIPT_DIR/install/venv.sh"
# ... etc

# Use functions
print_header "Installing Claude Code Hooks Daemon"
log_step "1" "Checking prerequisites"
check_all_prerequisites
log_step "2" "Creating virtual environment"
create_venv "$DAEMON_DIR"
```

## Maintenance

- Each module is self-contained with no cross-module dependencies (except all depend on `output.sh`)
- Functions use `fail_fast` for unrecoverable errors (prints message and exits)
- All functions that need project/daemon paths take them as arguments (no globals)
- Add new modules for new concerns; keep existing modules focused
