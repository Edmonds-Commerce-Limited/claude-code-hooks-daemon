#!/bin/bash
#
# Validate Worktree QA
#
# Runs QA sequentially in each active worktree to verify 100% pass.
# MUST run sequentially - concurrent QA causes daemon socket collisions
# and mypy cache corruption.
#
# See CLAUDE/Worktree.md for full documentation.
#
# Usage:
#   ./scripts/validate_worktrees.sh              # Validate all worktrees
#   ./scripts/validate_worktrees.sh worktree-plan-00028  # Validate one worktree
#

set -euo pipefail

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKTREES_DIR="${PROJECT_ROOT}/untracked/worktrees"
RESULTS_FILE="/tmp/worktree_qa_results_$$.txt"

# Track results
declare -a PASSED_WTS=()
declare -a FAILED_WTS=()

validate_worktree() {
    local wt_name="$1"
    local wt_dir="${WORKTREES_DIR}/${wt_name}"

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  Validating: ${wt_name}${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""

    # Check worktree exists
    if [[ ! -d "${wt_dir}" ]]; then
        echo -e "${RED}ERROR${NC}: Worktree directory not found: ${wt_dir}"
        FAILED_WTS+=("${wt_name} (NOT FOUND)")
        return 1
    fi

    # Check venv exists
    if [[ ! -f "${wt_dir}/untracked/venv/bin/python" ]]; then
        echo -e "${RED}ERROR${NC}: Venv not found. Run: ./scripts/setup_worktree.sh ${wt_name}"
        FAILED_WTS+=("${wt_name} (NO VENV)")
        return 1
    fi

    # Verify editable install points to worktree
    local editable_location
    editable_location=$("${wt_dir}/untracked/venv/bin/pip" show claude-code-hooks-daemon 2>/dev/null | grep "Editable project location" | cut -d' ' -f4- || echo "UNKNOWN")
    if [[ "${editable_location}" != "${wt_dir}" ]]; then
        echo -e "${RED}ERROR${NC}: Editable install points to wrong location"
        echo "  Expected: ${wt_dir}"
        echo "  Got: ${editable_location}"
        echo "  Fix: cd ${wt_dir} && untracked/venv/bin/pip install -e '.[dev]'"
        FAILED_WTS+=("${wt_name} (WRONG VENV TARGET)")
        return 1
    fi
    echo -e "${GREEN}✓${NC} Venv editable install correct: ${editable_location}"

    # Run QA from within the worktree
    echo -e "${YELLOW}→${NC} Running QA suite..."
    local qa_log="/tmp/qa_${wt_name}_$$.txt"

    if (cd "${wt_dir}" && ./scripts/qa/run_all.sh > "${qa_log}" 2>&1); then
        echo -e "${GREEN}✓${NC} QA PASSED"
        PASSED_WTS+=("${wt_name}")
    else
        echo -e "${RED}✗${NC} QA FAILED - see ${qa_log}"
        # Show the summary section
        grep -A 12 "QA Summary" "${qa_log}" 2>/dev/null || true
        echo ""
        # Show failed tests
        grep "FAILED" "${qa_log}" 2>/dev/null || true
        FAILED_WTS+=("${wt_name}")
        return 1
    fi
}

# Main
echo -e "${CYAN}=== Worktree QA Validation ===${NC}"
echo ""
echo -e "${YELLOW}NOTE${NC}: Running QA sequentially (concurrent runs cause daemon"
echo "      socket collisions and mypy cache corruption)."

if [[ $# -gt 0 ]]; then
    # Validate specific worktree(s)
    for wt in "$@"; do
        validate_worktree "${wt}" || true
    done
else
    # Validate all worktrees
    if [[ ! -d "${WORKTREES_DIR}" ]]; then
        echo -e "${YELLOW}No worktrees found at ${WORKTREES_DIR}${NC}"
        exit 0
    fi

    # List all worktree directories
    for wt_dir in "${WORKTREES_DIR}"/worktree-*; do
        if [[ -d "${wt_dir}" ]]; then
            wt_name=$(basename "${wt_dir}")
            validate_worktree "${wt_name}" || true
        fi
    done
fi

# Summary
echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Validation Summary${NC}"
echo -e "${CYAN}========================================${NC}"

if [[ ${#PASSED_WTS[@]} -gt 0 ]]; then
    for wt in "${PASSED_WTS[@]}"; do
        echo -e "  ${GREEN}✅ PASSED${NC}: ${wt}"
    done
fi

if [[ ${#FAILED_WTS[@]} -gt 0 ]]; then
    for wt in "${FAILED_WTS[@]}"; do
        echo -e "  ${RED}❌ FAILED${NC}: ${wt}"
    done
fi

echo ""
TOTAL=$(( ${#PASSED_WTS[@]} + ${#FAILED_WTS[@]} ))
echo "  Total: ${TOTAL}  Passed: ${#PASSED_WTS[@]}  Failed: ${#FAILED_WTS[@]}"

if [[ ${#FAILED_WTS[@]} -gt 0 ]]; then
    echo ""
    echo -e "${RED}NOT ALL WORKTREES PASSED${NC}"
    exit 1
else
    echo ""
    echo -e "${GREEN}ALL WORKTREES PASSED${NC}"
    exit 0
fi
