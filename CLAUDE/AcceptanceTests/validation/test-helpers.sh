#!/usr/bin/env bash
# Test helper functions for acceptance tests

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

# Test assertion functions
assert_equals() {
    local expected="$1"
    local actual="$2"
    local message="${3:-Assertion failed}"

    TESTS_RUN=$((TESTS_RUN + 1))

    if [ "$expected" = "$actual" ]; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        log_success "$message: PASS"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        log_error "$message: FAIL"
        log_error "  Expected: $expected"
        log_error "  Actual: $actual"
        return 1
    fi
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local message="${3:-Assertion failed}"

    TESTS_RUN=$((TESTS_RUN + 1))

    if echo "$haystack" | grep -q "$needle"; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        log_success "$message: PASS"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        log_error "$message: FAIL"
        log_error "  Expected to find: $needle"
        log_error "  In: $haystack"
        return 1
    fi
}

assert_file_exists() {
    local file="$1"
    local message="${2:-File should exist}"

    TESTS_RUN=$((TESTS_RUN + 1))

    if [ -f "$file" ]; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        log_success "$message: PASS"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        log_error "$message: FAIL"
        log_error "  File not found: $file"
        return 1
    fi
}

assert_file_not_exists() {
    local file="$1"
    local message="${2:-File should not exist}"

    TESTS_RUN=$((TESTS_RUN + 1))

    if [ ! -f "$file" ]; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        log_success "$message: PASS"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        log_error "$message: FAIL"
        log_error "  File exists: $file"
        return 1
    fi
}

# Test environment setup
setup_test_env() {
    local test_name="$1"
    log_info "Setting up test environment: $test_name"

    # Create temporary directory for test
    export TEST_DIR="/tmp/acceptance-test-$$-${test_name}"
    mkdir -p "$TEST_DIR"

    # Save original directory
    export ORIGINAL_DIR="$(pwd)"
}

cleanup_test_env() {
    log_info "Cleaning up test environment"

    # Return to original directory
    cd "$ORIGINAL_DIR" || true

    # Remove temporary directory
    if [ -n "${TEST_DIR:-}" ] && [ -d "$TEST_DIR" ]; then
        rm -rf "$TEST_DIR"
    fi
}

# Summary reporting
print_test_summary() {
    echo ""
    echo "=========================================="
    echo "Test Summary"
    echo "=========================================="
    echo "Tests run: $TESTS_RUN"
    echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
    echo "=========================================="

    if [ "$TESTS_FAILED" -eq 0 ]; then
        log_success "All tests passed!"
        return 0
    else
        log_error "$TESTS_FAILED test(s) failed"
        return 1
    fi
}

# Daemon status check
check_daemon_running() {
    local python_cmd="${PYTHON:-/workspace/untracked/venv/bin/python}"

    log_info "Checking daemon status..."
    if $python_cmd -m claude_code_hooks_daemon.daemon.cli status | grep -q "RUNNING"; then
        log_success "Daemon is running"
        return 0
    else
        log_error "Daemon is not running"
        return 1
    fi
}

# Git helpers
ensure_clean_git() {
    log_info "Checking git status..."
    if ! git diff --quiet || ! git diff --cached --quiet; then
        log_error "Working directory is not clean"
        git status
        return 1
    fi
    log_success "Working directory is clean"
    return 0
}

# Export functions
export -f log_info log_warn log_error log_success
export -f assert_equals assert_contains assert_file_exists assert_file_not_exists
export -f setup_test_env cleanup_test_env print_test_summary
export -f check_daemon_running ensure_clean_git
