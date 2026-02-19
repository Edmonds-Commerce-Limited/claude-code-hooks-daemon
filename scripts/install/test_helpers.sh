#!/bin/bash
#
# test_helpers.sh - Test infrastructure for install/upgrade modules
#
# Creates isolated dummy projects in /tmp for testing install/upgrade logic
# without affecting the live daemon repository.
#
# Usage:
#   source "$(dirname "$0")/install/test_helpers.sh"
#   TEST_PROJECT=$(create_test_project)
#   # ... run tests ...
#   cleanup_test_project "$TEST_PROJECT"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

#
# create_test_project() - Create isolated test project in /tmp
#
# Creates a minimal project structure with .git and .claude directories
# for testing install/upgrade modules in isolation.
#
# Args:
#   $1 - mode (optional): "normal" or "self-install" (default: normal)
#
# Returns:
#   Prints test project path to stdout
#   Exit code 0 on success, 1 on failure
#
create_test_project() {
    local mode="${1:-normal}"

    # Create unique test directory
    local test_id
    test_id="test_$$_$(date +%s)"
    local test_project="/tmp/hooks_daemon_test_$test_id"

    print_verbose "Creating test project: $test_project (mode: $mode)"

    # Create project structure
    mkdir -p "$test_project"

    # Initialize git repo
    git -C "$test_project" init -q
    git -C "$test_project" config user.email "test@example.com"
    git -C "$test_project" config user.name "Test User"

    # Create .claude directory
    mkdir -p "$test_project/.claude"
    mkdir -p "$test_project/.claude/hooks"
    mkdir -p "$test_project/.claude/commands"

    # Create minimal dummy files
    echo "# Test Project" > "$test_project/README.md"
    echo "test-project" > "$test_project/.git/description"

    # Initial commit
    git -C "$test_project" add README.md
    git -C "$test_project" commit -q -m "Initial commit"

    if [ "$mode" = "self-install" ]; then
        # Self-install mode: daemon directory is project root
        mkdir -p "$test_project/src/claude_code_hooks_daemon"
        mkdir -p "$test_project/untracked/venv"
        mkdir -p "$test_project/scripts/install"

        # Copy essential modules to test project
        cp "$INSTALL_LIB_DIR"/output.sh "$test_project/scripts/install/"
        cp "$INSTALL_LIB_DIR"/prerequisites.sh "$test_project/scripts/install/"
        cp "$INSTALL_LIB_DIR"/project_detection.sh "$test_project/scripts/install/"

        # Create minimal pyproject.toml
        cat > "$test_project/pyproject.toml" <<'EOF'
[project]
name = "claude-code-hooks-daemon"
version = "2.1.0"
EOF

        print_verbose "Created self-install mode test project"
    else
        # Normal mode: daemon in .claude/hooks-daemon/
        mkdir -p "$test_project/.claude/hooks-daemon"
        mkdir -p "$test_project/.claude/hooks-daemon/src/claude_code_hooks_daemon"
        mkdir -p "$test_project/.claude/hooks-daemon/untracked/venv"
        mkdir -p "$test_project/.claude/hooks-daemon/scripts/install"

        # Copy essential modules to daemon directory
        cp "$INSTALL_LIB_DIR"/output.sh "$test_project/.claude/hooks-daemon/scripts/install/"
        cp "$INSTALL_LIB_DIR"/prerequisites.sh "$test_project/.claude/hooks-daemon/scripts/install/"
        cp "$INSTALL_LIB_DIR"/project_detection.sh "$test_project/.claude/hooks-daemon/scripts/install/"

        # Create minimal pyproject.toml
        cat > "$test_project/.claude/hooks-daemon/pyproject.toml" <<'EOF'
[project]
name = "claude-code-hooks-daemon"
version = "2.1.0"
EOF

        print_verbose "Created normal mode test project"
    fi

    print_success "Test project created: $test_project"
    echo "$test_project"
    return 0
}

