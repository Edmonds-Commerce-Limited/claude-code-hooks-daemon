#!/bin/bash
#
# run_canonical_callers_check.sh — Plan 00104 Phase 6 Task 6.2
#
# JSON wrapper around scripts/qa/check_canonical_callers.sh so the bash
# static-check fits the run_all.sh / llm_qa.py output contract.
#
# Writes untracked/qa/canonical_callers.json with this schema:
#   {
#     "tool": "canonical_callers",
#     "summary": { "total_violations": N, "passed": bool },
#     "violations": [ "<repo-relative-path>", ... ]
#   }
#
# Exit codes: 0 — clean; 1 — at least one violation.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CHECKER="${SCRIPT_DIR}/check_canonical_callers.sh"
OUTPUT_FILE="${PROJECT_ROOT}/untracked/qa/canonical_callers.json"

mkdir -p "$(dirname "${OUTPUT_FILE}")"

# Capture both streams; the underlying checker prints the violation list to
# stderr (R24 actionable directive). Stderr is preserved on the console for
# operator visibility but parsing happens in Python.
RAW_OUTPUT="$("${CHECKER}" 2>&1)"
RC=$?

# Resolve a Python interpreter for JSON emission via the canonical library
# (Plan 00104 Decision 7 — single source of truth for venv resolution).
# Stderr is NOT silenced — a genuine resolver failure should surface to the
# operator (silent-fallback antipattern; cf. v3.9.0 field bug).
# shellcheck source=../lib/resolve_venv.sh
source "${PROJECT_ROOT}/scripts/lib/resolve_venv.sh"
if ! PYTHON_BIN="$(resolve_venv_python "${PROJECT_ROOT}")"; then
    echo "run_canonical_callers_check: canonical resolver could not locate a venv python; cannot emit JSON" >&2
    exit 2
fi
if [ ! -x "${PYTHON_BIN}" ]; then
    echo "run_canonical_callers_check: resolved python is not executable: ${PYTHON_BIN}" >&2
    exit 2
fi

# All parsing is done in Python — no shell text manipulation. Raw output
# is passed via env var (avoids heredoc/pipe conflict, SC2259).
RAW_OUTPUT="${RAW_OUTPUT}" CHECKER_RC="${RC}" OUTPUT_FILE="${OUTPUT_FILE}" \
    "${PYTHON_BIN}" - << 'PYEOF'
import json
import os
import re

raw = os.environ["RAW_OUTPUT"]
checker_rc = int(os.environ["CHECKER_RC"])
output_path = os.environ["OUTPUT_FILE"]

# Header: "check_canonical_callers: <N> violations" or "<N> violation(s) found"
count = 0
match = re.search(r"check_canonical_callers:\s+(\d+)", raw)
if match:
    count = int(match.group(1))

# Violation paths: lines like "  /abs/path" or "  rel/path" indented 2 spaces.
violations = []
for line in raw.splitlines():
    if line.startswith("  ") and not line.startswith("   "):
        candidate = line.strip()
        if candidate and ("/" in candidate) and (" " not in candidate):
            violations.append(candidate)

passed = (checker_rc == 0) and (count == 0)

result = {
    "tool": "canonical_callers",
    "summary": {
        "total_violations": count,
        "passed": passed,
    },
    "violations": violations,
}

with open(output_path, "w") as fh:
    json.dump(result, fh, indent=2)
    fh.write("\n")
PYEOF

# Surface the human-readable directive on stderr (preserves R24 behaviour).
if [ "${RC}" -ne 0 ]; then
    printf '%s\n' "${RAW_OUTPUT}" >&2
fi

exit "${RC}"
