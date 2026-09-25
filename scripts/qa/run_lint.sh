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
# The QA_LINT_* overrides exist so tests/unit/qa/test_run_lint.py can drive
# this exact wrapper against a planted target and a fake ruff binary without
# touching the real scope (gate-scope.bash's ".") or the real
# untracked/qa/ output. Unset, they change nothing (00466 N21).
OUTPUT_DIR="${QA_LINT_OUTPUT_DIR:-${PROJECT_ROOT}/untracked/qa}"
OUTPUT_FILE="${OUTPUT_DIR}/lint.json"

# Source venv management
# shellcheck source=../venv-include.bash
source "${PROJECT_ROOT}/scripts/venv-include.bash"

# Source the shared gate scope (SSoT for which paths are examined)
# shellcheck source=./gate-scope.bash
source "${PROJECT_ROOT}/scripts/qa/gate-scope.bash"

cd "${PROJECT_ROOT}"

# Ensure venv and deps
ensure_venv || exit 1
if ! "${VENV_PYTHON}" -c "import ruff" 2>/dev/null; then
    install_deps || exit 1
fi

# Ensure output directory exists
mkdir -p "${OUTPUT_DIR}"

echo "Running ruff linter (auto-fixing)..."

# Run ruff with --fix to auto-fix issues, then check remaining violations
# Note: ruff outputs JSON natively with --output-format=json
# NO `2>&1` here (Plan 00200): ruff streams its JSON to stdout, so anything
# merged into that stream corrupts the capture. Diagnostics stay on stderr and
# reach the console, where they belong.
# NOT `mapfile` — that is bash 4+, and macOS ships /bin/bash 3.2.57.
# tests/integration/test_bash32_portability.py enforces this.
LINT_PATHS=()
if [ -n "${QA_LINT_PATHS:-}" ]; then
    LINT_PATHS=("${QA_LINT_PATHS}")
else
    while IFS= read -r _scope_path; do
        LINT_PATHS+=("${_scope_path}")
    done < <(qa_lint_paths)
fi
RUFF_BIN="${QA_LINT_RUFF_BIN:-${VENV_DIR}/bin/ruff}"

# 00466 N21: ruff's own contract is 0 = clean, 1 = violations found. Anything
# else means ruff did not complete a check at all -- a bad rule code, a
# broken config -- and whatever it wrote to stdout (usually nothing) cannot
# be trusted as a verdict.
if "${RUFF_BIN}" check --fix "${LINT_PATHS[@]}" --output-format=json > "${OUTPUT_FILE}.raw"; then
    RUFF_EXIT=0
else
    RUFF_EXIT=$?
fi

if [ "${RUFF_EXIT}" != "0" ] && [ "${RUFF_EXIT}" != "1" ]; then
    RUFF_ERROR_MESSAGE="ruff exited ${RUFF_EXIT} (expected 0 or 1) -- it did not complete a check, so nothing below was actually checked"
    echo "FATAL: ${RUFF_ERROR_MESSAGE}" >&2
    "${VENV_PYTHON}" -c '
import json
import sys

message = sys.argv[1]
output_file = sys.argv[2]
summary = {
    "total_files_checked": 0,
    "total_violations": 1,
    "errors": 1,
    "warnings": 0,
    "passed": False,
    "error": message,
}
output = {
    "tool": "ruff",
    "summary": summary,
    "violations": [{
        "file": "",
        "line": 0,
        "column": 0,
        "rule": "ruff-run-error",
        "message": message,
        "severity": "error",
    }],
    "files": [],
}
with open(output_file, "w") as f:
    json.dump(output, f, indent=2)
    f.write("\n")
' "${RUFF_ERROR_MESSAGE}" "${OUTPUT_FILE}"
    rm -f "${OUTPUT_FILE}.raw"
    exit 1
fi
# Violations (if any) are captured as JSON in the output file for parsing below

# Parse ruff JSON output and transform to our format
# QA_LINT_RAW_FILE lets the parser below (extracted verbatim and run
# standalone by tests/integration/test_qa_lint_gate_integrity.py, and driven
# end to end by tests/unit/qa/test_run_lint.py) read a planted/overridden raw
# capture; unset, it defaults to the path this script itself just wrote to.
export QA_LINT_RAW_FILE="${OUTPUT_FILE}.raw"
python3 << 'EOF' > "${OUTPUT_FILE}"
import json
import os
import sys
from pathlib import Path

# Read ruff output
raw_file = Path(os.environ.get("QA_LINT_RAW_FILE", "untracked/qa/lint.json.raw"))
ruff_output = []
# 00466 N21: a genuinely clean ruff run still writes "[]" (2 bytes) to
# stdout -- a ZERO-byte (or missing) capture means ruff wrote nothing at
# all, which is not the same fact and must not be read as "no violations".
# A report is written (to stdout, captured by the shell redirect above) so
# llm_qa's "count implies detail" check holds for this failure too.
if not raw_file.exists() or raw_file.stat().st_size == 0:
    no_capture_message = (
        "ruff produced no output capture -- nothing was checked "
        "(a clean run writes at least '[]')"
    )
    no_capture_summary = {
        "total_files_checked": 0,
        "total_violations": 1,
        "errors": 1,
        "warnings": 0,
        "passed": False,
        "error": no_capture_message,
    }
    no_capture_output = {
        "tool": "ruff",
        "summary": no_capture_summary,
        "violations": [{
            "file": "",
            "line": 0,
            "column": 0,
            "rule": "ruff-run-error",
            "message": no_capture_message,
            "severity": "error",
        }],
        "files": [],
    }
    json.dump(no_capture_output, sys.stdout, indent=2)
    print()
    print(f"FATAL: {no_capture_message}", file=sys.stderr)
    sys.exit(1)
try:
    with open(raw_file) as f:
        content = f.read().strip()
        if content:
            ruff_output = json.loads(content)
except json.JSONDecodeError as exc:
    # FAIL FAST (Plan 00200). This previously swallowed the error into
    # `ruff_output = []`, which made `passed` True and reported a green
    # gate over an unreadable capture -- hiding 47 real violations.
    # Genuinely-empty output is already handled by the st_size guard above,
    # so anything non-empty and unparseable is a defect, not a clean run.
    print(
        "FATAL: ruff output could not be parsed as JSON. The capture is "
        "corrupted -- something wrote to stdout alongside ruff.\n"
        f"  parse error: {exc}\n"
        f"  first 200 bytes: {content[:200]!r}",
        file=sys.stderr,
    )
    sys.exit(1)

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

# Print summary and exit based on violations, not auto-fix status
echo ""
echo "Lint Results:"
"${VENV_PYTHON}" -c "
import json
import sys
with open('${OUTPUT_FILE}') as f:
    data = json.load(f)
    summary = data['summary']
    print(f\"  Files checked: {summary['total_files_checked']}\")
    print(f\"  Violations: {summary['total_violations']}\")
    print(f\"  Errors: {summary['errors']}\")
    print(f\"  Warnings: {summary['warnings']}\")
    print(f\"  Status: {'✅ PASSED' if summary['passed'] else '❌ FAILED'}\")
    # Exit 0 if passed (0 violations), exit 1 if failed
    sys.exit(0 if summary['passed'] else 1)
"
