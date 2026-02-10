#!/bin/bash
#
# config_preserve.sh - Config preservation for upgrades
#
# Wraps the Python config diff/merge/validate CLI commands to provide
# config preservation during upgrades. Follows the "Upgrade = Clean
# Reinstall + Config Preservation" philosophy.
#
# Usage:
#   source "$(dirname "$0")/install/config_preserve.sh"
#   backup_config "$PROJECT_ROOT"
#   extract_custom_config "$VENV_PYTHON" "$USER_CONFIG" "$DEFAULT_CONFIG"
#   merge_custom_config "$VENV_PYTHON" "$USER_CONFIG" "$OLD_DEFAULT" "$NEW_DEFAULT"
#   validate_merged_config "$VENV_PYTHON" "$MERGED_CONFIG"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

#
# backup_config() - Create timestamped backup of config file
#
# Creates a backup copy of the config file with timestamp suffix.
# Safe to call if config file doesn't exist (returns 0).
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - backup_dir (optional): Directory for backup file
#        Defaults to same directory as config file
#
# Returns:
#   Prints backup file path to stdout
#   Exit code 0 on success, 1 on failure
#
backup_config() {
    local project_root="$1"
    local backup_dir="${2:-}"

    if [ -z "$project_root" ]; then
        print_error "backup_config: project_root parameter required"
        return 1
    fi

    local config_file="$project_root/.claude/hooks-daemon.yaml"

    if [ ! -f "$config_file" ]; then
        print_verbose "No config file to backup: $config_file"
        return 0
    fi

    local timestamp
    timestamp=$(date +%Y%m%d-%H%M%S)

    local backup_file
    if [ -n "$backup_dir" ]; then
        mkdir -p "$backup_dir"
        backup_file="$backup_dir/hooks-daemon.yaml.backup-${timestamp}"
    else
        backup_file="${config_file}.backup-${timestamp}"
    fi

    cp "$config_file" "$backup_file"
    print_success "Config backed up to: $backup_file" >&2
    echo "$backup_file"
    return 0
}

#
# extract_custom_config() - Extract user customizations from config
#
# Calls the Python config-diff CLI to compare user config against
# the default config and extract customizations.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - user_config: Path to user's current config YAML
#   $3 - default_config: Path to default/example config YAML
#
# Returns:
#   Prints JSON diff result to stdout
#   Exit code 0 on success, 1 on failure
#
extract_custom_config() {
    local venv_python="$1"
    local user_config="$2"
    local default_config="$3"

    if [ -z "$venv_python" ] || [ -z "$user_config" ] || [ -z "$default_config" ]; then
        print_error "extract_custom_config: venv_python, user_config, and default_config required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    if [ ! -f "$user_config" ]; then
        print_error "User config not found: $user_config"
        return 1
    fi

    if [ ! -f "$default_config" ]; then
        print_error "Default config not found: $default_config"
        return 1
    fi

    print_verbose "Extracting customizations from config..."

    local diff_output
    diff_output=$("$venv_python" -m claude_code_hooks_daemon.daemon.cli config-diff "$user_config" "$default_config" 2>&1)
    local exit_code=$?

    if [ $exit_code -ne 0 ]; then
        print_error "Config diff failed: $diff_output"
        return 1
    fi

    print_verbose "Config customizations extracted"
    echo "$diff_output"
    return 0
}

