#!/usr/bin/env bash
# Strategy Pattern Compliance Check
# Verifies proper Strategy Pattern usage in language-aware handlers
#
# Checks:
# - Handlers delegate to strategies (no language-specific if/elif chains)
# - Strategies have get_acceptance_tests() method
# - Strategies use named constants (no bare string literals)
# - All strategies are registered in Registry
#
# Usage:
#   ./scripts/qa/run_strategy_pattern_check.sh
#
# Exit codes:
#   0 - No violations
#   1 - Violations found
#   2 - Execution error

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Get project root (script is in scripts/qa/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Python command
PYTHON="${PROJECT_ROOT}/untracked/venv/bin/python"

if [ ! -f "$PYTHON" ]; then
    echo -e "${RED}ERROR: Python not found at $PYTHON${NC}" >&2
    exit 2
fi

# Header
echo "========================================"
echo "Strategy Pattern Compliance Check"
echo "========================================"
echo

# Run checker with JSON output
cd "$PROJECT_ROOT"
if "$PYTHON" -m claude_code_hooks_daemon.qa.strategy_pattern_checker --json; then
    echo -e "${GREEN}✅ PASSED${NC} - No strategy pattern violations"
    exit 0
else
    echo
    echo -e "${RED}❌ FAILED${NC} - Strategy pattern violations detected"
    echo
    echo "See: untracked/qa/strategy_pattern.json for details"
    exit 1
fi
