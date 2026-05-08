#!/bin/bash
#
# Plan 00105 Phase 2 Task 2.1: capture-corruption gate.
#
# Runs scripts/qa/audit_capture_corruption.py against scripts/ and the
# bundled skill scripts. The audit enforces two rules:
#
#   1. Captured-function rule — any function called via $(name ...)
#      somewhere in the repo must only emit to stdout at terminal-return
#      positions. Mid-function status echoes corrupt the captured value.
#
#   2. Log-helper rule — functions named print_*, log_*, warn_*, err_*,
#      error_*, fail_*, die_*, info_* must redirect every echo/printf
#      with `>&2`. The v3.10.0 SEV-1 was a missing `>&2` on print_info
#      that ended up in every VAR=$(ensure_venv ...) capture in the
#      field, breaking every upgrade until v3.10.1 hot-patched it.
#
# Output: untracked/qa/capture_corruption.json
# Exit:   0 = clean, 1 = violations
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_FILE="${PROJECT_ROOT}/untracked/qa/capture_corruption.json"

cd "${PROJECT_ROOT}"

mkdir -p "$(dirname "${OUTPUT_FILE}")"

echo "Running capture-corruption audit..."

# The audit is pure stdlib — no venv required.
if python3 scripts/qa/audit_capture_corruption.py --json --output "${OUTPUT_FILE}"; then
    audit_exit=0
else
    audit_exit=$?
fi

# Print summary from the JSON the audit just produced.
python3 - "${OUTPUT_FILE}" <<'PYEOF'
import json
import sys
from pathlib import Path

output_file = Path(sys.argv[1])
data = json.loads(output_file.read_text())
summary = data["summary"]
total = summary["total_violations"]
print("")
print("Capture-Corruption Audit Results:")
print(f"  Total violations: {total}")
print(f"  Status: {'✅ PASSED' if summary['passed'] else '❌ FAILED'}")
if total > 0:
    print("")
    print("  First violations:")
    for v in data["violations"][:5]:
        print(f"    {v['file']}:{v['line']}  [{v['function']}]  [{v['rule']}]")
        print(f"      {v['message']}")
PYEOF

exit "${audit_exit}"