#
# merge_custom_config() - Merge user customizations onto new default
#
# Calls the Python config-merge CLI to:
# 1. Diff user config vs old default to extract customizations
# 2. Apply customizations onto new default config
# 3. Return merged config + any conflicts
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - user_config: Path to user's current config YAML
#   $3 - old_default_config: Path to default config from current version
#   $4 - new_default_config: Path to default config from new version
#   $5 - output_file (optional): Path to write merged YAML config
#        If provided, extracts merged_config from JSON and writes as YAML
#
# Returns:
#   Prints JSON merge result to stdout (includes merged_config, conflicts, is_clean)
#   Exit code 0 on success, 1 on failure
#
merge_custom_config() {
    local venv_python="$1"
    local user_config="$2"
    local old_default_config="$3"
    local new_default_config="$4"
    local output_file="${5:-}"

    if [ -z "$venv_python" ] || [ -z "$user_config" ] || [ -z "$old_default_config" ] || [ -z "$new_default_config" ]; then
        print_error "merge_custom_config: venv_python, user_config, old_default_config, and new_default_config required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    for config_file in "$user_config" "$old_default_config" "$new_default_config"; do
        if [ ! -f "$config_file" ]; then
            print_error "Config file not found: $config_file"
            return 1
        fi
    done

    print_info "Merging config customizations onto new default..."

    local merge_output
    merge_output=$("$venv_python" -m claude_code_hooks_daemon.daemon.cli config-merge "$user_config" "$old_default_config" "$new_default_config" 2>&1)
    local exit_code=$?

    if [ $exit_code -ne 0 ]; then
        print_error "Config merge failed: $merge_output"
        return 1
    fi

    # If output_file specified, extract merged_config and write as YAML
    if [ -n "$output_file" ]; then
        local write_result
        write_result=$("$venv_python" -c "
import json, sys, yaml
data = json.loads('''$merge_output''')
merged = data.get('merged_config', {})
with open('$output_file', 'w') as f:
    yaml.dump(merged, f, default_flow_style=False, sort_keys=False)
print('OK')
" 2>&1)

        if [ "$write_result" != "OK" ]; then
            print_error "Failed to write merged config: $write_result"
            return 1
        fi

        print_success "Merged config written to: $output_file"
    fi

    echo "$merge_output"
    return 0
}

#
# validate_merged_config() - Validate config against Pydantic schema
#
# Calls the Python config-validate CLI to validate a config file.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - config_path: Path to config YAML to validate
#
# Returns:
#   Prints JSON validation result to stdout
#   Exit code 0 if valid, 1 if invalid or error
#
validate_merged_config() {
    local venv_python="$1"
    local config_path="$2"

    if [ -z "$venv_python" ] || [ -z "$config_path" ]; then
        print_error "validate_merged_config: venv_python and config_path required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    if [ ! -f "$config_path" ]; then
        print_error "Config file not found: $config_path"
        return 1
    fi

    print_verbose "Validating merged config..."

    local validate_output
    validate_output=$("$venv_python" -m claude_code_hooks_daemon.daemon.cli config-validate "$config_path" 2>&1)
    local exit_code=$?

    if [ $exit_code -ne 0 ]; then
        print_warning "Config validation found issues"
        echo "$validate_output"
        return 1
    fi

    print_success "Config validation passed"
    echo "$validate_output"
    return 0
}

#
# report_incompatibilities() - Display user-friendly conflict report
#
# Parses JSON merge output and displays human-readable report
# of any conflicts or incompatibilities found during merge.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - merge_json: JSON string from merge_custom_config output
#
# Returns:
#   Exit code 0 if no conflicts (is_clean=true)
#   Exit code 1 if conflicts exist (is_clean=false)
#
report_incompatibilities() {
    local venv_python="$1"
    local merge_json="$2"

    if [ -z "$venv_python" ] || [ -z "$merge_json" ]; then
        print_error "report_incompatibilities: venv_python and merge_json required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    local report_output
    report_output=$("$venv_python" -c "
import json, sys

data = json.loads('''$merge_json''')
is_clean = data.get('is_clean', True)
conflicts = data.get('conflicts', [])

if is_clean:
    print('No conflicts found - config merge was clean.')
    sys.exit(0)

print(f'Found {len(conflicts)} conflict(s) during config merge:')
print('')

for i, conflict in enumerate(conflicts, 1):
    path = conflict.get('path', 'unknown')
    ctype = conflict.get('conflict_type', 'unknown')
    desc = conflict.get('description', '')
    user_val = conflict.get('user_value')
    default_val = conflict.get('default_value')

    print(f'  {i}. [{ctype}] {path}')
    print(f'     {desc}')
    if user_val is not None:
        print(f'     Your value: {user_val}')
    if default_val is not None:
        print(f'     New default: {default_val}')
    print('')

print('Review merged config and adjust manually if needed.')
sys.exit(1)
" 2>&1)
    local exit_code=$?

    echo "$report_output"
    return $exit_code
}

#
# preserve_config_for_upgrade() - Complete config preservation workflow
#
# High-level function that performs the full config preservation flow:
# 1. Backup current config
# 2. Extract customizations (diff against old default)
# 3. Merge customizations onto new default
# 4. Validate merged config
# 5. Report any incompatibilities
# 6. Write merged config to destination
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - project_root: Path to project root
#   $3 - old_default_config: Path to default config from current version
#   $4 - new_default_config: Path to default config from new version
#   $5 - backup_dir (optional): Directory for backup file
#
# Returns:
#   Exit code 0 on success (clean merge or merge with warnings)
#   Exit code 1 on failure
#
preserve_config_for_upgrade() {
    local venv_python="$1"
    local project_root="$2"
    local old_default_config="$3"
    local new_default_config="$4"
    local backup_dir="${5:-}"

    if [ -z "$venv_python" ] || [ -z "$project_root" ] || [ -z "$old_default_config" ] || [ -z "$new_default_config" ]; then
        print_error "preserve_config_for_upgrade: venv_python, project_root, old_default_config, and new_default_config required"
        return 1
    fi

    local config_file="$project_root/.claude/hooks-daemon.yaml"

    # If no user config exists, just copy new default
    if [ ! -f "$config_file" ]; then
        print_info "No existing config - using new default"
        cp "$new_default_config" "$config_file"
        print_success "Default config installed"
        return 0
    fi

    # Step 1: Backup
    print_info "Step 1/5: Backing up current config..."
    local backup_path
    backup_path=$(backup_config "$project_root" "$backup_dir")

    # Step 2: Merge (includes diff + apply)
    print_info "Step 2/5: Merging customizations onto new default..."
    local merge_output
    merge_output=$(merge_custom_config "$venv_python" "$config_file" "$old_default_config" "$new_default_config" "$config_file")
    local merge_exit=$?

    if [ $merge_exit -ne 0 ]; then
        print_error "Config merge failed"
        # Restore backup
        if [ -n "$backup_path" ] && [ -f "$backup_path" ]; then
            cp "$backup_path" "$config_file"
            print_warning "Restored config from backup"
        fi
        return 1
    fi

    # Step 3: Validate
    print_info "Step 3/5: Validating merged config..."
    local validate_output
    validate_output=$(validate_merged_config "$venv_python" "$config_file")
    local validate_exit=$?

    if [ $validate_exit -ne 0 ]; then
        print_warning "Merged config has validation issues"
        echo "$validate_output"
        # Don't restore backup - let user see the merged config
        # They can manually fix or use the backup
        print_info "Backup available at: $backup_path"
    else
        print_success "Merged config is valid"
    fi

    # Step 4: Report incompatibilities
    print_info "Step 4/5: Checking for conflicts..."
    report_incompatibilities "$venv_python" "$merge_output"
    local report_exit=$?

    # Step 5: Summary
    print_info "Step 5/5: Config preservation summary"

    if [ $report_exit -eq 0 ] && [ $validate_exit -eq 0 ]; then
        print_success "Config preserved cleanly - all customizations applied"
        return 0
    elif [ $validate_exit -eq 0 ]; then
        print_warning "Config preserved with conflicts (see above)"
        print_info "Backup: $backup_path"
        return 0
    else
        print_warning "Config preserved but has validation issues"
        print_info "Backup: $backup_path"
        print_info "You may need to manually adjust: $config_file"
        return 0
    fi
}
