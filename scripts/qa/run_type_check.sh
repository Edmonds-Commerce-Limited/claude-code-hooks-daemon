#!/bin/bash
#
# Run mypy type checker and output results to JSON
#
# Exit codes:
#   0 - No type errors
#   1 - Type errors found
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_FILE="${PROJECT_ROOT}/untracked/qa/type_check.json"

# Source venv management
# shellcheck source=../venv-include.bash
source "${PROJECT_ROOT}/scripts/venv-include.bash"

# Source the shared gate scope (SSoT for which paths are examined)
# shellcheck source=./gate-scope.bash
source "${PROJECT_ROOT}/scripts/qa/gate-scope.bash"

cd "${PROJECT_ROOT}"

# Ensure venv and deps
ensure_venv || exit 1
if ! "${VENV_PYTHON}" -c "import mypy" 2>/dev/null; then
    install_deps || exit 1
fi

# Ensure output directory exists
mkdir -p "$(dirname "${OUTPUT_FILE}")"

echo "Running mypy type checker..."

# Run mypy with machine-readable output
# Note: mypy doesn't output JSON natively, so we parse text output
# --no-color-output ensures clean text for regex parsing (ANSI codes break the parser)
#
# --no-error-summary is deliberately NOT passed. That flag suppressed the only
# line carrying the number of files actually analysed ("Success: no issues found
# in N source files" / "Found N errors in M files (checked K source files)"), so
# the emitted JSON always reported `total_files_checked: 0` -- identical on a
# clean 378-file run and on a run where mypy aborted before checking anything.
# The parser below reads that summary line so the count is real, and `passed`
# now requires a non-zero count (see the FAIL FAST note there).
# NOT `mapfile` — that is bash 4+, and macOS ships /bin/bash 3.2.57.
# tests/integration/test_bash32_portability.py enforces this.
TYPE_PATHS=()
while IFS= read -r _scope_path; do
    TYPE_PATHS+=("${_scope_path}")
done < <(qa_type_paths)
if venv_tool mypy "${TYPE_PATHS[@]}" --no-color-output 2>&1 | tee "${OUTPUT_FILE}.raw"; then
    EXIT_CODE=0
else
    EXIT_CODE=$?
fi

# Parse mypy output and transform to JSON
python3 << 'EOF' > "${OUTPUT_FILE}"
import json
import re
import sys
from pathlib import Path

# Read mypy output
raw_file = Path("untracked/qa/type_check.json.raw")
errors = []
files_with_findings = set()
analysed_count = None

# mypy's closing summary, the only line that states how many files it actually
# analysed. Both spellings carry the count:
#   "Success: no issues found in 378 source files"
#   "Found 12 errors in 2 files (checked 378 source files)"
SUMMARY_PATTERNS = (
    re.compile(r'^Success: no issues found in (\d+) source files?$'),
    re.compile(r'^Found \d+ errors? in \d+ files? \(checked (\d+) source files?\)$'),
)

if raw_file.exists():
    with open(raw_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            for pattern in SUMMARY_PATTERNS:
                summary_match = pattern.match(line)
                if summary_match:
                    analysed_count = int(summary_match.group(1))
                    break

            # Parse mypy output format: file:line: error: message
            # Example: src/module.py:10: error: Incompatible types  [error-code]
            match = re.match(r'^([^:]+):(\d+): (error|warning|note): (.+)$', line)
            if match:
                file_path = match.group(1)
                line_num = int(match.group(2))
                severity = match.group(3)
                message = match.group(4)

                files_with_findings.add(file_path)

                if severity == "error":
                    errors.append({
                        "file": file_path,
                        "line": line_num,
                        "column": 0,  # mypy doesn't always provide column
                        "severity": severity,
                        "message": message,
                    })

# FAIL FAST: a type check that analysed NOTHING has not passed, it has not run.
# Previously `passed` was `len(errors) == 0`, computed only from parsed finding
# lines — so any failure that produced no `file:line: error:` output (a mypy
# usage error such as "X contains __init__.py but is not a valid Python package
# name", a bad path, an unreadable config) yielded zero findings and reported
# PASSED. Requiring a positive analysed count means the gate must show its work.
summary = {
    "total_files_checked": analysed_count if analysed_count is not None else 0,
    "total_errors": len(errors),
    "passed": len(errors) == 0 and bool(analysed_count),
}

# Output final JSON
output = {
    "tool": "mypy",
    "summary": summary,
    "errors": errors,
    # Files mypy reported findings against — NOT the full analysed set, which
    # mypy never enumerates. Named accordingly so the two are not confused.
    "files_with_findings": sorted(files_with_findings),
}

json.dump(output, sys.stdout, indent=2)
print()
EOF

# Clean up raw file
rm -f "${OUTPUT_FILE}.raw"

# Print summary
echo ""
echo "Type Check Results:"
python3 -c "
import json
with open('${OUTPUT_FILE}') as f:
    data = json.load(f)
    summary = data['summary']
    print(f\"  Files checked: {summary['total_files_checked']}\")
    print(f\"  Errors: {summary['total_errors']}\")
    print(f\"  Status: {'✅ PASSED' if summary['passed'] else '❌ FAILED'}\")
"

exit ${EXIT_CODE}
