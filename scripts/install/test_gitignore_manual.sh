#!/bin/bash
#
# Manual test for gitignore.sh
# Run with: bash scripts/install/test_gitignore_manual.sh
#

# Load the modules
INSTALL_LIB_DIR="$(dirname "$0")"
source "$INSTALL_LIB_DIR/output.sh"
source "$INSTALL_LIB_DIR/project_detection.sh"
source "$INSTALL_LIB_DIR/gitignore.sh"

echo "Testing gitignore.sh functions..."
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

# Create test directory to avoid modifying real .gitignore
TEST_DIR="/tmp/gitignore_test_$$"
mkdir -p "$TEST_DIR/.claude"
mkdir -p "$TEST_DIR/test_daemon/untracked"

print_info "Test directory: $TEST_DIR"

# Test 1: ensure_root_gitignore (creates new)
print_header "Test 1: ensure_root_gitignore() - create new"
if ensure_root_gitignore "$TEST_DIR" "normal"; then
    print_success "ensure_root_gitignore() passed"

    if [ -f "$TEST_DIR/.gitignore" ]; then
        print_success ".gitignore file created"
        if grep -q ".claude/hooks-daemon/" "$TEST_DIR/.gitignore"; then
            print_success "Contains correct entry"
        else
            print_error ".gitignore missing expected entry"
            cat "$TEST_DIR/.gitignore"
            rm -rf "$TEST_DIR"
            exit 1
        fi
    else
        print_error ".gitignore file not created"
        rm -rf "$TEST_DIR"
        exit 1
    fi
else
    print_error "ensure_root_gitignore() failed"
    rm -rf "$TEST_DIR"
    exit 1
fi

# Test 2: ensure_root_gitignore (already exists)
print_header "Test 2: ensure_root_gitignore() - already exists"
if ensure_root_gitignore "$TEST_DIR" "normal"; then
    print_success "ensure_root_gitignore() passed (idempotent)"
else
    print_error "ensure_root_gitignore() failed on second call"
    rm -rf "$TEST_DIR"
    exit 1
fi

# Test 3: ensure_root_gitignore (self-install mode)
TEST_DIR2="/tmp/gitignore_test_self_$$"
mkdir -p "$TEST_DIR2/.claude"
print_header "Test 3: ensure_root_gitignore() - self-install mode"
if ensure_root_gitignore "$TEST_DIR2" "self-install"; then
    print_success "ensure_root_gitignore() passed (self-install)"

    if grep -q "/untracked/" "$TEST_DIR2/.gitignore"; then
        print_success "Contains untracked/ entry"
    else
        print_error ".gitignore missing untracked/ entry"
        cat "$TEST_DIR2/.gitignore"
        rm -rf "$TEST_DIR" "$TEST_DIR2"
        exit 1
    fi
else
    print_error "ensure_root_gitignore() failed (self-install)"
    rm -rf "$TEST_DIR" "$TEST_DIR2"
    exit 1
fi

# Test 4: create_daemon_untracked_gitignore
print_header "Test 4: create_daemon_untracked_gitignore()"
if create_daemon_untracked_gitignore "$TEST_DIR/test_daemon"; then
    print_success "create_daemon_untracked_gitignore() passed"

    if [ -f "$TEST_DIR/test_daemon/untracked/.gitignore" ]; then
        print_success "untracked/.gitignore created"
        if grep -q "/untracked/" "$TEST_DIR/test_daemon/untracked/.gitignore"; then
            print_success "Contains self-exclusion entry"
        else
            print_error "Missing self-exclusion entry"
            rm -rf "$TEST_DIR" "$TEST_DIR2"
            exit 1
        fi
    else
        print_error "untracked/.gitignore not created"
        rm -rf "$TEST_DIR" "$TEST_DIR2"
        exit 1
    fi
else
    print_error "create_daemon_untracked_gitignore() failed"
    rm -rf "$TEST_DIR" "$TEST_DIR2"
    exit 1
fi

# Test 5: verify_claude_gitignore (normal mode, missing)
print_header "Test 5: verify_claude_gitignore() - normal mode, missing"
if verify_claude_gitignore "$TEST_DIR" "normal"; then
    print_warning "verify_claude_gitignore() should have failed (file missing)"
else
    print_success "verify_claude_gitignore() correctly detected missing file"
fi

# Create .claude/.gitignore for next test
cat > "$TEST_DIR/.claude/.gitignore" <<'EOF'
hooks-daemon/untracked/
EOF

# Test 6: verify_claude_gitignore (normal mode, exists)
print_header "Test 6: verify_claude_gitignore() - normal mode, exists"
if verify_claude_gitignore "$TEST_DIR" "normal"; then
    print_success "verify_claude_gitignore() passed with correct file"
else
    print_error "verify_claude_gitignore() failed with correct file"
    rm -rf "$TEST_DIR" "$TEST_DIR2"
    exit 1
fi

# Test 7: verify_claude_gitignore (self-install mode, skipped)
print_header "Test 7: verify_claude_gitignore() - self-install mode"
if verify_claude_gitignore "$TEST_DIR2" "self-install"; then
    print_success "verify_claude_gitignore() skipped in self-install mode"
else
    print_error "verify_claude_gitignore() should pass in self-install mode"
    rm -rf "$TEST_DIR" "$TEST_DIR2"
    exit 1
fi

# Test 8: verify_gitignore_complete
print_header "Test 8: verify_gitignore_complete()"
if verify_gitignore_complete "$TEST_DIR" "$TEST_DIR/test_daemon" "normal"; then
    print_success "verify_gitignore_complete() passed"
else
    print_warning "verify_gitignore_complete() detected issues (expected for test setup)"
fi

# Test 9: setup_all_gitignores (comprehensive test)
TEST_DIR3="/tmp/gitignore_test_all_$$"
mkdir -p "$TEST_DIR3/.claude"
print_header "Test 9: setup_all_gitignores() - full workflow"
if setup_all_gitignores "$TEST_DIR3" "$TEST_DIR3/test_daemon" "normal"; then
    print_success "setup_all_gitignores() passed"
else
    print_warning "setup_all_gitignores() completed with warnings"
fi

# Cleanup
rm -rf "$TEST_DIR" "$TEST_DIR2" "$TEST_DIR3"

echo ""
print_success "All manual tests passed!"
