#!/bin/bash
#
# Run deptry dependency checker and output results to JSON
#
# Checks for:
#   DEP001 - Missing dependencies (imported but not declared)
#   DEP004 - Misplaced dev dependencies (dev dep used in production code)
#
# Exit codes:
#   0 - No dependency issues found
#   1 - Dependency issues found
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_FILE="${PROJECT_ROOT}/untracked/qa/dependencies.json"

# Source venv management
# shellcheck source=../venv-include.bash
source "${PROJECT_ROOT}/scripts/venv-include.bash"

cd "${PROJECT_ROOT}"

# Ensure venv and deps
ensure_venv || exit 1
if ! "${VENV_PYTHON}" -c "import deptry" 2>/dev/null; then
    install_deps || exit 1
fi

# Ensure output directory exists
mkdir -p "$(dirname "${OUTPUT_FILE}")"

echo "Running deptry dependency checker..."

# Run deptry on src/ only, capture output
# Only check DEP001 (missing) and DEP004 (misplaced) - the real issues
# DEP002 (unused) and DEP003 (transitive/self) are configured as ignored in pyproject.toml
if venv_tool deptry src/ --json-output "${OUTPUT_FILE}.raw" 2>&1; then
    : # No issues found
fi
# Issues (if any) are captured as JSON in the output file for parsing below

# Parse deptry JSON output and transform to our format
"${VENV_PYTHON}" << 'PYEOF' > "${OUTPUT_FILE}"
import json
import sys
from pathlib import Path

raw_file = Path("untracked/qa/dependencies.json.raw")
issues_raw = []
if raw_file.exists() and raw_file.stat().st_size > 0:
    try:
        with open(raw_file) as f:
            content = f.read().strip()
            if content:
                issues_raw = json.loads(content)
    except json.JSONDecodeError:
        issues_raw = []

# Transform to our format
issues = []
for item in issues_raw:
    violation_code = item.get("error", {}).get("code", "")
    violation_msg = item.get("error", {}).get("message", "")
    module = item.get("module", "")

    issues.append({
        "rule": violation_code,
        "module": module,
        "message": violation_msg,
    })

# Build summary
summary = {
    "total_issues": len(issues),
    "missing_deps": sum(1 for i in issues if i["rule"] == "DEP001"),
    "misplaced_deps": sum(1 for i in issues if i["rule"] == "DEP004"),
    "passed": len(issues) == 0,
}

output = {
    "tool": "deptry",
    "summary": summary,
    "issues": issues,
}

json.dump(output, sys.stdout, indent=2)
print()
PYEOF

# Clean up raw file
rm -f "${OUTPUT_FILE}.raw"

# Print summary
echo ""
echo "Dependency Check Results:"
"${VENV_PYTHON}" -c "
import json
import sys
with open('${OUTPUT_FILE}') as f:
    data = json.load(f)
    summary = data['summary']
    print(f\"  Total issues: {summary['total_issues']}\")
    print(f\"  Missing deps (DEP001): {summary['missing_deps']}\")
    print(f\"  Misplaced deps (DEP004): {summary['misplaced_deps']}\")
    print(f\"  Status: {'✅ PASSED' if summary['passed'] else '❌ FAILED'}\")
    sys.exit(0 if summary['passed'] else 1)
"
