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
# The QA_FORMAT_* overrides exist so tests/unit/qa/test_run_format_check.py
# can drive this exact wrapper against a planted target without touching the
# real scope (gate-scope.bash's ".") or the real untracked/qa/ output.
# Unset, they change nothing (00466 N21).
OUTPUT_DIR="${QA_FORMAT_OUTPUT_DIR:-${PROJECT_ROOT}/untracked/qa}"
OUTPUT_FILE="${OUTPUT_DIR}/format.json"

# Source venv management
# shellcheck source=../venv-include.bash
source "${PROJECT_ROOT}/scripts/venv-include.bash"

# Source the shared gate scope (SSoT for which paths are examined)
# shellcheck source=./gate-scope.bash
source "${PROJECT_ROOT}/scripts/qa/gate-scope.bash"

cd "${PROJECT_ROOT}"

# Ensure venv and deps
ensure_venv || exit 1
if ! "${VENV_PYTHON}" -c "import black" 2>/dev/null; then
    install_deps || exit 1
fi

# Ensure output directory exists
mkdir -p "${OUTPUT_DIR}"

echo "Running black formatter (auto-fixing)..."

# Run black to auto-format files
# Note: black doesn't output JSON, so we parse text output
# NOT `mapfile` — that is bash 4+, and macOS ships /bin/bash 3.2.57.
# tests/integration/test_bash32_portability.py enforces this.
FORMAT_PATHS=()
if [ -n "${QA_FORMAT_PATHS:-}" ]; then
    FORMAT_PATHS=("${QA_FORMAT_PATHS}")
else
    while IFS= read -r _scope_path; do
        FORMAT_PATHS+=("${_scope_path}")
    done < <(qa_format_paths)
fi
BLACK_BIN="${QA_FORMAT_BLACK_BIN:-${VENV_DIR}/bin/black}"

if "${BLACK_BIN}" "${FORMAT_PATHS[@]}" 2>&1 | tee "${OUTPUT_FILE}.raw"; then
    EXIT_CODE=0
else
    EXIT_CODE=$?
fi

# Parse black output and transform to JSON
"${VENV_PYTHON}" - "${OUTPUT_FILE}.raw" "${OUTPUT_FILE}" "${EXIT_CODE}" <<'PYEOF'
import json
import re
import sys
from pathlib import Path

raw_file = Path(sys.argv[1])
output_file = Path(sys.argv[2])
black_exit = int(sys.argv[3])

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

            # 00466 N21: black exits 123 ("error: cannot format ...") when a
            # file cannot even be PARSED -- distinct from a reformat, and the
            # old parser never looked for this line at all, so format.json
            # reported passed: true while the process correctly exited 123.
            # Example: "error: cannot format broken.py: Cannot parse ..."
            if line.startswith("error: cannot format"):
                match = re.search(r'error: cannot format (.+?):\s*(.*)$', line)
                if match:
                    file_path, reason = match.group(1), match.group(2)
                else:
                    file_path, reason = "", line
                violations.append({
                    "file": file_path,
                    "message": f"black could NOT format this file: {reason}",
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

# Build summary. black's own contract: 0 = nothing to do, 1 = files were
# reformatted, anything else (123 = "error: cannot format") means black did
# NOT complete formatting -- and a violations list built only from
# "reformatted ..." lines cannot see that failure, since black never gets to
# print one for a file it could not parse at all. `passed` must agree with
# the exit code, not just with what got parsed out of the transcript.
summary = {
    "total_violations": len(violations),
    "passed": len(violations) == 0 and black_exit in (0, 1),
}
if black_exit not in (0, 1):
    summary["error"] = (
        f"black exited {black_exit} (expected 0 or 1) -- it did not finish "
        "formatting, so this run cannot be reported as clean"
    )
    if not violations:
        # black failed but the transcript held no line this parser
        # recognised (message wording drifted, or the failure predates any
        # per-file report) -- report the exit code itself as the finding so
        # the count still implies detail.
        violations.append({
            "file": "",
            "message": summary["error"],
        })
        summary["total_violations"] = len(violations)

# Output final JSON
output = {
    "tool": "black",
    "summary": summary,
    "violations": violations,
}

output_file.write_text(json.dumps(output, indent=2) + "\n")
PYEOF

# Clean up raw file
rm -f "${OUTPUT_FILE}.raw"

# Print summary
echo ""
echo "Format Check Results:"
"${VENV_PYTHON}" -c "
import json
with open('${OUTPUT_FILE}') as f:
    data = json.load(f)
    summary = data['summary']
    print(f\"  Files needing formatting: {summary['total_violations']}\")
    print(f\"  Status: {'✅ PASSED' if summary['passed'] else '❌ FAILED'}\")
"

exit ${EXIT_CODE}
