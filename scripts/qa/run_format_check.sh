#!/bin/bash
#
# Run black formatter (auto-fixes by default) and output results to JSON
#
# Exit codes:
#   0 - All files formatted correctly
#   1 - Formatting issues found
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_FILE="${PROJECT_ROOT}/untracked/qa/format.json"

# Source venv management
source "${PROJECT_ROOT}/scripts/venv-include.bash"

cd "${PROJECT_ROOT}"

# Ensure venv and deps
ensure_venv || exit 1
if ! "${VENV_PYTHON}" -c "import black" 2>/dev/null; then
    install_deps || exit 1
fi

# Ensure output directory exists
mkdir -p "$(dirname "${OUTPUT_FILE}")"

echo "Running black formatter (auto-fixing)..."

# Run black to auto-format files
# Note: black doesn't output JSON, so we parse text output
if venv_tool black src/ tests/ 2>&1 | tee "${OUTPUT_FILE}.raw"; then
    EXIT_CODE=0
else
    EXIT_CODE=$?
fi

# Parse black output and transform to JSON
python3 << 'EOF' > "${OUTPUT_FILE}"
import json
import re
import sys
from pathlib import Path

raw_file = Path("untracked/qa/format.json.raw")
violations = []
files_checked = set()

if raw_file.exists():
    with open(raw_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Parse black output
            # Example: "reformatted /path/to/file.py"
            if "reformatted" in line and "would" not in line:
                match = re.search(r'reformatted (.+)$', line)
                if match:
                    file_path = match.group(1)
                    violations.append({
                        "file": file_path,
                        "message": "File was reformatted by black (auto-fixed)",
                    })

            # Track files checked
            # Example: "All done! ✨ 🍰 ✨"
            # or "Oh no! 💥 💔 💥"
            if re.search(r'\d+ files? (would be )?left unchanged', line):
                match = re.search(r'(\d+) files?', line)
                if match:
                    files_checked.add("checked")

            if re.search(r'(\d+) files? (would be )?reformatted', line):
                match = re.search(r'(\d+) files?', line)
                if match:
                    count = int(match.group(1))
                    # Already captured in violations list

# Build summary
summary = {
    "total_violations": len(violations),
    "passed": len(violations) == 0,
}

# Output final JSON
output = {
    "tool": "black",
    "summary": summary,
    "violations": violations,
}

json.dump(output, sys.stdout, indent=2)
print()
EOF

# Clean up raw file
rm -f "${OUTPUT_FILE}.raw"

# Print summary
echo ""
echo "Format Check Results:"
python3 -c "
import json
with open('${OUTPUT_FILE}') as f:
    data = json.load(f)
    summary = data['summary']
    print(f\"  Files needing formatting: {summary['total_violations']}\")
    print(f\"  Status: {'✅ PASSED' if summary['passed'] else '❌ FAILED'}\")
"

exit ${EXIT_CODE}
