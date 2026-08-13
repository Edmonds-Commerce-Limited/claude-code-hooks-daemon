#!/usr/bin/env bash
#
# Run the project's custom semgrep rules (Plan 00231).
#
# Ruff has no plugin mechanism, so project-specific "ban this code shape" rules
# used to mean one bespoke AST scanner per rule — a few hundred lines of Python
# plus its own test suite, catching a fraction of the spellings. Benchmarked
# against an 11-shape probe of the bounded-read defect class, the hand-written
# checker caught 1 and the equivalent semgrep rules caught 9.
#
# Rules live in scripts/qa/semgrep/*.yaml. Add a rule file there and it is
# picked up automatically — no wiring required.
#
# semgrep is a DEV dependency (pyproject [dev]); the client installer runs
# `uv pip install -e <dir>` with no [dev] extra, so it never ships to a client.
#
# Runs fully offline: local --config, metrics disabled, no registry fetch.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RULES_DIR="${SCRIPT_DIR}/semgrep"
OUTPUT_DIR="${REPO_ROOT}/untracked/qa"
OUTPUT_FILE="${OUTPUT_DIR}/semgrep.json"

# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/lib/resolve_venv.sh"
VENV_PYTHON="$(resolve_venv_python "${REPO_ROOT}")"
SEMGREP="$(dirname "${VENV_PYTHON}")/semgrep"

mkdir -p "${OUTPUT_DIR}"

if [ ! -x "${SEMGREP}" ]; then
    # FAIL LOUD: a missing linter that silently passes is worse than no check.
    # It reports green while examining nothing, which is the exact failure this
    # project's DBF standard exists to prevent.
    echo "ERROR: semgrep not found at ${SEMGREP}" >&2
    echo "Install dev dependencies:  uv pip install -e '.[dev]' --python ${VENV_PYTHON}" >&2
    printf '{"tool":"semgrep","summary":{"passed":false,"total_violations":0,"error":"semgrep not installed"},"violations":[]}\n' \
        > "${OUTPUT_FILE}"
    exit 1
fi

# Trees whose Python runs against files with no upper bound, mirroring the
# scan roots the rules were validated against.
SCAN_TARGETS=("${REPO_ROOT}/src" "${REPO_ROOT}/scripts")
if [ -d "${REPO_ROOT}/.claude/project-handlers" ]; then
    SCAN_TARGETS+=("${REPO_ROOT}/.claude/project-handlers")
fi

RAW_OUTPUT="${OUTPUT_DIR}/semgrep-raw.json"
"${SEMGREP}" scan \
    --config "${RULES_DIR}" \
    --metrics=off \
    --disable-version-check \
    --quiet \
    --json \
    --output "${RAW_OUTPUT}" \
    "${SCAN_TARGETS[@]}"
SEMGREP_EXIT=$?

if [ ! -s "${RAW_OUTPUT}" ]; then
    echo "ERROR: semgrep produced no output (exit ${SEMGREP_EXIT})" >&2
    printf '{"tool":"semgrep","summary":{"passed":false,"total_violations":0,"error":"no output"},"violations":[]}\n' \
        > "${OUTPUT_FILE}"
    exit 1
fi

# Normalise into the shape every other QA check emits, so llm_qa.py and
# run_all.sh consume it identically.
"${VENV_PYTHON}" - "${RAW_OUTPUT}" "${OUTPUT_FILE}" <<'PYEOF'
import json
import sys
from pathlib import Path

raw = json.loads(Path(sys.argv[1]).read_text())
violations = [
    {
        "file": r.get("path", ""),
        "line": r.get("start", {}).get("line", 0),
        "rule": r.get("check_id", "").split(".")[-1],
        "message": " ".join(r.get("extra", {}).get("message", "").split()),
    }
    for r in raw.get("results", [])
]
output = {
    "tool": "semgrep",
    "summary": {"passed": not violations, "total_violations": len(violations)},
    "violations": violations,
}
Path(sys.argv[2]).write_text(json.dumps(output, indent=2))

if violations:
    print(f"Found {len(violations)} semgrep violations:")
    for v in violations:
        print(f"  {v['file']}:{v['line']}  [{v['rule']}]")
else:
    print("No semgrep violations found")
sys.exit(1 if violations else 0)
PYEOF
exit $?
