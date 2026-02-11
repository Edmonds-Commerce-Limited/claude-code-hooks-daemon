#!/bin/bash
#
# gitignore.sh - Unified .gitignore management for install/upgrade
#
# Manages .gitignore entries for daemon installation.
# Ensures both root .gitignore and .claude/.gitignore are properly configured.
#
# Usage:
#   source "$(dirname "$0")/install/gitignore.sh"
#   ensure_root_gitignore "$PROJECT_ROOT" "$INSTALL_MODE"
#   verify_claude_gitignore "$PROJECT_ROOT"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

# Expected .gitignore entries
readonly DAEMON_GITIGNORE_ENTRY=".claude/hooks-daemon/"
readonly UNTRACKED_GITIGNORE_ENTRY="/untracked/"

#
# ensure_root_gitignore() - Ensure root .gitignore has daemon entry
#
# Adds .claude/hooks-daemon/ to root .gitignore if not present.
# In self-install mode, adds untracked/ instead.
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - install_mode: "self-install" or "normal"
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
ensure_root_gitignore() {
    local project_root="$1"
    local install_mode="$2"

    if [ -z "$project_root" ]; then
        print_error "ensure_root_gitignore: project_root parameter required"
        return 1
    fi

    local gitignore_file="$project_root/.gitignore"
    local ignore_entry

    if [ "$install_mode" = "self-install" ]; then
        ignore_entry="$UNTRACKED_GITIGNORE_ENTRY"
    else
        ignore_entry="$DAEMON_GITIGNORE_ENTRY"
    fi

    print_verbose "Ensuring $ignore_entry in .gitignore..."

    # Create .gitignore if it doesn't exist
    if [ ! -f "$gitignore_file" ]; then
        cat > "$gitignore_file" <<EOF
# Claude Code Hooks Daemon
$ignore_entry
EOF
        print_success "Created .gitignore with daemon entry"
        return 0
    fi

    # Check if entry already exists
    if grep -qF "$ignore_entry" "$gitignore_file"; then
        print_verbose "Daemon entry already in .gitignore"
        return 0
    fi

    # Add entry to .gitignore
    cat >> "$gitignore_file" <<EOF

# Claude Code Hooks Daemon
$ignore_entry
EOF

    print_success "Added daemon entry to .gitignore"
    return 0
}

#
# verify_claude_gitignore() - Verify .claude/.gitignore exists and is correct
#
# In normal mode, checks for hooks-daemon/untracked/ entry.
# In self-install mode, this is not needed (untracked/ is at root).
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - install_mode: "self-install" or "normal"
#
# Returns:
#   Exit code 0 if correct, 1 if missing or incorrect
#
verify_claude_gitignore() {
    local project_root="$1"
    local install_mode="$2"

    if [ -z "$project_root" ]; then
        print_error "verify_claude_gitignore: project_root parameter required"
        return 1
    fi

    # Self-install mode doesn't need .claude/.gitignore for daemon
    if [ "$install_mode" = "self-install" ]; then
        print_verbose "Self-install mode: skipping .claude/.gitignore check"
        return 0
    fi

    local claude_gitignore="$project_root/.claude/.gitignore"

    # Check if .claude/.gitignore exists
    if [ ! -f "$claude_gitignore" ]; then
        print_warning ".claude/.gitignore not found"
        return 1
    fi

    # Verify it contains hooks-daemon/untracked/ entry
    if ! grep -q "hooks-daemon/untracked" "$claude_gitignore"; then
        print_warning ".claude/.gitignore missing hooks-daemon/untracked entry"
        return 1
    fi

    print_verbose ".claude/.gitignore is correct"
    return 0
}

#
# create_daemon_untracked_gitignore() - Create self-excluding .gitignore in daemon untracked dir
#
# Creates untracked/.gitignore with "/untracked/" entry to prevent git tracking.
#
# Args:
#   $1 - daemon_dir: Path to daemon installation directory
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
create_daemon_untracked_gitignore() {
    local daemon_dir="$1"

    if [ -z "$daemon_dir" ]; then
        print_error "create_daemon_untracked_gitignore: daemon_dir parameter required"
        return 1
    fi

    local untracked_dir="$daemon_dir/untracked"
    local untracked_gitignore="$untracked_dir/.gitignore"

    # Create untracked directory if needed
    if [ ! -d "$untracked_dir" ]; then
        mkdir -p "$untracked_dir"
    fi

    # Create self-excluding .gitignore
    echo "$UNTRACKED_GITIGNORE_ENTRY" > "$untracked_gitignore"

    print_verbose "Created untracked/.gitignore"
    return 0
}