#
# create_test_daemon_dir() - Create minimal daemon directory structure
#
# Creates daemon source files needed for testing.
#
# Args:
#   $1 - daemon_dir: Path to daemon directory
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
create_test_daemon_dir() {
    local daemon_dir="$1"

    if [ -z "$daemon_dir" ]; then
        print_error "create_test_daemon_dir: daemon_dir required"
        return 1
    fi

    print_verbose "Creating daemon directory structure: $daemon_dir"

    # Create source structure
    mkdir -p "$daemon_dir/src/claude_code_hooks_daemon"
    mkdir -p "$daemon_dir/untracked/venv"
    mkdir -p "$daemon_dir/.claude/hooks"
    mkdir -p "$daemon_dir/.claude/commands"

    # Create dummy hook scripts
    for hook in pre_tool_use post_tool_use session_start session_end stop; do
        cat > "$daemon_dir/.claude/hooks/$hook" <<'HOOK_EOF'
#!/bin/bash
# Dummy hook for testing
echo '{"decision": "allow", "reason": "Test hook"}'
exit 0
HOOK_EOF
        chmod +x "$daemon_dir/.claude/hooks/$hook"
    done

    # Create dummy init.sh
    cat > "$daemon_dir/init.sh" <<'INIT_EOF'
#!/bin/bash
# Dummy init.sh for testing
echo "Test daemon initialized"
INIT_EOF
    chmod +x "$daemon_dir/init.sh"

    # Create dummy slash commands
    cat > "$daemon_dir/.claude/commands/test-command.md" <<'CMD_EOF'
# Test Command

This is a test slash command.
CMD_EOF

    print_success "Daemon directory structure created"
    return 0
}

#
# cleanup_test_project() - Remove test project directory
#
# Args:
#   $1 - test_project: Path to test project directory
#
# Returns:
#   Exit code 0 on success
#
cleanup_test_project() {
    local test_project="$1"

    if [ -z "$test_project" ]; then
        print_error "cleanup_test_project: test_project required"
        return 1
    fi

    # Safety check: only remove /tmp/hooks_daemon_test_* directories
    if [[ "$test_project" != /tmp/hooks_daemon_test_* ]]; then
        print_error "Refusing to remove non-test directory: $test_project"
        return 1
    fi

    if [ -d "$test_project" ]; then
        rm -rf "$test_project"
        print_verbose "Cleaned up test project: $test_project"
    fi

    return 0
}

#
# run_test_with_cleanup() - Execute test function with automatic cleanup
#
# Runs a test function and ensures cleanup happens even on failure.
#
# Args:
#   $1 - test_function: Name of test function to run
#   $2 - mode (optional): "normal" or "self-install" (default: normal)
#
# Returns:
#   Exit code from test function
#
run_test_with_cleanup() {
    local test_function="$1"
    local mode="${2:-normal}"

    if [ -z "$test_function" ]; then
        print_error "run_test_with_cleanup: test_function required"
        return 1
    fi

    local test_project
    test_project=$(create_test_project "$mode")
    local create_status=$?

    if [ $create_status -ne 0 ]; then
        print_error "Failed to create test project"
        return 1
    fi

    # Export for test function
    export TEST_PROJECT="$test_project"

    # Run test function
    local test_status=0
    $test_function || test_status=$?

    # Always cleanup
    cleanup_test_project "$test_project"

    return $test_status
}

#
# create_test_config() - Create test hooks-daemon.yaml
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - mode: "normal" or "self-install"
#
# Returns:
#   Exit code 0 on success
#
create_test_config() {
    local project_root="$1"
    local mode="$2"

    if [ -z "$project_root" ] || [ -z "$mode" ]; then
        print_error "create_test_config: project_root and mode required"
        return 1
    fi

    local config_file="$project_root/.claude/hooks-daemon.yaml"

    cat > "$config_file" <<EOF
version: 1.0

daemon:
  idle_timeout_seconds: 600
  log_level: INFO
  self_install_mode: $([ "$mode" = "self-install" ] && echo "true" || echo "false")

handlers:
  pre_tool_use:
    test_handler:
      enabled: true
      priority: 50

  post_tool_use:
    test_handler:
      enabled: true
      priority: 50
EOF

    print_verbose "Created test config: $config_file"
    return 0
}

#
# verify_test_structure() - Verify test project structure is valid
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - mode: "normal" or "self-install"
#
# Returns:
#   Exit code 0 if valid, 1 if invalid
#
verify_test_structure() {
    local project_root="$1"
    local mode="$2"

    if [ -z "$project_root" ] || [ -z "$mode" ]; then
        print_error "verify_test_structure: project_root and mode required"
        return 1
    fi

    # Check git directory
    if [ ! -d "$project_root/.git" ]; then
        print_error "Missing .git directory"
        return 1
    fi

    # Check .claude directory
    if [ ! -d "$project_root/.claude" ]; then
        print_error "Missing .claude directory"
        return 1
    fi

    if [ "$mode" = "self-install" ]; then
        # Self-install: daemon at project root
        if [ ! -d "$project_root/src/claude_code_hooks_daemon" ]; then
            print_error "Missing src/claude_code_hooks_daemon directory"
            return 1
        fi
    else
        # Normal: daemon in .claude/hooks-daemon/
        if [ ! -d "$project_root/.claude/hooks-daemon" ]; then
            print_error "Missing .claude/hooks-daemon directory"
            return 1
        fi
    fi

    print_verbose "Test structure verified: $project_root ($mode)"
    return 0
}
