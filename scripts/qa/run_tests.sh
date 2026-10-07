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
# The coverage JSON REPORT. Not named COVERAGE_FILE: coverage.py reads an
# exported COVERAGE_FILE as the DATA file path, which is the one thing this
# report must never be (shard mode exports that name for the data file below).
COVERAGE_JSON="${PROJECT_ROOT}/untracked/qa/coverage.json"
FIRST_ERROR_LINES_FILE="${PROJECT_ROOT}/untracked/qa/first-error-lines.jsonl"

# Shard mode (Plan 00500 Task 2.4), driven by run_test_matrix.py:
#   run_tests.sh --shard NAME --output FILE --coverage-data FILE -- PYTEST_ARG...
# runs only PYTEST_ARG... (paths and --ignore=), writes this shard's report to
# FILE and its coverage DATA to --coverage-data, and judges no coverage: the
# data files of every shard are combined afterwards and the fail_under verdict
# is taken once, on the whole. With no arguments the script runs all of tests/
# with coverage and judges it, as it always has.
SHARD=""
COVERAGE_DATA=""
COVERAGE_JSON_REPORT=""
PYTEST_TARGETS=(tests/)
if [ "${1:-}" = "--shard" ]; then
    if [ "$#" -lt 8 ] || [ "$3" != "--output" ] || [ "$5" != "--coverage-data" ] || [ "$7" != "--" ]; then
        echo "usage: run_tests.sh [--shard NAME --output FILE --coverage-data FILE -- PYTEST_ARG...]" >&2
        exit 2
    fi
    SHARD="$2"
    OUTPUT_FILE="$4"
    COVERAGE_DATA="$6"
    shift 7
    PYTEST_TARGETS=("$@")
    FIRST_ERROR_LINES_FILE="${OUTPUT_FILE%.json}.first-error-lines.jsonl"
    # The data file and the JSON report must be different files, always.
    if [ "${COVERAGE_DATA}" = "${COVERAGE_JSON}" ]; then
        echo "run_tests.sh: --coverage-data must not be the coverage JSON report ${COVERAGE_JSON}" >&2
        exit 2
    fi
elif [ "$#" -ne 0 ]; then
    echo "usage: run_tests.sh [--shard NAME --output FILE --coverage-data FILE -- PYTEST_ARG...]" >&2
    exit 2
fi

# Coverage options: a whole run reports to the terminal and the JSON file and
# is held to pyproject's fail_under by pytest-cov; a shard writes only its data
# file (COVERAGE_FILE, exported for coverage.py) and is held to nothing.
COVERAGE_ARGS=(--cov=src/claude_code_hooks_daemon --cov=.claude/ccy --cov-branch)
if [ -n "${SHARD}" ]; then
    export COVERAGE_FILE="${COVERAGE_DATA}"
    COVERAGE_ARGS+=(--cov-report= --cov-fail-under=0)
else
    COVERAGE_ARGS+=(--cov-report=term-missing:skip-covered --cov-report=json:"${COVERAGE_JSON}")
    COVERAGE_JSON_REPORT="${COVERAGE_JSON}"
fi

# Each failed or errored test's first error line, put on its tests.json record
# as "reason" so the gate's summary says why it failed, not only which (00466
# N196). The plugin appends, so a previous run's file is removed first.
# tests/conftest.py loads the plugin; `-p` would import the package before
# coverage starts and leave its import-time code unmeasured (N110).
FIRST_ERROR_ARGS=(--first-error-lines="${FIRST_ERROR_LINES_FILE}")

# The slowest tests, recorded in tests.json as "slowest_tests" (Plan 00500
# Task 1.3). Mirrors claude_code_hooks_daemon.qa.pytest_text_report
# .SLOWEST_DURATIONS_ARGS; a test pins the two together.
SLOWEST_DURATIONS_ARGS=(--durations=50 --durations-min=1.0)

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

# Plan 00463 round 9: this script drives a whole-suite pytest run, so it must
# hold the host-wide full-QA lock BEFORE pytest collects — the sink in
# tests/conftest.py (claude_code_hooks_daemon.qa.full_qa_gate) refuses a
# whole-suite-sized selection with no lock held, no matter what launched it.
# `exec {FD}>>` opens a plain (non-CLOEXEC) descriptor, so `venv_tool pytest`
# below — an ordinary child of THIS shell — inherits it for free; nothing
# downstream needs to know the fd number, only that the file it points at
# resolves to the same lock (verified via /proc/self/fd, not this variable).
# Review 10 m1: the wait is BOUNDED and names the holding pid(s) on timeout
# (see scripts/qa/acquire_full_qa_lock.bash) — an unbounded `flock` here
# hangs forever against a leaked lock with no diagnostic at all.
# shellcheck source=./acquire_full_qa_lock.bash
source "${SCRIPT_DIR}/acquire_full_qa_lock.bash"
GIT_COMMON_DIR="$(git -C "${PROJECT_ROOT}" rev-parse --path-format=absolute --git-common-dir)"
FULL_QA_LOCK="${GIT_COMMON_DIR}/hooksdaemon-full-qa.lock"
acquire_full_qa_lock_or_die "${FULL_QA_LOCK}"

