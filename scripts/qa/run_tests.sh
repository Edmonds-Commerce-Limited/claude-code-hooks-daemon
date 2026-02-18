#!/bin/bash
#
# Run pytest with coverage and output results to JSON
#
# Exit codes:
#   0 - All tests passed
#   1 - Tests failed
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_FILE="${PROJECT_ROOT}/untracked/qa/tests.json"
COVERAGE_FILE="${PROJECT_ROOT}/untracked/qa/coverage.json"

# Source venv management
# shellcheck source=../venv-include.bash
source "${PROJECT_ROOT}/scripts/venv-include.bash"

cd "${PROJECT_ROOT}"

# Ensure venv and deps
ensure_venv || exit 1
if ! "${VENV_PYTHON}" -c "import pytest" 2>/dev/null; then
    install_deps || exit 1
fi

# Ensure output directory exists
mkdir -p "$(dirname "${OUTPUT_FILE}")"

echo "Running pytest with coverage..."

# Run pytest with JSON report
# Note: pytest-json-report plugin needed for native JSON output
# If not installed, we'll parse JUnit XML output instead
if "${VENV_PYTHON}" -c "import pytest_json_report" 2>/dev/null; then
    # Use pytest-json-report if available
    if venv_tool pytest --json-report --json-report-file="${OUTPUT_FILE}.raw" \
              --cov=src/claude_code_hooks_daemon \
              --cov-report=json:"${COVERAGE_FILE}" \
              tests/; then
        EXIT_CODE=0
    else
        EXIT_CODE=$?
    fi

    # Transform pytest-json-report format to our format
    python3 << 'EOF' > "${OUTPUT_FILE}"
import json
import sys
from pathlib import Path

raw_file = Path("untracked/qa/tests.json.raw")
if raw_file.exists():
    with open(raw_file) as f:
        pytest_data = json.load(f)
else:
    pytest_data = {}

# Extract test results
tests = []
for test in pytest_data.get("tests", []):
    tests.append({
        "name": test.get("nodeid", ""),
        "outcome": test.get("outcome", ""),
        "duration": test.get("call", {}).get("duration", 0),
    })

# Extract summary
summary_data = pytest_data.get("summary", {})
summary = {
    "total": summary_data.get("total", 0),
    "passed": summary_data.get("passed", 0),
    "failed": summary_data.get("failed", 0),
    "skipped": summary_data.get("skipped", 0),
    "duration": pytest_data.get("duration", 0),
    "passed_all": summary_data.get("failed", 0) == 0,
}

# Read coverage data
coverage_file = Path("untracked/qa/coverage.json")
coverage = {}
if coverage_file.exists():
    with open(coverage_file) as f:
        cov_data = json.load(f)
        coverage = {
            "percent_covered": cov_data.get("totals", {}).get("percent_covered", 0),
            "num_statements": cov_data.get("totals", {}).get("num_statements", 0),
            "missing_lines": cov_data.get("totals", {}).get("missing_lines", 0),
        }

output = {
    "tool": "pytest",
    "summary": summary,
    "tests": tests,
    "coverage": coverage,
}

json.dump(output, sys.stdout, indent=2)
print()
EOF
else
    # Fallback: Parse standard pytest output
    if venv_tool pytest --cov=src/claude_code_hooks_daemon \
              --cov-report=json:"${COVERAGE_FILE}" \
              --tb=short \
              tests/ 2>&1 | tee "${OUTPUT_FILE}.raw"; then
        EXIT_CODE=0
    else
        EXIT_CODE=$?
    fi

    # Parse text output
    python3 << 'EOF' > "${OUTPUT_FILE}"
import json
import re
import sys
from pathlib import Path

raw_file = Path("untracked/qa/tests.json.raw")
passed = 0
failed = 0
skipped = 0
total = 0

if raw_file.exists():
    with open(raw_file) as f:
        content = f.read()

        # Parse pytest summary line
        # Example: "====== 364 passed in 0.52s ======"
        match = re.search(r'(\d+) passed', content)
        if match:
            passed = int(match.group(1))
            total += passed

        match = re.search(r'(\d+) failed', content)
        if match:
            failed = int(match.group(1))
            total += failed

        match = re.search(r'(\d+) skipped', content)
        if match:
            skipped = int(match.group(1))
            total += skipped

summary = {
    "total": total,
    "passed": passed,
    "failed": failed,
    "skipped": skipped,
    "passed_all": failed == 0,
}

# Read coverage
coverage_file = Path("untracked/qa/coverage.json")
coverage = {}
if coverage_file.exists():
    with open(coverage_file) as f:
        cov_data = json.load(f)
        coverage = {
            "percent_covered": cov_data.get("totals", {}).get("percent_covered", 0),
            "num_statements": cov_data.get("totals", {}).get("num_statements", 0),
            "missing_lines": cov_data.get("totals", {}).get("missing_lines", 0),
        }

output = {
    "tool": "pytest",
    "summary": summary,
    "tests": [],  # Not parsed from text output
    "coverage": coverage,
}

json.dump(output, sys.stdout, indent=2)
print()
EOF
fi

# Clean up raw file
rm -f "${OUTPUT_FILE}.raw"

# Print summary
echo ""
echo "Test Results:"
python3 -c "
import json
with open('${OUTPUT_FILE}') as f:
    data = json.load(f)
    summary = data['summary']
    coverage = data.get('coverage', {})
    print(f\"  Total tests: {summary['total']}\")
    print(f\"  Passed: {summary['passed']}\")
    print(f\"  Failed: {summary['failed']}\")
    print(f\"  Skipped: {summary['skipped']}\")
    if coverage:
        print(f\"  Coverage: {coverage.get('percent_covered', 0):.1f}%\")
    print(f\"  Status: {'✅ PASSED' if summary['passed_all'] else '❌ FAILED'}\")
"

exit ${EXIT_CODE}
