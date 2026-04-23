#!/bin/bash
#
# parse_min_python.sh - Extract minimum Python version from pyproject.toml
#
# Plan 00100 Task 0.3: Single source of truth for the daemon's minimum
# Python version — parsed from pyproject.toml:requires-python at runtime,
# never hardcoded. Used by skill wrappers (install.sh, upgrade.sh) to
# pre-check the active python3 BEFORE mutating daemon state.
#
# Usage:
#   bash parse_min_python.sh [PYPROJECT_PATH]
#
# Arguments:
#   PYPROJECT_PATH (optional): Path to pyproject.toml.
#                              Defaults to $SCRIPT_DIR/../../pyproject.toml.
#
# Output:
#   MAJOR.MINOR string (e.g. "3.11") on stdout, exit 0
#   Error message on stderr, exit 1 on parse failure
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYPROJECT_PATH="${1:-$SCRIPT_DIR/../../pyproject.toml}"

if [ ! -f "$PYPROJECT_PATH" ]; then
    echo "Error: pyproject.toml not found at $PYPROJECT_PATH" >&2
    exit 1
fi

# Extract `requires-python = ">=3.11"` line and capture MAJOR.MINOR.
# grep returns non-zero when no match — we handle that explicitly.
if ! line="$(grep -E '^requires-python\s*=' "$PYPROJECT_PATH")"; then
    echo "Error: requires-python not found in $PYPROJECT_PATH" >&2
    exit 1
fi

# Strip everything except the first N.N match.
if ! version="$(echo "$line" | grep -oE '[0-9]+\.[0-9]+' | head -n 1)"; then
    echo "Error: Could not parse version from: $line" >&2
    exit 1
fi

if [ -z "$version" ]; then
    echo "Error: Could not parse version from: $line" >&2
    exit 1
fi

echo "$version"
