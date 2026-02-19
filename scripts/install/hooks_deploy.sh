#!/bin/bash
#
# hooks_deploy.sh - Unified hook script deployment
#
# Deploys hook scripts from daemon installation to project .claude/hooks/.
# Single source of truth: actual hook scripts in daemon's .claude/hooks/ directory.
# Handles both normal and self-install modes.
#
# Usage:
#   source "$(dirname "$0")/lib/hooks_deploy.sh"
#   deploy_all_hooks "$PROJECT_ROOT" "$DAEMON_DIR" "$INSTALL_MODE"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

#
# deploy_hook_scripts() - Deploy hook forwarder scripts to project
#
# Copies hook scripts from daemon installation to project .claude/hooks/.
# In self-install mode, creates symlinks instead of copies.
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - install_mode: "self-install" or "normal"
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
deploy_hook_scripts() {
    local project_root="$1"
    local daemon_dir="$2"
    local install_mode="$3"

    if [ -z "$project_root" ] || [ -z "$daemon_dir" ]; then
        print_error "deploy_hook_scripts: project_root and daemon_dir required"
        return 1
    fi

    local source_hooks="$daemon_dir/.claude/hooks"
    local target_hooks="$project_root/.claude/hooks"

    # CRITICAL: In self-install mode, source and target are THE SAME.
    # Do NOT create symlinks or copy - hooks are already in place.
    if [ "$install_mode" = "self-install" ]; then
        if [ "$source_hooks" = "$target_hooks" ]; then
            print_verbose "Self-install mode: hooks already in place, skipping deployment"
            return 0
        fi
    fi

    if [ ! -d "$source_hooks" ]; then
        print_error "Source hooks directory not found: $source_hooks"
        return 1
    fi

    print_info "Deploying hook scripts..."

    # Create target directory
    mkdir -p "$target_hooks"

    # Get list of hook scripts (exclude directories and hidden files)
    local hook_files
    hook_files=$(find "$source_hooks" -maxdepth 1 -type f ! -name ".*" -exec basename {} \;)

    if [ -z "$hook_files" ]; then
        print_warning "No hook scripts found in: $source_hooks"
        return 0
    fi

    local deployed_count=0

    for hook_file in $hook_files; do
        local source="$source_hooks/$hook_file"
        local target="$target_hooks/$hook_file"

        # Normal mode: copy files (never symlink hooks)
        cp "$source" "$target"
        print_verbose "Copied: $hook_file"

        deployed_count=$((deployed_count + 1))
    done

    print_success "Deployed $deployed_count hook scripts"
    return 0
}

#
# deploy_init_script() - Deploy init.sh to project
#
# Copies init.sh script from daemon installation to project .claude/.
# In self-install mode, creates symlink instead of copy.
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - install_mode: "self-install" or "normal"
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
deploy_init_script() {
    local project_root="$1"
    local daemon_dir="$2"
    local install_mode="$3"

    if [ -z "$project_root" ] || [ -z "$daemon_dir" ]; then
        print_error "deploy_init_script: project_root and daemon_dir required"
        return 1
    fi

    local source_init="$daemon_dir/init.sh"
    local target_init="$project_root/.claude/init.sh"

    # CRITICAL: In self-install mode, check if source and target are the same
    if [ "$install_mode" = "self-install" ]; then
        # If init.sh is already at target location, skip
        if [ -f "$target_init" ] && [ "$(readlink -f "$source_init" 2>/dev/null || echo "$source_init")" = "$(readlink -f "$target_init" 2>/dev/null || echo "$target_init")" ]; then
            print_verbose "Self-install mode: init.sh already in place, skipping deployment"
            return 0
        fi
    fi

    if [ ! -f "$source_init" ]; then
        print_error "Source init.sh not found: $source_init"
        return 1
    fi

    print_verbose "Deploying init.sh..."

    # Normal mode: copy file (never symlink)
    cp "$source_init" "$target_init"
    print_verbose "Copied init.sh"

    return 0
}

