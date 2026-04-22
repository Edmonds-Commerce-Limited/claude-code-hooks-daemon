#!/bin/bash
#
# Worktree Setup Script
#
# Creates a git worktree with proper Python venv for agent team workflows.
# See CLAUDE/Worktree.md for full documentation.
#
# Usage:
#   ./scripts/setup_worktree.sh <branch-name>
#   ./scripts/setup_worktree.sh <branch-name> <base-branch>
#
# Examples:
#   # Create parent worktree from main:
#   ./scripts/setup_worktree.sh worktree-plan-00028
#
#   # Create child worktree from parent:
#   ./scripts/setup_worktree.sh worktree-child-plan-00028-handler-a worktree-plan-00028
#

set -euo pipefail

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Project root (always /workspace or wherever the main repo is)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKTREES_DIR="${PROJECT_ROOT}/untracked/worktrees"

# Load SSOT venv helpers (v3.7.0+ fingerprint-keyed layout).
# shellcheck source=install/output.sh
source "${SCRIPT_DIR}/install/output.sh"
# shellcheck source=install/python_fingerprint.sh
source "${SCRIPT_DIR}/install/python_fingerprint.sh"
# shellcheck source=install/venv.sh
source "${SCRIPT_DIR}/install/venv.sh"
# shellcheck source=install/venv_resolver.sh
source "${SCRIPT_DIR}/install/venv_resolver.sh"

# Read the daemon version string so ensure_venv can stamp the venv with it.
_read_daemon_version() {
    local version_file="$1"
    python3 - "$version_file" <<'PY'
import sys, re, pathlib
path = pathlib.Path(sys.argv[1])
match = re.search(r'__version__\s*=\s*"([^"]+)"', path.read_text())
if not match:
    sys.exit("version.py missing __version__")
print(match.group(1))
PY
}

usage() {
    echo "Usage: $0 <branch-name> [base-branch]"
    echo ""
    echo "Arguments:"
    echo "  branch-name   Branch name for the worktree (must start with 'worktree-')"
    echo "  base-branch   Optional base branch to create from (default: current branch)"
    echo ""
    echo "Examples:"
    echo "  # Parent worktree from main:"
    echo "  $0 worktree-plan-00028"
    echo ""
    echo "  # Child worktree from parent:"
    echo "  $0 worktree-child-plan-00028-handler-a worktree-plan-00028"
    exit 1
}

