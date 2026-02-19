#!/bin/bash
#
# Run shellcheck on all shell scripts and output results to JSON
#
# Exit codes:
#   0 - No issues found
#   1 - Issues found or shellcheck not installed
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_FILE="${PROJECT_ROOT}/untracked/qa/shell_check.json"

mkdir -p "$(dirname "${OUTPUT_FILE}")"

echo "Running shellcheck on shell scripts..."

# Check shellcheck is installed
if ! command -v shellcheck &>/dev/null; then
    echo "❌ shellcheck not installed"
    echo "   Install via Dockerfile: apt-get install shellcheck"
    cat > "${OUTPUT_FILE}" << 'ENDJSON'
{
  "tool": "shellcheck",
  "summary": {
    "total_files_checked": 0,
    "total_issues": 0,
    "errors": 0,
    "warnings": 0,
    "passed": false,
    "error": "shellcheck not installed"
  },
  "issues": [],
  "files": []
}
ENDJSON
    exit 1
fi

# Collect all shell scripts under scripts/ and src/
mapfile -t SHELL_SCRIPTS < <(find "${PROJECT_ROOT}/scripts" "${PROJECT_ROOT}/src" -name "*.sh" -o -name "*.bash" | sort)

FILE_COUNT="${#SHELL_SCRIPTS[@]}"
echo "Found ${FILE_COUNT} shell scripts"

if [ "${FILE_COUNT}" -eq 0 ]; then
    python3 - << 'PYEOF' > "${OUTPUT_FILE}"
import json, sys
json.dump({"tool": "shellcheck", "summary": {"total_files_checked": 0, "total_issues": 0,
    "errors": 0, "warnings": 0, "passed": True}, "issues": [], "files": []}, sys.stdout, indent=2)
print()
PYEOF
    exit 0
fi

# Run shellcheck with JSON output
# Source directives in individual scripts handle venv-include.bash resolution,
# so no global SC suppressions are needed here.
if shellcheck -x -f json "${SHELL_SCRIPTS[@]}" > "${OUTPUT_FILE}.raw" 2>&1; then
    : # No issues found
fi
# Issues (if any) are captured as JSON in the output file for parsing below

# Write file list for Python to read
printf '%s\n' "${SHELL_SCRIPTS[@]}" > "${OUTPUT_FILE}.files"

# Parse shellcheck JSON output to standard QA format
python3 - << PYEOF > "${OUTPUT_FILE}"
import json, sys
from pathlib import Path

raw_file = Path("${OUTPUT_FILE}.raw")
sc_output = []
if raw_file.exists() and raw_file.stat().st_size > 0:
    try:
        content = raw_file.read_text().strip()
        if content:
            sc_output = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        sc_output = []

severity_map = {"error": "error", "warning": "warning", "info": "info", "style": "info"}

issues = []
for item in sc_output:
    issues.append({
        "file": item.get("file", ""),
        "line": item.get("line", 0),
        "column": item.get("column", 0),
        "rule": "SC{}".format(item.get("code", "")),
        "message": item.get("message", ""),
        "severity": severity_map.get(item.get("level", "warning"), "warning"),
    })

all_files = [f for f in Path("${OUTPUT_FILE}.files").read_text().strip().splitlines() if f]
summary = {
    "total_files_checked": len(all_files),
    "total_issues": len(issues),
    "errors": sum(1 for i in issues if i["severity"] == "error"),
    "warnings": sum(1 for i in issues if i["severity"] == "warning"),
    "info": sum(1 for i in issues if i["severity"] == "info"),
    "passed": sum(1 for i in issues if i["severity"] in ("error", "warning")) == 0,
}

json.dump({"tool": "shellcheck", "summary": summary, "issues": issues,
    "files": sorted(all_files)}, sys.stdout, indent=2)
print()
PYEOF

rm -f "${OUTPUT_FILE}.raw" "${OUTPUT_FILE}.files"

echo ""
echo "Shell Check Results:"
python3 - << PYEOF
import json, sys
with open("${OUTPUT_FILE}") as f:
    data = json.load(f)
s = data["summary"]
print(f"  Files checked: {s['total_files_checked']}")
print(f"  Total issues: {s['total_issues']}")
print(f"  Errors: {s['errors']}")
print(f"  Warnings: {s['warnings']}")
print(f"  Info: {s['info']}")
print(f"  Status: {'✅ PASSED' if s['passed'] else '❌ FAILED'}")
sys.exit(0 if s["passed"] else 1)
PYEOF
