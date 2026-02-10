#!/bin/bash
#
# Manual test for slash_commands.sh
# Run with: bash scripts/install/test_slash_commands_manual.sh
#

# Load the modules
INSTALL_LIB_DIR="$(dirname "$0")"
source "$INSTALL_LIB_DIR/output.sh"
source "$INSTALL_LIB_DIR/project_detection.sh"
source "$INSTALL_LIB_DIR/slash_commands.sh"

echo "Testing slash_commands.sh functions..."
echo ""

# Detect project
print_header "Setup: Detect project"
if ! detect_and_validate_project; then
    print_error "Failed to detect project"
    exit 1
fi

print_info "PROJECT_ROOT: $PROJECT_ROOT"
print_info "DAEMON_DIR: $DAEMON_DIR"
print_info "INSTALL_MODE: $INSTALL_MODE"

# Create test directory
TEST_DIR="/tmp/slash_test_$$"
mkdir -p "$TEST_DIR/.claude/commands"
mkdir -p "$TEST_DIR/daemon/.claude/commands"

# Create test slash command files
cat > "$TEST_DIR/daemon/.claude/commands/test-command.md" <<'EOF'
# Test Command

This is a test slash command.
EOF

cat > "$TEST_DIR/daemon/.claude/commands/another-command.md" <<'EOF'
# Another Command

Another test command.
EOF

print_info "Test directory: $TEST_DIR"

# Test 1: deploy_slash_commands (normal mode)
print_header "Test 1: deploy_slash_commands() - normal mode"
if deploy_slash_commands "$TEST_DIR" "$TEST_DIR/daemon" "normal"; then
    print_success "deploy_slash_commands() passed"

    if [ -f "$TEST_DIR/.claude/commands/test-command.md" ]; then
        print_success "test-command.md deployed"
    else
        print_error "test-command.md not deployed"
        rm -rf "$TEST_DIR"
        exit 1
    fi

    if [ -f "$TEST_DIR/.claude/commands/another-command.md" ]; then
        print_success "another-command.md deployed"
    else
        print_error "another-command.md not deployed"
        rm -rf "$TEST_DIR"
        exit 1
    fi
else
    print_error "deploy_slash_commands() failed"
    rm -rf "$TEST_DIR"
    exit 1
fi

# Test 2: verify_slash_commands_deployed
print_header "Test 2: verify_slash_commands_deployed()"
if verify_slash_commands_deployed "$TEST_DIR"; then
    print_success "verify_slash_commands_deployed() passed"
else
    print_error "verify_slash_commands_deployed() failed"
    rm -rf "$TEST_DIR"
    exit 1
fi

# Test 3: list_slash_commands
print_header "Test 3: list_slash_commands()"
list_slash_commands "$TEST_DIR"
print_success "list_slash_commands() completed"

# Test 4: remove_slash_command
print_header "Test 4: remove_slash_command()"
if remove_slash_command "$TEST_DIR" "test-command"; then
    print_success "remove_slash_command() passed"

    if [ -f "$TEST_DIR/.claude/commands/test-command.md" ]; then
        print_error "test-command.md not removed"
        rm -rf "$TEST_DIR"
        exit 1
    else
        print_success "test-command.md removed"
    fi
else
    print_error "remove_slash_command() failed"
    rm -rf "$TEST_DIR"
    exit 1
fi

# Test 5: deploy_single_slash_command
print_header "Test 5: deploy_single_slash_command() - restore removed command"
if deploy_single_slash_command "$TEST_DIR" "$TEST_DIR/daemon" "normal" "test-command"; then
    print_success "deploy_single_slash_command() passed"

    if [ -f "$TEST_DIR/.claude/commands/test-command.md" ]; then
        print_success "test-command.md restored"
    else
        print_error "test-command.md not restored"
        rm -rf "$TEST_DIR"
        exit 1
    fi
else
    print_error "deploy_single_slash_command() failed"
    rm -rf "$TEST_DIR"
    exit 1
fi

# Test 6: deploy_slash_commands (self-install mode with symlinks)
TEST_DIR2="/tmp/slash_test_self_$$"
mkdir -p "$TEST_DIR2/.claude/commands"
mkdir -p "$TEST_DIR2/daemon/.claude/commands"
cp "$TEST_DIR/daemon/.claude/commands/"*.md "$TEST_DIR2/daemon/.claude/commands/"

print_header "Test 6: deploy_slash_commands() - self-install mode"
if deploy_slash_commands "$TEST_DIR2" "$TEST_DIR2/daemon" "self-install"; then
    print_success "deploy_slash_commands() passed (self-install)"

    if [ -L "$TEST_DIR2/.claude/commands/test-command.md" ]; then
        print_success "test-command.md is symlink"
    else
        print_error "test-command.md is not symlink"
        rm -rf "$TEST_DIR" "$TEST_DIR2"
        exit 1
    fi
else
    print_error "deploy_slash_commands() failed (self-install)"
    rm -rf "$TEST_DIR" "$TEST_DIR2"
    exit 1
fi

# Test 7: Test with real project commands
print_header "Test 7: Real project slash commands"
if [ -d "$DAEMON_DIR/.claude/commands" ]; then
    print_info "Real daemon has slash commands directory"
    list_slash_commands "$PROJECT_ROOT"
else
    print_info "No slash commands directory in daemon"
fi

# Cleanup
rm -rf "$TEST_DIR" "$TEST_DIR2"

echo ""
print_success "All manual tests passed!"
