#!/bin/bash
#
# Manual test for validation.sh
# Run with: bash scripts/install/test_validation_manual.sh
#

# Load the modules
INSTALL_LIB_DIR="$(dirname "$0")"
source "$INSTALL_LIB_DIR/output.sh"
source "$INSTALL_LIB_DIR/project_detection.sh"
source "$INSTALL_LIB_DIR/validation.sh"

echo "Testing validation.sh functions..."
echo ""

# Detect project
print_header "Setup: Detect project"
if ! detect_and_validate_project; then
    print_error "Failed to detect project"
    exit 1
fi

print_info "PROJECT_ROOT: $PROJECT_ROOT"
print_info "DAEMON_DIR: $DAEMON_DIR"
print_info "VENV_PYTHON: $VENV_PYTHON"

if [ ! -f "$VENV_PYTHON" ]; then
    print_error "Venv Python not found: $VENV_PYTHON"
    print_warning "Cannot test validation without venv"
    exit 1
fi

# Test 1: cleanup_stale_runtime_files
print_header "Test 1: cleanup_stale_runtime_files()"
if cleanup_stale_runtime_files "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR"; then
    print_success "cleanup_stale_runtime_files() passed"
else
    print_error "cleanup_stale_runtime_files() failed"
    exit 1
fi

# Test 2: verify_config_valid
print_header "Test 2: verify_config_valid()"
if verify_config_valid "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR"; then
    print_success "verify_config_valid() passed - config is valid"
else
    print_warning "verify_config_valid() detected config issues (may be expected)"
fi

# Test 3: run_pre_install_checks (non-fatal)
print_header "Test 3: run_pre_install_checks() - non-fatal mode"
if run_pre_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" false; then
    print_success "run_pre_install_checks() passed"
else
    print_warning "run_pre_install_checks() detected issues (may be expected for self-install)"
fi

# Test 4: run_post_install_checks (non-fatal)
print_header "Test 4: run_post_install_checks() - non-fatal mode"
if run_post_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" false; then
    print_success "run_post_install_checks() passed"
else
    print_warning "run_post_install_checks() detected issues (may be expected for self-install)"
fi

echo ""
print_success "All manual tests completed!"
print_info "Note: Some warnings are expected in self-install mode"
