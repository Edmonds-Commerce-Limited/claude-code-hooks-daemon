#!/bin/bash
#
# slash_commands.sh - Unified slash command deployment
#
# Deploys slash command files from daemon to project .claude/commands/.
# Handles both copy (normal mode) and symlink (self-install mode).
#
# Usage:
#   source "$(dirname "$0")/install/slash_commands.sh"
#   deploy_slash_commands "$PROJECT_ROOT" "$DAEMON_DIR" "$INSTALL_MODE"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

#
# deploy_slash_commands() - Deploy slash command files to project
#
# Copies or symlinks slash command files from daemon to project.
# In self-install mode, creates symlinks to avoid duplication.
# In normal mode, copies files for independence from daemon updates.
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - install_mode: "self-install" or "normal"
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
deploy_slash_commands() {
    local project_root="$1"
    local daemon_dir="$2"
    local install_mode="$3"

    if [ -z "$project_root" ] || [ -z "$daemon_dir" ]; then
        print_error "deploy_slash_commands: project_root and daemon_dir required"
        return 1
    fi

    local source_commands_dir="$daemon_dir/.claude/commands"
    local target_commands_dir="$project_root/.claude/commands"

    # Check if source commands directory exists
    if [ ! -d "$source_commands_dir" ]; then
        print_verbose "No slash commands directory in daemon: $source_commands_dir"
        return 0
    fi

    print_verbose "Deploying slash commands..."

    # Create target directory
    mkdir -p "$target_commands_dir"

    # Get list of command files
    local command_files
    command_files=$(find "$source_commands_dir" -maxdepth 1 -type f -name "*.md" 2>/dev/null)

    if [ -z "$command_files" ]; then
        print_verbose "No slash command files found in: $source_commands_dir"
        return 0
    fi

    local deployed_count=0

    for source_file in $command_files; do
        local file_name
        file_name=$(basename "$source_file")
        local target_file="$target_commands_dir/$file_name"

        if [ "$install_mode" = "self-install" ]; then
            # Self-install mode: create symlinks
            if [ -L "$target_file" ] || [ -f "$target_file" ]; then
                rm -f "$target_file"
            fi
            ln -s "$source_file" "$target_file"
            print_verbose "Symlinked: $file_name"
        else
            # Normal mode: copy files
            cp "$source_file" "$target_file"
            print_verbose "Copied: $file_name"
        fi

        deployed_count=$((deployed_count + 1))
    done

    print_success "Deployed $deployed_count slash command(s)"
    return 0
}

#
# verify_slash_commands_deployed() - Verify slash commands are present
#
# Args:
#   $1 - project_root: Path to project root
#
# Returns:
#   Exit code 0 if commands are deployed, 1 if not
#
verify_slash_commands_deployed() {
    local project_root="$1"

    if [ -z "$project_root" ]; then
        return 1
    fi

    local commands_dir="$project_root/.claude/commands"

    # Check commands directory exists
    if [ ! -d "$commands_dir" ]; then
        print_verbose "Slash commands directory not found: $commands_dir"
        return 1
    fi

    # Count command files
    local command_count
    command_count=$(find "$commands_dir" -maxdepth 1 \( -type f -o -type l \) -name "*.md" 2>/dev/null | wc -l)

    if [ "$command_count" -eq 0 ]; then
        print_verbose "No slash command files found"
        return 1
    fi

    print_verbose "Slash commands verified: $command_count file(s) found"
    return 0
}

#
# list_slash_commands() - List deployed slash commands
#
# Args:
#   $1 - project_root: Path to project root
#
# Returns:
#   Prints list of slash commands to stdout
#   Exit code 0 on success
#
list_slash_commands() {
    local project_root="$1"

    if [ -z "$project_root" ]; then
        print_error "list_slash_commands: project_root required"
        return 1
    fi

    local commands_dir="$project_root/.claude/commands"

    if [ ! -d "$commands_dir" ]; then
        print_info "No slash commands directory: $commands_dir"
        return 0
    fi

    local command_files
    command_files=$(find "$commands_dir" -maxdepth 1 \( -type f -o -type l \) -name "*.md" 2>/dev/null)

    if [ -z "$command_files" ]; then
        print_info "No slash commands found"
        return 0
    fi

    print_info "Slash commands:"
    for cmd_file in $command_files; do
        local cmd_name
        cmd_name=$(basename "$cmd_file" .md)

        # Check if it's a symlink
        if [ -L "$cmd_file" ]; then
            local target
            target=$(readlink "$cmd_file")
            echo "  /$cmd_name (symlink -> $target)"
        else
            echo "  /$cmd_name"
        fi
    done

    return 0
}

#
# remove_slash_command() - Remove a specific slash command
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - command_name: Name of command to remove (without .md extension)
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
remove_slash_command() {
    local project_root="$1"
    local command_name="$2"

    if [ -z "$project_root" ] || [ -z "$command_name" ]; then
        print_error "remove_slash_command: project_root and command_name required"
        return 1
    fi

    local command_file="$project_root/.claude/commands/${command_name}.md"

    if [ ! -f "$command_file" ] && [ ! -L "$command_file" ]; then
        print_verbose "Slash command not found: /$command_name"
        return 0
    fi

    rm -f "$command_file"
    print_success "Removed slash command: /$command_name"
    return 0
}

#
# deploy_single_slash_command() - Deploy a specific slash command
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - install_mode: "self-install" or "normal"
#   $4 - command_name: Name of command to deploy (without .md extension)
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
deploy_single_slash_command() {
    local project_root="$1"
    local daemon_dir="$2"
    local install_mode="$3"
    local command_name="$4"

    if [ -z "$project_root" ] || [ -z "$daemon_dir" ] || [ -z "$command_name" ]; then
        print_error "deploy_single_slash_command: project_root, daemon_dir, and command_name required"
        return 1
    fi

    local source_file="$daemon_dir/.claude/commands/${command_name}.md"
    local target_dir="$project_root/.claude/commands"
    local target_file="$target_dir/${command_name}.md"

    if [ ! -f "$source_file" ]; then
        print_error "Source slash command not found: $source_file"
        return 1
    fi

    # Create target directory
    mkdir -p "$target_dir"

    if [ "$install_mode" = "self-install" ]; then
        # Self-install mode: create symlink
        if [ -L "$target_file" ] || [ -f "$target_file" ]; then
            rm -f "$target_file"
        fi
        ln -s "$source_file" "$target_file"
        print_success "Symlinked slash command: /$command_name"
    else
        # Normal mode: copy file
        cp "$source_file" "$target_file"
        print_success "Copied slash command: /$command_name"
    fi

    return 0
}
