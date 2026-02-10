#!/bin/bash
#
# Manual test for output.sh
# Run with: bash scripts/lib/test_output_manual.sh
#

# Load the module
source "$(dirname "$0")/output.sh"

echo "Testing output.sh functions..."
echo ""

# Test print_header
print_header "Test Header Section"

# Test print_success
print_success "This is a success message"

# Test print_error
print_error "This is an error message"

# Test print_warning
print_warning "This is a warning message"

# Test print_info
print_info "This is an info message"

# Test log_step
log_step "1" "First test step"
log_step "2" "Second test step"

# Test print_verbose (should not print)
print_verbose "This should not appear (VERBOSE not set)"

# Test print_verbose with VERBOSE=true
VERBOSE=true print_verbose "This should appear (VERBOSE=true)"

echo ""
echo "Manual tests completed. Verify output above looks correct."
echo ""

# Test that fail_fast actually exits (in subshell to avoid killing this script)
echo "Testing fail_fast (in subshell)..."
(
    source "$(dirname "$0")/output.sh"
    fail_fast "Testing fail_fast with exit code 42" 42
)
exit_code=$?
if [ $exit_code -eq 42 ]; then
    print_success "fail_fast correctly exited with code 42"
else
    print_error "fail_fast did not exit correctly (got $exit_code, expected 42)"
    exit 1
fi

echo ""
print_success "All manual tests passed!"
