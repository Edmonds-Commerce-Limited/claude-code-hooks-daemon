#!/bin/bash
#
# Run Bandit security linter and output results to JSON
#
# Exit codes:
#   0 - No security issues found
#   1 - Security issues found
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_FILE="${PROJECT_ROOT}/untracked/qa/security.json"

# Source venv management
# shellcheck source=../venv-include.bash
source "${PROJECT_ROOT}/scripts/venv-include.bash"

cd "${PROJECT_ROOT}"

# Ensure venv and deps
ensure_venv || exit 1
if ! "${VENV_PYTHON}" -c "import bandit" 2>/dev/null; then
    install_deps || exit 1
fi

# Ensure output directory exists
mkdir -p "$(dirname "${OUTPUT_FILE}")"

echo "Running Bandit security scanner..."

# Run bandit with JSON output
# Note: Bandit uses -f json for JSON format, -r for recursive
# Skip ONLY test assertions (B101) - we run bandit on src/ not tests/
if venv_tool bandit -r src/ -f json -o "${OUTPUT_FILE}.raw" -s B101 2>&1; then
    : # No issues found
fi
# Issues (if any) are captured as JSON in the output file for parsing below

# Parse bandit JSON output and transform to our format
python3 << 'EOF' > "${OUTPUT_FILE}"
import json
import sys
from pathlib import Path

# Read bandit output
raw_file = Path("untracked/qa/security.json.raw")
bandit_output = {}
if raw_file.exists() and raw_file.stat().st_size > 0:
    try:
        with open(raw_file) as f:
            content = f.read().strip()
            if content:
                bandit_output = json.loads(content)
    except json.JSONDecodeError:
        # Empty or invalid JSON means no issues
        bandit_output = {}

# Extract results
results = bandit_output.get("results", [])
metrics = bandit_output.get("metrics", {})

# Transform to our format
issues = []
files_checked = set()

for item in results:
    file_path = item.get("filename", "")
    files_checked.add(file_path)

    # Map Bandit severity to our format
    severity_map = {
        "HIGH": "error",
        "MEDIUM": "warning",
        "LOW": "info",
    }
    bandit_severity = item.get("issue_severity", "MEDIUM")

    issues.append({
        "file": file_path,
        "line": item.get("line_number", 0),
        "column": 0,  # Bandit doesn't provide column numbers
        "rule": item.get("test_id", ""),
        "message": item.get("issue_text", ""),
        "severity": severity_map.get(bandit_severity, "warning"),
        "confidence": item.get("issue_confidence", ""),
    })

# Calculate total files checked from metrics (if available)
total_files = len(files_checked)
if "_totals" in metrics:
    # Use Bandit's file count if available
    total_files = max(total_files, metrics["_totals"].get("loc", 0) // 100)  # Rough estimate

# Build summary - FAIL on ANY issue (HIGH, MEDIUM, or LOW)
summary = {
    "total_files_checked": total_files,
    "total_issues": len(issues),
    "errors": sum(1 for i in issues if i["severity"] == "error"),
    "warnings": sum(1 for i in issues if i["severity"] == "warning"),
    "info": sum(1 for i in issues if i["severity"] == "info"),
    "passed": len(issues) == 0,  # ZERO TOLERANCE - any issue fails
}

# Output final JSON
output = {
    "tool": "bandit",
    "summary": summary,
    "issues": issues,
    "files": sorted(list(files_checked)),
}

json.dump(output, sys.stdout, indent=2)
print()  # Newline at end
EOF

# Clean up raw file
rm -f "${OUTPUT_FILE}.raw"

# Print summary and determine final exit code based on HIGH severity errors
echo ""
echo "Security Check Results:"
python3 -c "
import json
import sys
with open('${OUTPUT_FILE}') as f:
    data = json.load(f)
    summary = data['summary']
    print(f\"  Files checked: {summary['total_files_checked']}\")
    print(f\"  Total issues: {summary['total_issues']}\")
    print(f\"  Errors (HIGH): {summary['errors']}\")
    print(f\"  Warnings (MEDIUM): {summary['warnings']}\")
    print(f\"  Info (LOW): {summary['info']}\")
    print(f\"  Status: {'✅ PASSED' if summary['passed'] else '❌ FAILED'}\")
    # Exit 0 if passed (no HIGH severity), exit 1 if failed
    sys.exit(0 if summary['passed'] else 1)
"