# Validate arguments
if [[ $# -lt 1 ]]; then
    usage
fi

BRANCH_NAME="$1"
BASE_BRANCH="${2:-}"

# Validate branch name prefix
if [[ ! "${BRANCH_NAME}" =~ ^worktree- ]]; then
    echo -e "${RED}ERROR${NC}: Branch name must start with 'worktree-'"
    echo "  Got: ${BRANCH_NAME}"
    echo "  Expected: worktree-plan-NNNNN or worktree-child-<parent>-<task>"
    exit 1
fi

# Validate child worktree has base branch specified
if [[ "${BRANCH_NAME}" =~ ^worktree-child- ]] && [[ -z "${BASE_BRANCH}" ]]; then
    echo -e "${YELLOW}WARNING${NC}: Child worktree without base branch."
    echo "  Child worktrees should branch from their parent:"
    echo "  $0 ${BRANCH_NAME} worktree-plan-NNNNN"
    echo ""
    echo "  Creating from current branch instead..."
fi

WORKTREE_DIR="${WORKTREES_DIR}/${BRANCH_NAME}"

echo -e "${CYAN}=== Worktree Setup ===${NC}"
echo "  Branch:    ${BRANCH_NAME}"
echo "  Base:      ${BASE_BRANCH:-<current branch>}"
echo "  Directory: ${WORKTREE_DIR}"
echo ""

# Step 1: Ensure worktrees directory exists
mkdir -p "${WORKTREES_DIR}"

# Step 2: Check if worktree already exists
if [[ -d "${WORKTREE_DIR}" ]]; then
    echo -e "${RED}ERROR${NC}: Worktree directory already exists: ${WORKTREE_DIR}"
    echo "  To remove: git worktree remove ${WORKTREE_DIR}"
    exit 1
fi

# Step 3: Create worktree
echo -e "${YELLOW}→${NC} Creating git worktree..."
cd "${PROJECT_ROOT}"
if [[ -n "${BASE_BRANCH}" ]]; then
    git worktree add "${WORKTREE_DIR}" -b "${BRANCH_NAME}" "${BASE_BRANCH}"
else
    git worktree add "${WORKTREE_DIR}" -b "${BRANCH_NAME}"
fi
echo -e "${GREEN}✓${NC} Worktree created"

# Step 4: Create fingerprint-keyed Python venv via SSOT helper.
# ensure_venv picks untracked/venv-{fingerprint}/ so concurrent containers
# with the same Python share one venv, and distinct Pythons don't collide.
DAEMON_VERSION="$(_read_daemon_version "${WORKTREE_DIR}/src/claude_code_hooks_daemon/version.py")"
echo -e "${YELLOW}→${NC} Creating Python venv (fingerprint-keyed) via uv sync..."
WT_VENV_PATH="$(ensure_venv "${WORKTREE_DIR}" "v${DAEMON_VERSION}" python3)"
if [[ -z "${WT_VENV_PATH}" ]] || [[ ! -x "${WT_VENV_PATH}/bin/python" ]]; then
    echo -e "${RED}✗${NC} Failed to create venv via ensure_venv"
    exit 1
fi
WT_VENV_PIP="${WT_VENV_PATH}/bin/pip"
echo -e "${GREEN}✓${NC} Venv created at ${WT_VENV_PATH}"

# Step 5: Verify editable install points to correct source
# uv sync already installed the package editable via pyproject; just verify.
EDITABLE_LOCATION=$("${WT_VENV_PIP}" show claude-code-hooks-daemon 2>/dev/null | grep "Editable project location" | cut -d' ' -f4-)
if [[ "${EDITABLE_LOCATION}" == "${WORKTREE_DIR}" ]]; then
    echo -e "${GREEN}✓${NC} Editable install points to worktree source: ${EDITABLE_LOCATION}"
else
    echo -e "${RED}✗${NC} Editable install points to WRONG location: ${EDITABLE_LOCATION}"
    echo "  Expected: ${WORKTREE_DIR}"
    echo "  This means tests will import from the wrong source!"
    exit 1
fi

# Step 7: Verify QA scripts are accessible
if [[ -x "${WORKTREE_DIR}/scripts/qa/run_all.sh" ]]; then
    echo -e "${GREEN}✓${NC} QA scripts accessible"
else
    echo -e "${YELLOW}⚠${NC}  QA scripts may not be executable (run chmod +x if needed)"
fi

# Step 8: Create daemon untracked directory
mkdir -p "${WORKTREE_DIR}/.claude/hooks-daemon/untracked"
echo -e "${GREEN}✓${NC} Daemon untracked directory created"

echo ""
echo -e "${GREEN}=== Worktree Ready ===${NC}"
echo ""
echo "Quick start:"
echo "  cd ${WORKTREE_DIR}"
echo "  PYTHON=${WT_VENV_PATH}/bin/python"
echo ""
echo "Run QA:"
echo "  cd ${WORKTREE_DIR} && ./scripts/qa/run_all.sh"
echo ""
echo "Verify daemon:"
echo "  \$PYTHON -m claude_code_hooks_daemon.daemon.cli restart"
echo "  \$PYTHON -m claude_code_hooks_daemon.daemon.cli status"
echo ""
echo "Agent prompt template:"
echo "  You are working in a git worktree at ${WORKTREE_DIR}/"
echo "  DO NOT work in /workspace - only work in YOUR worktree directory."
echo "  PYTHON=${WT_VENV_PATH}/bin/python"
echo "  Run ./scripts/qa/run_all.sh before committing."