#
# set_hook_permissions() - Ensure hook scripts are executable
#
# Sets executable permissions on all hook scripts.
# Handles git core.fileMode=false case by checking if permissions stick.
#
# Args:
#   $1 - project_root: Path to project root
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
set_hook_permissions() {
    local project_root="$1"

    if [ -z "$project_root" ]; then
        print_error "set_hook_permissions: project_root required"
        return 1
    fi

    local hooks_dir="$project_root/.claude/hooks"

    if [ ! -d "$hooks_dir" ]; then
        print_warning "Hooks directory not found: $hooks_dir"
        return 0
    fi

    print_verbose "Setting executable permissions on hook scripts..."

    # Find all regular files (not symlinks) in hooks directory
    local hook_files
    hook_files=$(find "$hooks_dir" -maxdepth 1 -type f ! -name ".*")

    if [ -z "$hook_files" ]; then
        print_verbose "No hook files found to set permissions"
        return 0
    fi

    local chmod_count=0

    for hook_file in $hook_files; do
        chmod +x "$hook_file" 2>/dev/null || true
        chmod_count=$((chmod_count + 1))
    done

    # Check if permissions stuck (git core.fileMode=false detection)
    local test_file
    test_file=$(echo "$hook_files" | awk 'NR==1')
    if [ -f "$test_file" ] && [ ! -x "$test_file" ]; then
        print_warning "Hook permissions may not persist (git core.fileMode=false)"
        print_info "Hooks will still work, but permissions won't be tracked by git"
    else
        print_verbose "Set executable on $chmod_count hook scripts"
    fi

    return 0
}

#
# deploy_all_hooks() - Complete hook deployment workflow
#
# Deploys all hooks, init script, and sets permissions.
# This is the recommended high-level function.
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - install_mode: "self-install" or "normal"
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
deploy_all_hooks() {
    local project_root="$1"
    local daemon_dir="$2"
    local install_mode="$3"

    if [ -z "$project_root" ] || [ -z "$daemon_dir" ]; then
        fail_fast "deploy_all_hooks: project_root and daemon_dir required"
    fi

    print_info "Deploying hooks to project..."

    # Deploy hook scripts
    if ! deploy_hook_scripts "$project_root" "$daemon_dir" "$install_mode"; then
        print_error "Failed to deploy hook scripts"
        return 1
    fi

    # Deploy init script
    if ! deploy_init_script "$project_root" "$daemon_dir" "$install_mode"; then
        print_error "Failed to deploy init.sh"
        return 1
    fi

    # Set permissions (only needed in normal mode, symlinks inherit permissions)
    if [ "$install_mode" != "self-install" ]; then
        if ! set_hook_permissions "$project_root"; then
            print_warning "Failed to set hook permissions (may still work)"
        fi
    fi

    print_success "Hooks deployed successfully"
    return 0
}

#
# verify_hooks_deployed() - Verify hooks are present and executable
#
# Args:
#   $1 - project_root: Path to project root
#
# Returns:
#   Exit code 0 if hooks are deployed, 1 if not
#
verify_hooks_deployed() {
    local project_root="$1"

    if [ -z "$project_root" ]; then
        return 1
    fi

    local hooks_dir="$project_root/.claude/hooks"
    local init_script="$project_root/.claude/init.sh"

    # Check hooks directory exists
    if [ ! -d "$hooks_dir" ]; then
        print_error "Hooks directory not found: $hooks_dir"
        return 1
    fi

    # Check init.sh exists
    if [ ! -f "$init_script" ]; then
        print_error "init.sh not found: $init_script"
        return 1
    fi

    # Count hook files
    local hook_count
    hook_count=$(find "$hooks_dir" -maxdepth 1 -type f -o -type l | wc -l)

    if [ "$hook_count" -lt 5 ]; then
        print_warning "Only $hook_count hook scripts found (expected at least 5)"
        return 1
    fi

    print_verbose "Hooks verified: $hook_count scripts found"
    return 0
}