# Ensure output directory exists
mkdir -p "$(dirname "${OUTPUT_FILE}")"
rm -f "${FIRST_ERROR_LINES_FILE}"

echo "Running pytest with coverage..."

# Run pytest with JSON report
# Note: pytest-json-report plugin needed for native JSON output
# If not installed, we'll parse JUnit XML output instead
if "${VENV_PYTHON}" -c "import pytest_json_report" 2>/dev/null; then
    # Use pytest-json-report if available
    if venv_tool pytest --json-report --json-report-file="${OUTPUT_FILE}.raw" \
              "${FIRST_ERROR_ARGS[@]}" \
              "${SLOWEST_DURATIONS_ARGS[@]}" \
              "${COVERAGE_ARGS[@]}" \
              "${PYTEST_TARGETS[@]}"; then
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
    PYTEST_RUN_EXIT_CODE="${EXIT_CODE}" RAW_FILE="${OUTPUT_FILE}.raw" \
    FIRST_ERROR_LINES_FILE="${FIRST_ERROR_LINES_FILE}" \
    COVERAGE_JSON_REPORT="${COVERAGE_JSON_REPORT}" "${VENV_PYTHON}" << 'EOF' > "${OUTPUT_FILE}"
import json
import os
import sys
from pathlib import Path

from claude_code_hooks_daemon.qa.first_error_lines import attach_first_error_lines
from claude_code_hooks_daemon.qa.pytest_text_report import build_json_report_summary

raw_file = Path(os.environ["RAW_FILE"])
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
attach_first_error_lines(tests, Path(os.environ["FIRST_ERROR_LINES_FILE"]))

# Read coverage data
# Empty in shard mode: a shard judges no coverage, and an old whole run's
# coverage.json must not stand in for one.
coverage_report = os.environ["COVERAGE_JSON_REPORT"]
coverage_file = Path(coverage_report) if coverage_report else None
coverage = {}
if coverage_file is not None and coverage_file.exists():
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
    if venv_tool pytest "${FIRST_ERROR_ARGS[@]}" \
              "${SLOWEST_DURATIONS_ARGS[@]}" \
              "${COVERAGE_ARGS[@]}" \
              --tb=short \
              "${PYTEST_TARGETS[@]}" 2>&1 | tee "${OUTPUT_FILE}.raw"; then
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
    PYTEST_RUN_EXIT_CODE="${EXIT_CODE}" RAW_FILE="${OUTPUT_FILE}.raw" \
    FIRST_ERROR_LINES_FILE="${FIRST_ERROR_LINES_FILE}" \
    COVERAGE_JSON_REPORT="${COVERAGE_JSON_REPORT}" "${VENV_PYTHON}" << 'EOF' > "${OUTPUT_FILE}"
import json
import os
import sys
from pathlib import Path

from claude_code_hooks_daemon.qa.first_error_lines import attach_first_error_lines
from claude_code_hooks_daemon.qa.pytest_text_report import (
    finalize_passed_all,
    find_unnamed_failure_reason,
    parse_pytest_text_output,
    parse_slowest_durations,
)

raw_file = Path(os.environ["RAW_FILE"])
content = raw_file.read_text() if raw_file.exists() else ""
report = parse_pytest_text_output(content)

exit_code = int(os.environ["PYTEST_RUN_EXIT_CODE"])

# Same record shape as the pytest-json-report path above, so consumers do not
# have to know which path produced the file. Only failures are listed: the text
# output names those and is silent about every passing test.
tests = [{"name": node_id, "outcome": "failed"} for node_id in report["failed_tests"]]
attach_first_error_lines(tests, Path(os.environ["FIRST_ERROR_LINES_FILE"]))

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

# 00466 N118: name the cause of a red run the failed/errored counts do not
# explain (a coverage-threshold miss is the known case) so the gate never
# reports "0 failed" over a run that did not pass.
unnamed_failure_reason = find_unnamed_failure_reason(
    content,
    failed=report["failed"],
    errors=report["errors"],
    total=report["total"],
    exit_code=exit_code,
)
if unnamed_failure_reason is not None:
    summary["unnamed_failure_reason"] = unnamed_failure_reason

# Read coverage
# Empty in shard mode: a shard judges no coverage, and an old whole run's
# coverage.json must not stand in for one.
coverage_report = os.environ["COVERAGE_JSON_REPORT"]
coverage_file = Path(coverage_report) if coverage_report else None
coverage = {}
if coverage_file is not None and coverage_file.exists():
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
    "slowest_tests": parse_slowest_durations(content),
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