#
# ensure_claude_gitignore() - Create .claude/.gitignore if missing
#
# In normal mode, creates .claude/.gitignore with hooks-daemon/untracked/ entry
# so that daemon runtime files are not tracked by git.
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - install_mode: "self-install" or "normal"
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
ensure_claude_gitignore() {
    local project_root="$1"
    local install_mode="$2"

    if [ -z "$project_root" ]; then
        print_error "ensure_claude_gitignore: project_root parameter required"
        return 1
    fi

    # Self-install mode doesn't need .claude/.gitignore for daemon
    if [ "$install_mode" = "self-install" ]; then
        print_verbose "Self-install mode: skipping .claude/.gitignore creation"
        return 0
    fi

    local claude_dir="$project_root/.claude"
    local claude_gitignore="$claude_dir/.gitignore"

    # Ensure .claude directory exists
    if [ ! -d "$claude_dir" ]; then
        print_verbose ".claude directory not found, skipping .claude/.gitignore"
        return 0
    fi

    # Create .claude/.gitignore if it doesn't exist
    if [ ! -f "$claude_gitignore" ]; then
        cat > "$claude_gitignore" <<EOF
# Claude Code Hooks Daemon - runtime files
hooks-daemon/untracked/
EOF
        print_success "Created .claude/.gitignore"
        return 0
    fi

    # Check if entry already exists
    if grep -q "hooks-daemon/untracked" "$claude_gitignore"; then
        print_verbose ".claude/.gitignore already has daemon entry"
        return 0
    fi

    # Append entry
    cat >> "$claude_gitignore" <<EOF

# Claude Code Hooks Daemon - runtime files
hooks-daemon/untracked/
EOF
    print_success "Added daemon entry to .claude/.gitignore"
    return 0
}

#
# show_gitignore_instructions() - Display instructions for manual .gitignore setup
#
# Shows user how to manually add .gitignore entries if needed.
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - install_mode: "self-install" or "normal"
#
show_gitignore_instructions() {
    local project_root="$1"
    local install_mode="$2"

    if [ "$install_mode" = "self-install" ]; then
        cat <<EOF

Manual .gitignore Setup (if needed):
=====================================

Add to $project_root/.gitignore:

# Claude Code Hooks Daemon (development)
$UNTRACKED_GITIGNORE_ENTRY

EOF
    else
        cat <<EOF

Manual .gitignore Setup (if needed):
=====================================

Add to $project_root/.gitignore:

# Claude Code Hooks Daemon
$DAEMON_GITIGNORE_ENTRY

Ensure $project_root/.claude/.gitignore contains:

hooks-daemon/untracked/

EOF
    fi
}

#
# verify_gitignore_complete() - Comprehensive .gitignore verification
#
# Checks all .gitignore files are properly configured.
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - install_mode: "self-install" or "normal"
#
# Returns:
#   Exit code 0 if all correct, 1 if any issues found
#
verify_gitignore_complete() {
    local project_root="$1"
    local daemon_dir="$2"
    local install_mode="$3"

    if [ -z "$project_root" ] || [ -z "$daemon_dir" ]; then
        print_error "verify_gitignore_complete: project_root and daemon_dir required"
        return 1
    fi

    local all_ok=true

    # Check root .gitignore
    local root_gitignore="$project_root/.gitignore"
    local expected_entry

    if [ "$install_mode" = "self-install" ]; then
        expected_entry="$UNTRACKED_GITIGNORE_ENTRY"
    else
        expected_entry="$DAEMON_GITIGNORE_ENTRY"
    fi

    if [ ! -f "$root_gitignore" ]; then
        print_warning "Root .gitignore not found"
        all_ok=false
    elif ! grep -qF "$expected_entry" "$root_gitignore"; then
        print_warning "Root .gitignore missing entry: $expected_entry"
        all_ok=false
    else
        print_verbose "Root .gitignore OK"
    fi

    # Check .claude/.gitignore (only for normal mode)
    if [ "$install_mode" != "self-install" ]; then
        if ! verify_claude_gitignore "$project_root" "$install_mode"; then
            all_ok=false
        fi
    fi

    # Check daemon untracked/.gitignore
    local daemon_untracked_gitignore="$daemon_dir/untracked/.gitignore"
    if [ ! -f "$daemon_untracked_gitignore" ]; then
        print_warning "Daemon untracked/.gitignore not found"
        all_ok=false
    elif ! grep -qF "$UNTRACKED_GITIGNORE_ENTRY" "$daemon_untracked_gitignore"; then
        print_warning "Daemon untracked/.gitignore missing self-exclusion"
        all_ok=false
    else
        print_verbose "Daemon untracked/.gitignore OK"
    fi

    if [ "$all_ok" = true ]; then
        return 0
    else
        return 1
    fi
}

#
# setup_all_gitignores() - Complete .gitignore setup workflow
#
# Sets up all necessary .gitignore files.
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
setup_all_gitignores() {
    local project_root="$1"
    local daemon_dir="$2"
    local install_mode="$3"

    if [ -z "$project_root" ] || [ -z "$daemon_dir" ]; then
        fail_fast "setup_all_gitignores: project_root and daemon_dir required"
    fi

    print_info "Setting up .gitignore files..."

    # Ensure root .gitignore
    if ! ensure_root_gitignore "$project_root" "$install_mode"; then
        print_error "Failed to setup root .gitignore"
        return 1
    fi

    # Create daemon untracked .gitignore
    if ! create_daemon_untracked_gitignore "$daemon_dir"; then
        print_error "Failed to create daemon untracked .gitignore"
        return 1
    fi

    # Create .claude/.gitignore if missing (normal mode only)
    if ! ensure_claude_gitignore "$project_root" "$install_mode"; then
        print_warning "Failed to create .claude/.gitignore"
        # Non-fatal: continue to verification
    fi

    # Verify everything is correct
    if verify_gitignore_complete "$project_root" "$daemon_dir" "$install_mode"; then
        print_success ".gitignore files configured correctly"
        return 0
    else
        print_warning ".gitignore files may need manual adjustment"
        show_gitignore_instructions "$project_root" "$install_mode"
        return 1
    fi
}
