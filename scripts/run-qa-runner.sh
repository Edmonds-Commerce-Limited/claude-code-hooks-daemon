#!/bin/bash
# QA Runner Invocation Script
# Fast entry point for running QA checks via the daemon module

set -e

PROJECT_ROOT="${1:-.}"
TOOLS="${2:-eslint,typescript,prettier,cspell}"
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

# Build command
CMD="python3 -m claude_code_hooks_daemon.qa.runner"
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
