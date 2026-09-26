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

# llm_qa.py's `tests` tool is `live_daemon=True`: `ensure_live_daemon` starts
# this checkout's daemon before this script runs, but a start failure there
# does not abort -- it only prints a message, and this script still runs
# with no daemon live. blocking_gate_guard.py (tests/acceptance/) only
# escalates a skip of a declared release-gate file to a failure when this is
# set (Plan 00466 N39 widened); without it, that daemon-start failure would
# leave those tests skipping quietly instead of failing this gate.
export HOOKS_DAEMON_RELEASE_GATE=1

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
              --cov=.claude/ccy \
              --cov-branch \
              --cov-report=term-missing:skip-covered \
              --cov-report=json:"${COVERAGE_FILE}" \
              tests/; then
        EXIT_CODE=0
    else
        EXIT_CODE=$?
    fi

    # Transform pytest-json-report format to our format.
    #
    # Runs under VENV_PYTHON (not system python3) so
    # claude_code_hooks_daemon.qa.pytest_text_report is importable: the
    # verdict is built there, not re-derived here, so a runner that wrote no
    # raw report at all (crashed before pytest-json-report could) and a
    # runner that exited non-zero over a clean-looking summary are both
    # caught the same way the text-fallback branch below catches them
    # (00466 N21 -- build_json_report_summary / finalize_passed_all).
    PYTEST_RUN_EXIT_CODE="${EXIT_CODE}" "${VENV_PYTHON}" << 'EOF' > "${OUTPUT_FILE}"
import json
import os
import sys
from pathlib import Path

from claude_code_hooks_daemon.qa.pytest_text_report import build_json_report_summary

raw_file = Path("untracked/qa/tests.json.raw")
# None (not {}) when the raw report never existed: a runner that crashed
# before writing one produced no verdict at all, which must not be
# conflated with a report that legitimately says "0 found".
pytest_data = json.loads(raw_file.read_text()) if raw_file.exists() else None

exit_code = int(os.environ["PYTEST_RUN_EXIT_CODE"])
summary = build_json_report_summary(pytest_data, exit_code)

# Extract test results
tests = []
if pytest_data is not None:
    for test in pytest_data.get("tests", []):
        tests.append({
            "name": test.get("nodeid", ""),
            "outcome": test.get("outcome", ""),
            "duration": test.get("call", {}).get("duration", 0),
        })

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
              --cov=.claude/ccy \
              --cov-branch \
              --cov-report=term-missing:skip-covered \
              --cov-report=json:"${COVERAGE_FILE}" \
              --tb=short \
              tests/ 2>&1 | tee "${OUTPUT_FILE}.raw"; then
        EXIT_CODE=0
    else
        EXIT_CODE=$?
    fi

    # Parse text output.
    #
    # Runs under VENV_PYTHON, not system python3, so the parsing module is
    # importable. The logic lives in claude_code_hooks_daemon.qa
    # .pytest_text_report rather than in this heredoc so it can be unit-tested
    # against real captured pytest output (Plan 00226) — scraping only the
    # counts here meant a red QA run reported "2 failed" without ever saying
    # WHICH, and one such failure was never identified.
    #
    # finalize_passed_all combines the parser's own verdict with pytest's
    # process exit code (00466 N21): the parser only ever sees console text,
    # so a runner that exits non-zero for a reason its summary line does not
    # capture would otherwise still read green.
    PYTEST_RUN_EXIT_CODE="${EXIT_CODE}" "${VENV_PYTHON}" << 'EOF' > "${OUTPUT_FILE}"
import json
import os
import sys
from pathlib import Path

from claude_code_hooks_daemon.qa.pytest_text_report import (
    finalize_passed_all,
    parse_pytest_text_output,
)

raw_file = Path("untracked/qa/tests.json.raw")
content = raw_file.read_text() if raw_file.exists() else ""
report = parse_pytest_text_output(content)

exit_code = int(os.environ["PYTEST_RUN_EXIT_CODE"])

# Same record shape as the pytest-json-report path above, so consumers do not
# have to know which path produced the file. Only failures are listed: the text
# output names those and is silent about every passing test.
tests = [{"name": node_id, "outcome": "failed"} for node_id in report["failed_tests"]]

summary = {
    "total": report["total"],
    "passed": report["passed"],
    "failed": report["failed"],
    "skipped": report["skipped"],
    # Carried separately from "failed" because pytest counts them separately:
    # a fixture that blows up during setup or teardown is an ERROR, and
    # omitting it here let tests.json report a red run as green.
    "errors": report["errors"],
    "passed_all": finalize_passed_all(report["passed_all"], exit_code),
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
    "tests": tests,
    "coverage": coverage,
}

json.dump(output, sys.stdout, indent=2)
print()
EOF
fi

# Keep the raw pytest log when the run FAILED. Deleting it unconditionally
# meant a red gate reported "1 failed" and then destroyed the only record of
# WHICH test failed — the JSON summary carries counts, not names. Diagnosing
# a failure then required re-running the whole suite and hoping it reproduced,
# which for an order- or environment-dependent failure it may not.
if [ "${EXIT_CODE}" -eq 0 ]; then
    rm -f "${OUTPUT_FILE}.raw"
else
    echo "" >&2
    echo "Raw pytest output retained for diagnosis:" >&2
    echo "  ${OUTPUT_FILE}.raw" >&2
    echo "  grep -a 'FAILED' '${OUTPUT_FILE}.raw'" >&2
fi

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
