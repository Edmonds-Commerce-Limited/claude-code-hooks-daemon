#!/bin/bash
#
# Run tests with automatic venv setup
#
# Usage:
#   ./scripts/test.bash                 # Run all tests
#   ./scripts/test.bash tests/unit/     # Run specific test directory
#   ./scripts/test.bash -k test_foo     # Run tests matching pattern
#   ./scripts/test.bash --coverage      # Run with coverage report
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Source venv management functions
# shellcheck source=./venv-include.bash
source "${SCRIPT_DIR}/venv-include.bash"

cd "${PROJECT_ROOT}"

#
# Parse arguments
#
COVERAGE=false
PYTEST_ARGS=()

for arg in "$@"; do
    if [[ "${arg}" == "--coverage" ]]; then
        COVERAGE=true
    else
        PYTEST_ARGS+=("${arg}")
    fi
done

# Default to all tests if no args
if [[ ${#PYTEST_ARGS[@]} -eq 0 ]]; then
    PYTEST_ARGS=("tests/")
fi

#
# Ensure venv exists and deps installed
#
echo "=============================================="
echo "Test Runner"
echo "=============================================="
echo ""

ensure_venv || exit 1

# Check if pytest is installed
if ! "${VENV_PYTHON}" -c "import pytest" 2>/dev/null; then
    echo "Installing dependencies..."
    install_deps || exit 1
fi

echo ""
echo "=============================================="
echo "Running Tests"
echo "=============================================="
echo ""

#
# Build pytest command
#
PYTEST_CMD=("${VENV_DIR}/bin/pytest" "${PYTEST_ARGS[@]}")

if [[ "${COVERAGE}" == "true" ]]; then
    PYTEST_CMD+=(
        "--cov=src/claude_code_hooks_daemon"
        "--cov-report=term-missing"
        "--cov-report=html"
        "--cov-report=json:untracked/qa/coverage.json"
    )
fi

# Add verbose output
PYTEST_CMD+=("-v")

#
# Run tests
#
echo "Command: ${PYTEST_CMD[*]}"
echo ""

"${PYTEST_CMD[@]}"
EXIT_CODE=$?

echo ""
echo "=============================================="

if [[ ${EXIT_CODE} -eq 0 ]]; then
    echo -e "${GREEN}✓ Tests passed${NC}"

    if [[ "${COVERAGE}" == "true" ]]; then
        echo ""
        echo "Coverage reports:"
        echo "  - Terminal: (above)"
        echo "  - HTML: htmlcov/index.html"
        echo "  - JSON: untracked/qa/coverage.json"
    fi
else
    echo -e "${RED}✗ Tests failed${NC}"
fi

echo "=============================================="

exit ${EXIT_CODE}
