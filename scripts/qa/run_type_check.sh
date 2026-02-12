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
source "${PROJECT_ROOT}/scripts/venv-include.bash"

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
if venv_tool mypy src/ --no-error-summary --no-color-output 2>&1 | tee "${OUTPUT_FILE}.raw"; then
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
files_checked = set()

if raw_file.exists():
    with open(raw_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Parse mypy output format: file:line: error: message
            # Example: src/module.py:10: error: Incompatible types  [error-code]
            match = re.match(r'^([^:]+):(\d+): (error|warning|note): (.+)$', line)
            if match:
                file_path = match.group(1)
                line_num = int(match.group(2))
                severity = match.group(3)
                message = match.group(4)

                files_checked.add(file_path)

                if severity == "error":
                    errors.append({
                        "file": file_path,
                        "line": line_num,
                        "column": 0,  # mypy doesn't always provide column
                        "severity": severity,
                        "message": message,
                    })

# Build summary
summary = {
    "total_files_checked": len(files_checked),
    "total_errors": len(errors),
    "passed": len(errors) == 0,
}

# Output final JSON
output = {
    "tool": "mypy",
    "summary": summary,
    "errors": errors,
    "files": sorted(list(files_checked)),
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
