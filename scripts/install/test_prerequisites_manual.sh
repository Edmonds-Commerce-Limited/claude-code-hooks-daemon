#!/bin/bash
#
# Manual test for prerequisites.sh
# Run with: bash scripts/lib/test_prerequisites_manual.sh
#

# Load the module
INSTALL_LIB_DIR="$(dirname "$0")"
source "$INSTALL_LIB_DIR/output.sh"
source "$INSTALL_LIB_DIR/prerequisites.sh"

echo "Testing prerequisites.sh functions..."
echo ""

# Test check_git (should pass on this system)
print_header "Test: check_git()"
if check_git; then
    print_success "check_git() passed"
else
    print_error "check_git() failed"
    exit 1
fi

# Test check_python3 (should pass on this system)
print_header "Test: check_python3()"
if check_python3; then
    print_success "check_python3() passed"
else
    print_error "check_python3() failed"
    exit 1
fi

# Test check_uv (should pass since uv is installed)
print_header "Test: check_uv()"
if check_uv true; then
    print_success "check_uv() passed"
else
    print_error "check_uv() failed"
    exit 1
fi

# Test get_python_version
print_header "Test: get_python_version()"
py_version=$(get_python_version)
if [ -n "$py_version" ]; then
    print_success "get_python_version() returned: $py_version"
else
    print_error "get_python_version() failed"
    exit 1
fi

# Test get_python_major_minor
print_header "Test: get_python_major_minor()"
py_major_minor=$(get_python_major_minor)
if [ -n "$py_major_minor" ]; then
    print_success "get_python_major_minor() returned: $py_major_minor"
else
    print_error "get_python_major_minor() failed"
    exit 1
fi

# Test check_all_prerequisites
print_header "Test: check_all_prerequisites()"
if check_all_prerequisites; then
    print_success "check_all_prerequisites() passed"
else
    print_error "check_all_prerequisites() failed"
    exit 1
fi

echo ""
print_success "All manual tests passed!"
