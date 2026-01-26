#!/bin/bash
#
# Run ruff linter (auto-fixes by default) and output results to JSON
#
# Exit codes:
#   0 - No violations found
#   1 - Violations found
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_FILE="${PROJECT_ROOT}/untracked/qa/lint.json"

# Source venv management
source "${PROJECT_ROOT}/scripts/venv-include.bash"

cd "${PROJECT_ROOT}"

# Ensure venv and deps
ensure_venv || exit 1
if ! "${VENV_PYTHON}" -c "import ruff" 2>/dev/null; then
    install_deps || exit 1
fi

# Ensure output directory exists
mkdir -p "$(dirname "${OUTPUT_FILE}")"

echo "Running ruff linter (auto-fixing)..."

# Run ruff with --fix to auto-fix issues, then check remaining violations
# Note: ruff outputs JSON natively with --output-format=json
if venv_tool ruff check --fix src/ tests/ --output-format=json > "${OUTPUT_FILE}.raw" 2>&1; then
    EXIT_CODE=0
else
    EXIT_CODE=$?
fi

# Parse ruff JSON output and transform to our format
python3 << 'EOF' > "${OUTPUT_FILE}"
import json
import sys
from pathlib import Path

# Read ruff output
raw_file = Path("untracked/qa/lint.json.raw")
ruff_output = []
if raw_file.exists() and raw_file.stat().st_size > 0:
    try:
        with open(raw_file) as f:
            content = f.read().strip()
            if content:
                ruff_output = json.loads(content)
    except json.JSONDecodeError:
        # Empty or invalid JSON means no violations
        ruff_output = []

# Transform to our format
violations = []
files_checked = set()

for item in ruff_output:
    file_path = item.get("filename", "")
    files_checked.add(file_path)

    violations.append({
        "file": file_path,
        "line": item.get("location", {}).get("row", 0),
        "column": item.get("location", {}).get("column", 0),
        "rule": item.get("code", ""),
        "message": item.get("message", ""),
        "severity": "error" if item.get("code", "").startswith("E") else "warning",
    })

# Build summary
summary = {
    "total_files_checked": len(files_checked),
    "total_violations": len(violations),
    "errors": sum(1 for v in violations if v["severity"] == "error"),
    "warnings": sum(1 for v in violations if v["severity"] == "warning"),
    "passed": len(violations) == 0,
}

# Output final JSON
output = {
    "tool": "ruff",
    "summary": summary,
    "violations": violations,
    "files": sorted(list(files_checked)),
}

json.dump(output, sys.stdout, indent=2)
print()  # Newline at end
EOF

# Clean up raw file
rm -f "${OUTPUT_FILE}.raw"

# Print summary
echo ""
echo "Lint Results:"
python3 -c "
import json
with open('${OUTPUT_FILE}') as f:
    data = json.load(f)
    summary = data['summary']
    print(f\"  Files checked: {summary['total_files_checked']}\")
    print(f\"  Violations: {summary['total_violations']}\")
    print(f\"  Errors: {summary['errors']}\")
    print(f\"  Warnings: {summary['warnings']}\")
    print(f\"  Status: {'✅ PASSED' if summary['passed'] else '❌ FAILED'}\")
"

exit ${EXIT_CODE}
