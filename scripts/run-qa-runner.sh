#!/bin/bash
# QA Runner Invocation Script
# Fast entry point for running QA checks via the daemon module

set -e

# Anchor to THIS script's location, not the caller's cwd — the project root
# argument below is the directory being CHECKED, which is not necessarily the
# daemon repo whose venv we need.
_QA_RUNNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_QA_RUNNER_REPO_ROOT="${_QA_RUNNER_DIR%/*}"

PROJECT_ROOT="${1:-.}"
# Default mirrors the module CLI's own default (qa/runner.py --tools) — the
# previous "eslint,typescript,prettier,cspell" default named tools the module
# does not implement (it runs Python tools only), so the no-args invocation
# silently asked for nothing runnable.
TOOLS="${2:-ruff,mypy,black,pytest}"
SAVE_RESULTS="${3:-true}"
OUTPUT_DIR="${4:-}"

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Colour

# Header
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}QA Runner - Daemon Module Invoker${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# Show configuration
echo -e "${YELLOW}Configuration:${NC}"
echo "  Project Root: $PROJECT_ROOT"
echo "  Tools: $TOOLS"
echo "  Save Results: $SAVE_RESULTS"
if [ -n "$OUTPUT_DIR" ]; then
    echo "  Output Dir: $OUTPUT_DIR"
fi
echo ""

# Resolve the daemon's interpreter via the canonical library (Plan 00104
# Decision 7 — single source of truth for venv resolution). A bare `python3`
# CANNOT import the package: the venv is built with
# include-system-site-packages = false, so this script previously died with
# "ModuleNotFoundError: No module named 'claude_code_hooks_daemon'" — the exact
# failure docs/QA.md warns readers about, in the very wrapper it
# tells them to use instead. Stderr is NOT silenced: a resolver failure must
# surface to the operator rather than degrade silently.
# shellcheck source=lib/resolve_venv.sh
source "${_QA_RUNNER_DIR}/lib/resolve_venv.sh"
if ! PYTHON_BIN="$(resolve_venv_python "${_QA_RUNNER_REPO_ROOT}")"; then
    echo -e "${RED}✗ Could not resolve the daemon virtualenv.${NC}" >&2
    echo "  Install or repair the daemon before running QA checks." >&2
    exit 2
fi

# Build command
CMD="$PYTHON_BIN -m claude_code_hooks_daemon.qa.runner"
CMD="$CMD --project-root $PROJECT_ROOT"
CMD="$CMD --tools $TOOLS"

if [ "$SAVE_RESULTS" = "true" ]; then
    CMD="$CMD --save-results"
fi

if [ -n "$OUTPUT_DIR" ]; then
    CMD="$CMD --output-dir $OUTPUT_DIR"
fi

# Show command
echo -e "${BLUE}Command:${NC}"
echo "  $CMD"
echo ""

# Execute
echo -e "${BLUE}Executing QA checks...${NC}"
echo ""

if eval "$CMD"; then
    EXIT_CODE=$?
    echo ""
    echo -e "${GREEN}✓ QA execution completed successfully${NC}"
    exit 0
else
    EXIT_CODE=$?
    echo ""
    if [ $EXIT_CODE -eq 1 ]; then
        echo -e "${RED}✗ QA checks found issues (exit code: 1)${NC}"
    else
        echo -e "${RED}✗ QA execution failed (exit code: $EXIT_CODE)${NC}"
    fi
    exit $EXIT_CODE
fi
