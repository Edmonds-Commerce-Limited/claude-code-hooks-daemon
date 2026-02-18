#!/bin/bash
#
# Auto-fix formatting and linting issues
#
# Exit codes:
#   0 - All fixes applied successfully
#   1 - Some fixes failed
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source venv management
# shellcheck source=../venv-include.bash
source "${PROJECT_ROOT}/scripts/venv-include.bash"

cd "${PROJECT_ROOT}"

# Ensure venv and deps
ensure_venv || exit 1
if ! "${VENV_PYTHON}" -c "import black; import ruff" 2>/dev/null; then
    install_deps || exit 1
fi

echo "========================================"
echo "Auto-Fixing Code Quality Issues"
echo "========================================"
echo ""

# Track overall status
OVERALL_EXIT_CODE=0

# 1. Run Black formatter
echo "1. Running Black formatter..."
echo "----------------------------------------"
if venv_tool black src/ tests/; then
    echo "✅ Black formatting completed"
else
    OVERALL_EXIT_CODE=1
    echo "❌ Black formatting FAILED"
fi
echo ""

# 2. Run Ruff auto-fix
echo "2. Running Ruff auto-fix..."
echo "----------------------------------------"
if venv_tool ruff check --fix src/ tests/; then
    echo "✅ Ruff auto-fix completed"
else
    # Ruff returns non-zero if there are unfixable issues
    # This is OK - we've fixed what we can
    echo "⚠️  Ruff auto-fix completed with unfixable issues remaining"
fi
echo ""

echo "========================================"
echo "Auto-Fix Summary"
echo "========================================"
echo ""
echo "Formatting and auto-fixable linting issues have been resolved."
echo "Run ./scripts/qa/run_all.sh to verify all QA checks pass."
echo ""

exit ${OVERALL_EXIT_CODE}
